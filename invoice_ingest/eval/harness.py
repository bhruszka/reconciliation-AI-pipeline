from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from invoice_ingest import config
from invoice_ingest.eval import runner
from invoice_ingest.eval.accuracy import score_accuracy
from invoice_ingest.eval.grounding import score_grounding
from invoice_ingest.eval.report import build_report, print_report
from invoice_ingest.eval.schema import EvalReport
from invoice_ingest.ingest import process_pdf
from invoice_ingest.parsing.llm import DEFAULT_MODEL
from invoice_ingest.shared.reconcile import build_consensus

logger = logging.getLogger(__name__)

GOLDEN = Path("golden/golden_set.json")
EVAL_RESULT_DIR = Path("eval_results")


def _load_golden(path: Path) -> tuple[list[dict], dict[str, dict]]:
    """Return (invoices, labels_by_path) from the golden set."""
    data = json.loads(path.read_text(encoding="utf-8"))
    invoices = data["invoices"]
    labels = {inv["invoice_path"]: inv["labels"] for inv in invoices}
    return invoices, labels


def run_golden(model: str, golden_path: Path = GOLDEN) -> tuple[EvalReport, list[dict]]:
    """Run the whole golden set through all applicable views and score it."""
    invoices, labels = _load_golden(golden_path)
    repo_root = Path.cwd()

    records: list[dict] = []
    cost_by_view: dict[str, float] = defaultdict(float)
    cost_by_inv_view: dict[tuple[str, str], float] = {}  # (invoice, view) -> USD
    for inv in invoices:
        pdf = repo_root / inv["invoice_path"]
        enriched = process_pdf(pdf, repo_root)  # ingest: pdf_text + ocr_text
        for result in runner.run_all_views(enriched, model):  # routed: text skips image
            cost = result.usage.cost_usd if result.usage and result.usage.cost_usd else 0.0
            records.append(result.model_dump(mode="json"))
            cost_by_view[result.view] += cost
            cost_by_inv_view[(result.invoice_path, result.view)] = cost

    consensus = build_consensus(records)
    records += consensus
    # Consensus makes no API call of its own, but each record is the product of two
    # runs (OCR + its partner view). Attribute that combined cost so it isn't $0.
    cost_by_view["consensus"] = sum(
        cost_by_inv_view.get((c["invoice_path"], "ocr"), 0.0)
        + cost_by_inv_view.get((c["invoice_path"], c["partner"]), 0.0)
        for c in consensus
    )

    tallies, failures = score_accuracy(labels, records)
    grounding = score_grounding(labels, records)

    report = build_report(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        model=model,
        golden_count=len(invoices),
        tallies=tallies,
        grounding=grounding,
        failures=failures,
        cost_by_view=dict(cost_by_view),
    )
    return report, records


def _save(report: EvalReport, records: list[dict]) -> Path:
    EVAL_RESULT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = f"{stamp}_{config.model_slug(report.meta.model)}"
    report_path = EVAL_RESULT_DIR / f"eval_{tag}.json"
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    ext_path = EVAL_RESULT_DIR / f"extractions_{tag}.jsonl"
    ext_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return report_path


def main() -> int:
    config.setup_logging()
    parser = argparse.ArgumentParser(description="Run the golden set and score it.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="model slug (LLM_MODEL)")
    parser.add_argument("--golden", default=str(GOLDEN))
    args = parser.parse_args()

    report, records = run_golden(args.model, Path(args.golden))
    report_path = _save(report, records)
    print_report(report)  # the report tables -> stdout (the deliverable)
    logger.info("wrote %s", report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
