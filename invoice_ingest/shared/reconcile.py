#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from invoice_ingest.shared.compare import FIELDS, values_match


def _ran_ok(record: dict | None) -> bool:
    """True if this view produced a usable extraction (ran, no error)."""
    return record is not None and record.get("status") == "ok"


def _field(record: dict | None, field: str) -> dict:
    """The extractor's field dict, or an empty one if the view is unusable."""
    if record is None or not _ran_ok(record):
        return {}
    return (record.get("extraction") or {}).get(field, {})


def reconcile_invoice(views: dict[str, dict]) -> dict:
    """Build the consensus record for one invoice from its per-view records."""
    ocr = views.get("ocr")
    text = views.get("text")
    # Partner: the text layer if it ran ok (present on this invoice), else vision.
    partner_view = "text" if _ran_ok(text) else "vision"
    partner = text if _ran_ok(text) else views.get("vision")

    extraction: dict[str, dict] = {}
    for field in FIELDS:
        ocr_f, par_f = _field(ocr, field), _field(partner, field)
        v_ocr, v_par = ocr_f.get("value"), par_f.get("value")

        if v_ocr is not None and v_par is not None and values_match(field, v_ocr, v_par):
            value, agreement = v_ocr, True            # both agree on a value
        elif v_ocr is None and v_par is None:
            value, agreement = None, True             # both agree the field is absent
        else:
            value, agreement = None, False            # differ, or only one has it

        # OCR is always the text-grounded anchor — carry its quote/grounding when we
        # emit a value.
        extraction[field] = {
            "value": value,
            "source_quote": ocr_f.get("source_quote", "") if value is not None else "",
            "quote_found": ocr_f.get("quote_found") if value is not None else None,
            "agreement": agreement,
        }

    invoice_path = (ocr or partner or {}).get("invoice_path")
    return {
        "invoice_path": invoice_path,
        "view": "consensus",
        "partner": partner_view,
        "status": "ok",
        "extraction": extraction,
    }


def group_by_invoice(records: list[dict]) -> dict[str, dict[str, dict]]:
    """invoice_path -> {view: record}."""
    groups: dict[str, dict[str, dict]] = defaultdict(dict)
    for rec in records:
        groups[rec["invoice_path"]][rec["view"]] = rec
    return groups


def build_consensus(records: list[dict]) -> list[dict]:
    """One consensus record per invoice."""
    return [reconcile_invoice(views) for views in group_by_invoice(records).values()]


def load_records(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _fmt(value) -> str:
    return "—" if value is None else str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extractions", default="extractions.jsonl")
    args = parser.parse_args()

    records = load_records(Path(args.extractions))
    for cons in sorted(build_consensus(records), key=lambda c: c["invoice_path"] or ""):
        name = Path(cons["invoice_path"]).stem
        print(f"\n=== {name}  (consensus: ocr + {cons['partner']}) ===")
        print(f"  {'field':<15} {'value':<24} {'agree':>6} {'grounded':>9}")
        for field, f in cons["extraction"].items():
            grounded = {True: "yes", False: "NO", None: "—"}[f["quote_found"]]
            print(
                f"  {field:<15} {_fmt(f['value']):<24} "
                f"{('yes' if f['agreement'] else 'NO'):>6} {grounded:>9}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
