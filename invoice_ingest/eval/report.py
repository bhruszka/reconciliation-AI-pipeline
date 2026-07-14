from __future__ import annotations

import argparse
from pathlib import Path

from invoice_ingest.eval.schema import (
    EvalReport,
    Failure,
    FieldAccuracy,
    Grounding,
    Outcome,
    ReportMeta,
    ViewAccuracy,
)
from invoice_ingest.shared.compare import FIELDS


def _field_accuracy(counts: dict) -> FieldAccuracy:
    correct = counts.get(Outcome.CORRECT, 0)
    hallucination = counts.get(Outcome.HALLUCINATION, 0)
    miss = counts.get(Outcome.MISS, 0)
    total = correct + hallucination + miss
    return FieldAccuracy(
        correct=correct, hallucination=hallucination, miss=miss, total=total,
        accuracy=(correct / total if total else 0.0),
    )


def build_report(
    *,
    timestamp: str,
    model: str,
    golden_count: int,
    tallies: dict,
    grounding: dict[str, Grounding],
    failures: list[dict],
    cost_by_view: dict[str, float],
) -> EvalReport:
    """Assemble the report from raw tallies / grounding / costs."""
    accuracy: dict[str, ViewAccuracy] = {}
    for view, per_field in tallies.items():
        overall: dict = {}
        fields = {}
        for field in FIELDS:
            fields[field] = _field_accuracy(per_field[field])
            for outcome, n in per_field[field].items():
                overall[outcome] = overall.get(outcome, 0) + n
        accuracy[view] = ViewAccuracy(
            cost_usd=cost_by_view.get(view),
            fields=fields,
            overall=_field_accuracy(overall),
        )

    # Total is real API spend only — "consensus" is a derived attribution of the
    # OCR + partner runs, so counting it here would double-count.
    total_cost = sum(c for view, c in cost_by_view.items() if view != "consensus")
    return EvalReport(
        meta=ReportMeta(
            timestamp=timestamp, model=model, golden_count=golden_count,
            views=sorted(accuracy), total_cost_usd=total_cost,
        ),
        accuracy=accuracy,
        grounding=grounding,
        failures=[Failure(**f) for f in failures],
    )


def print_report(report: EvalReport) -> None:
    """Pretty-print a report (accuracy, grounding, failures) from the model."""
    for view in sorted(report.accuracy):
        va = report.accuracy[view]
        cost = f"${va.cost_usd:.5f}" if va.cost_usd is not None else "—"
        print(f"\n=== agent: {view}   (cost {cost}) ===")
        print(f"  {'field':<15} {'correct':>7} {'halluc':>7} {'miss':>6} {'acc':>6}")
        for field in FIELDS:
            fa = va.fields[field]
            note = "" if fa.total else "   (not run)"
            print(f"  {field:<15} {fa.correct:>7} {fa.hallucination:>7} {fa.miss:>6} "
                  f"{fa.accuracy:>5.0%}{note}")
        o = va.overall
        print(f"  {'ALL':<15} {o.correct:>7} {o.hallucination:>7} {o.miss:>6} {o.accuracy:>5.0%}")

    print("\n=== grounding (verified quotes / checkable values) ===")
    for view in sorted(report.grounding):
        g = report.grounding[view]
        print(f"  {view:<10} {g.grounded:>2}/{g.checkable:<2}  {g.rate:>4.0%}")

    if report.failures:
        print("\n=== failures (for analysis) ===")
        for f in sorted(report.failures, key=lambda x: (x.view, x.invoice, x.field)):
            name = Path(f.invoice).stem
            print(f"  [{f.outcome:<13}] {name:<12} {f.view:<9} {f.field:<14} "
                  f"gold={f.gold!r}  extracted={f.extracted!r}")

    m = report.meta
    print("\n=== overall ===")
    print(f"  model      : {m.model}")
    print(f"  timestamp  : {m.timestamp}")
    print(f"  golden     : {m.golden_count} invoices, views {m.views}")
    print(f"  total cost : ${m.total_cost_usd:.5f}")


def load_report(path: Path) -> EvalReport:
    return EvalReport.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Print one or more saved eval reports.")
    parser.add_argument("reports", nargs="+", help="Path(s) to eval_results/*.json report(s)")
    args = parser.parse_args()
    for path in args.reports:
        print_report(load_report(Path(path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
