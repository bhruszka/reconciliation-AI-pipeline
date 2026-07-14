"""Report assembly: build_report turns tallies/grounding/costs into the model."""
from __future__ import annotations

from invoice_ingest.eval.accuracy import Outcome, score_accuracy
from invoice_ingest.eval.grounding import score_grounding
from invoice_ingest.eval.report import build_report
from invoice_ingest.eval.schema import EvalReport
from tests.factories import CLEAN_LABELS, agent_record

GOLDEN = {"golden/pdfs/inv.pdf": CLEAN_LABELS}


def _report_from(records, cost_by_view):
    """Score the given records and assemble a report (test helper / arrange step)."""
    tallies, failures = score_accuracy(GOLDEN, records)
    grounding = score_grounding(GOLDEN, records)
    return build_report(
        timestamp="2026-07-13 00:00:00",
        model="test-model",
        golden_count=1,
        tallies=tallies,
        grounding=grounding,
        failures=failures,
        cost_by_view=cost_by_view,
    )


def test_build_report_returns_eval_report():
    # Arrange
    records = [agent_record("ocr", CLEAN_LABELS)]

    # Act
    report = _report_from(records, {"ocr": 0.05})

    # Assert
    assert isinstance(report, EvalReport)


def test_overall_accuracy_and_meta():
    # Arrange
    records = [agent_record("ocr", CLEAN_LABELS)]

    # Act
    report = _report_from(records, {"ocr": 0.05})

    # Assert
    assert report.accuracy["ocr"].overall.accuracy == 1.0
    assert report.accuracy["ocr"].cost_usd == 0.05
    assert report.meta.total_cost_usd == 0.05
    assert report.meta.model == "test-model"


def test_failure_lowers_field_accuracy():
    # Arrange
    records = [agent_record("ocr", dict(CLEAN_LABELS, amount="1.00"))]

    # Act
    report = _report_from(records, {"ocr": 0.0})

    # Assert
    assert report.accuracy["ocr"].fields["amount"].accuracy == 0.0
    assert report.accuracy["ocr"].fields["amount"].hallucination == 1
    assert report.failures[0].outcome == Outcome.HALLUCINATION.value


def test_report_round_trips_through_json():
    # Arrange
    report = _report_from([agent_record("ocr", CLEAN_LABELS)], {"ocr": 0.05})

    # Act
    restored = EvalReport.model_validate_json(report.model_dump_json())

    # Assert
    assert restored == report
