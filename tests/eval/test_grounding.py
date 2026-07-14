"""Grounding scoring: verified quotes over checkable values, per view."""
from __future__ import annotations

from invoice_ingest.eval.grounding import score_grounding
from tests.factories import CLEAN_LABELS, agent_record

GOLDEN = {"golden/pdfs/inv.pdf": CLEAN_LABELS}


def test_all_grounded_is_full_rate():
    # Arrange
    records = [agent_record("ocr", CLEAN_LABELS, quote_found=True)]

    # Act
    grounding = score_grounding(GOLDEN, records)["ocr"]

    # Assert
    assert grounding.grounded == grounding.checkable == 7  # all 7 fields present & grounded
    assert grounding.rate == 1.0


def test_ungrounded_lowers_the_rate():
    # Arrange
    records = [agent_record("ocr", CLEAN_LABELS, quote_found=False)]

    # Act
    grounding = score_grounding(GOLDEN, records)["ocr"]

    # Assert
    assert grounding.grounded == 0
    assert grounding.checkable == 7
    assert grounding.rate == 0.0


def test_vision_quote_found_none_is_not_checkable():
    # Arrange — quote_found=None (vision / evidence-only) is excluded from stats.
    records = [agent_record("vision", CLEAN_LABELS, quote_found=None)]

    # Act
    grounding = score_grounding(GOLDEN, records)

    # Assert
    assert "vision" not in grounding


def test_absent_value_is_not_checkable():
    # Arrange
    records = [agent_record("ocr", dict(CLEAN_LABELS, po_reference=None), quote_found=True)]

    # Act
    grounding = score_grounding(GOLDEN, records)["ocr"]

    # Assert
    assert grounding.checkable == 6  # po_reference absent → not counted


def test_errored_record_is_skipped():
    # Arrange
    records = [agent_record("ocr", CLEAN_LABELS, status="error")]

    # Act
    grounding = score_grounding(GOLDEN, records)

    # Assert
    assert grounding == {}
