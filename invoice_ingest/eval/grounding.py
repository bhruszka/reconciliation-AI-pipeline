from __future__ import annotations

from collections import defaultdict

from invoice_ingest.eval.schema import Grounding


def score_grounding(golden: dict[str, dict], records: list[dict]) -> dict[str, Grounding]:
    """Per view, the share of present values whose source_quote was verified.

    A value is *checkable* when it's present and `quote_found` is a bool. Vision
    (evidence-only) and null fields have `quote_found=None` → not checkable.
    """
    tally: dict = defaultdict(lambda: {"grounded": 0, "checkable": 0})
    for rec in records:
        if rec["invoice_path"] not in golden or rec.get("status") == "error":
            continue
        for f in (rec.get("extraction") or {}).values():
            if f.get("value") is None or f.get("quote_found") is None:
                continue
            tally[rec["view"]]["checkable"] += 1
            tally[rec["view"]]["grounded"] += 1 if f["quote_found"] else 0

    out: dict[str, Grounding] = {}
    for view, g in tally.items():
        rate = g["grounded"] / g["checkable"] if g["checkable"] else 0.0
        out[view] = Grounding(grounded=g["grounded"], checkable=g["checkable"], rate=rate)
    return out
