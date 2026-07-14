"""Accuracy grading: the classify truth table and score_accuracy tallies."""
from __future__ import annotations

import pytest

from invoice_ingest.eval.accuracy import Outcome, classify, score_accuracy
from tests.factories import CLEAN_LABELS, agent_record

GOLDEN = {"golden/pdfs/inv.pdf": CLEAN_LABELS}


class TestClassify:
    @pytest.mark.parametrize(
        ("field", "gold", "extracted", "expected"),
        [
            ("amount", "1000.00", "1000", Outcome.CORRECT),        # right value
            ("amount", "1000.00", "999", Outcome.HALLUCINATION),   # wrong value
            ("amount", "1000.00", None, Outcome.MISS),             # abstained, value exists
            ("po_reference", None, None, Outcome.CORRECT),         # abstained, absent
            ("po_reference", None, "PO-1", Outcome.HALLUCINATION),  # value where absent
        ],
    )
    def test_truth_table(self, field, gold, extracted, expected):
        # Arrange — inputs from parametrize

        # Act
        outcome = classify(field, gold, extracted)

        # Assert
        assert outcome is expected


class TestScoreAccuracy:
    def test_all_correct_has_no_failures(self):
        # Arrange
        records = [agent_record("ocr", CLEAN_LABELS)]

        # Act
        tallies, failures = score_accuracy(GOLDEN, records)

        # Assert
        assert failures == []
        assert tallies["ocr"]["amount"][Outcome.CORRECT] == 1

    def test_wrong_field_produces_a_failure(self):
        # Arrange
        records = [agent_record("ocr", dict(CLEAN_LABELS, amount="1.00"))]

        # Act
        _tallies, failures = score_accuracy(GOLDEN, records)

        # Assert
        amount_failures = [f for f in failures if f["field"] == "amount"]
        assert len(amount_failures) == 1
        assert amount_failures[0]["outcome"] == Outcome.HALLUCINATION.value
        assert amount_failures[0]["gold"] == "1000.00"

    def test_records_outside_golden_are_ignored(self):
        # Arrange
        records = [agent_record("ocr", CLEAN_LABELS, invoice_path="other.pdf")]

        # Act
        tallies, failures = score_accuracy(GOLDEN, records)

        # Assert
        assert tallies == {}
        assert failures == []

    def test_errored_record_is_skipped_not_graded_as_misses(self):
        # Arrange — an errored view (bad PDF / failed call) has no extraction. It
        # must not be graded, or an infra failure would read as the extractor
        # missing every field.
        records = [agent_record("ocr", CLEAN_LABELS, status="error")]

        # Act
        tallies, failures = score_accuracy(GOLDEN, records)

        # Assert
        assert tallies == {}
        assert failures == []
