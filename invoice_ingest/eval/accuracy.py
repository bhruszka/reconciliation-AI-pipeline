from __future__ import annotations

import logging
from collections import defaultdict

from invoice_ingest.eval.schema import Outcome
from invoice_ingest.shared.compare import FIELDS, values_match

logger = logging.getLogger(__name__)


def classify(field: str, gold_value, extracted_value) -> Outcome:
    """Grade one field. `None` = absent / abstained, on either side.

    Step 1 — did the extractor answer at all?
        abstained (extracted is None):
            - field absent in gold  -> CORRECT  (a proper abstention)
            - field has a value     -> MISS     (admitted unknown, but there was an answer)
    Step 2 — the extractor produced a value; is it right?
        - gold has no value  -> HALLUCINATION  (invented a value for an absent field)
        - values match       -> CORRECT
        - values differ      -> HALLUCINATION  (confident, but wrong)
    """
    if extracted_value is None:
        return Outcome.CORRECT if gold_value is None else Outcome.MISS
    if gold_value is None:
        return Outcome.HALLUCINATION
    if values_match(field, gold_value, extracted_value):
        return Outcome.CORRECT
    return Outcome.HALLUCINATION


def _extracted_value(record: dict, field: str):
    extraction = record.get("extraction")
    if not extraction:  # None -> the (invoice, view) errored
        return None
    return extraction.get(field, {}).get("value")


def score_accuracy(golden: dict[str, dict], records: list[dict]) -> tuple[dict, list]:
    """Grade every record's fields against the gold labels.

    Returns (tallies, failures):
      tallies[view][field] = {Outcome: count}
      failures = [{invoice, view, field, outcome, gold, extracted}, ...]  (non-correct)
    """
    tallies: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    failures: list[dict] = []
    for rec in records:
        if rec.get("status") == "error":
            # Errored view (bad PDF / failed call): no extraction to grade. Skip it —
            # as grounding/reconcile do — so an infra failure isn't scored as misses.
            logger.warning(
                "skipping errored view in accuracy: %s / %s — %s",
                rec.get("invoice_path"), rec.get("view"), rec.get("error"),
            )
            continue
        labels = golden.get(rec["invoice_path"])
        if labels is None:  # not part of the golden set
            continue
        view = rec["view"]
        for field in FIELDS:
            gold_val = labels[field]
            ext_val = _extracted_value(rec, field)
            outcome = classify(field, gold_val, ext_val)
            tallies[view][field][outcome] += 1
            if outcome is not Outcome.CORRECT:
                failures.append(
                    {
                        "invoice": rec["invoice_path"],
                        "view": view,
                        "field": field,
                        "outcome": outcome.value,
                        "gold": gold_val,
                        "extracted": ext_val,
                    }
                )
    return tallies, failures
