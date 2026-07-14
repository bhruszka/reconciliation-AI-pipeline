#!/usr/bin/env python3
"""End-to-end pipeline: PDFs → ingest → extract → reconcile → triage.

One invocation processes a whole folder of invoices and writes a self-contained
run directory under `results/<timestamp>/`:

  ingested.jsonl     the OCR + PDF-text per invoice (Task 1)
  extractions.jsonl  every agent view's structured extraction (Task 1/2)
  triage.csv         one row per invoice — extracted annotations, the two
                     confidence scores (match + approval), the decision, and a
                     reason summary explaining the confidence in both.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime
from pathlib import Path

from invoice_ingest import config
from invoice_ingest.application.matcher import load_bank, print_triage, triage_all
from invoice_ingest.eval.runner import DEFAULT_MODEL, run_all_views
from invoice_ingest.ingest import process_pdf, resolve
from invoice_ingest.parsing.schema import EnrichedInvoice
from invoice_ingest.shared.compare import FIELDS
from invoice_ingest.shared.reconcile import build_consensus

logger = logging.getLogger(__name__)

RESULTS_ROOT = Path("results")


# --------------------------------------------------------------------- stages

def ingest_pdfs(pdfs: list[Path], repo_root: Path) -> list[EnrichedInvoice]:
    """Task 1 — OCR + PDF text for every PDF."""
    enriched = []
    for pdf in pdfs:
        record = process_pdf(pdf, repo_root)
        enriched.append(record)
        image_only = "  [IMAGE-ONLY]" if not record.pdf_text else ""
        logger.info("ingest  %-30s text=%6d ocr=%6d%s", record.invoice_path,
                    len(record.pdf_text), len(record.ocr_text), image_only)
    return enriched


def extract_all(enriched: list[EnrichedInvoice], model: str) -> list[dict]:
    """Task 1/2 — run every applicable agent view (routed) over each invoice."""
    records: list[dict] = []
    total_cost = 0.0
    for record in enriched:
        for result in run_all_views(record, model):
            records.append(result.model_dump(mode="json"))
            cost = result.usage.cost_usd if result.usage and result.usage.cost_usd else 0.0
            total_cost += cost
            logger.info("extract %-30s %-7s %s", record.invoice_path, result.view, result.status)
    logger.info("extract total cost $%.5f", total_cost)
    return records


# ----------------------------------------------------------------------- CSV

# The extracted values we surface as annotations, in column order.
ANNOTATION_FIELDS = FIELDS

CSV_COLUMNS = (
    ["invoice", *ANNOTATION_FIELDS]
    + ["decision", "match_score", "match_confidence",
       "approval_score", "approval_confidence", "txn_id"]
)


def _row(consensus: dict, result: dict) -> dict:
    """One CSV row: extracted annotations + both confidences + decision + reasons."""
    extraction = consensus["extraction"]
    row = {"invoice": Path(consensus["invoice_path"]).stem}
    for field in ANNOTATION_FIELDS:
        value = extraction[field]["value"]
        row[field] = "" if value is None else value
    row.update(
        decision=result["status"],
        match_score=result["match_score"],
        match_confidence="; ".join(result["match_reasons"]),
        approval_score=result["approval_score"],
        approval_confidence="; ".join(result["approval_reasons"]),
        txn_id=result["txn_id"] or "",
    )
    return row


def write_csv(path: Path, consensus: list[dict], results: list[dict]) -> None:
    """Write the annotations + confidences CSV, one row per invoice."""
    by_path = {c["invoice_path"]: c for c in consensus}
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for result in results:
            writer.writerow(_row(by_path[result["invoice_path"]], result))


# ------------------------------------------------------------------ orchestrate

def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def run_pipeline(pdf_dir: Path, bank_csv: Path, model: str, stamp: str) -> Path:
    """Run the whole pipeline and write results/<stamp>/. Returns the run dir."""
    repo_root = Path.cwd()
    pdfs = sorted(resolve(str(pdf_dir), repo_root).glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDFs found in {pdf_dir}")

    run_dir = RESULTS_ROOT / f"{stamp}_{config.model_slug(model)}"
    run_dir.mkdir(parents=True, exist_ok=True)

    logger.info("[1/3] ingest  (%d PDFs)", len(pdfs))
    enriched = ingest_pdfs(pdfs, repo_root)
    _write_jsonl(run_dir / "ingested.jsonl", [r.model_dump_json() for r in enriched])

    logger.info("[2/3] extract (model %s)", model)
    records = extract_all(enriched, model)
    _write_jsonl(run_dir / "extractions.jsonl",
                 [json.dumps(r, ensure_ascii=False) for r in records])

    logger.info("[3/3] triage")
    consensus = build_consensus(records)
    txns = load_bank(bank_csv)
    results = triage_all(consensus, txns)
    write_csv(run_dir / "triage.csv", consensus, results)

    counts = print_triage(results)  # the triage table -> stdout (the deliverable)
    logger.info("wrote %s/  (%d auto-accept, %d review, %d reject)", run_dir,
                counts["auto_accept"], counts["review"], counts["reject"])
    return run_dir


# ------------------------------------------------------------------------- CLI

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pdf-dir", default="input/pdf_invoices", help="Folder of invoice PDFs")
    p.add_argument("--bank", default="input/bank_transactions.csv")
    p.add_argument("--model", default=DEFAULT_MODEL, help="model slug (LLM_MODEL)")
    return p.parse_args()


def main() -> int:
    config.setup_logging()
    args = parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        run_pipeline(Path(args.pdf_dir), Path(args.bank), args.model, stamp)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
