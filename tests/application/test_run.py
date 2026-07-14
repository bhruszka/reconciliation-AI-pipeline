"""The e2e triage CSV: one row per invoice with annotations + both confidences."""
from __future__ import annotations

import csv

from invoice_ingest.application.matcher import triage_all
from invoice_ingest.application.run import CSV_COLUMNS, write_csv
from tests.factories import CLEAN_LABELS, bank_txn, consensus_record


def _write_and_read(tmp_path, consensus, results):
    out = tmp_path / "triage.csv"
    write_csv(out, consensus, results)
    with out.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_csv_has_expected_columns_and_one_row_per_invoice(tmp_path):
    # Arrange
    consensus = [consensus_record()]
    results = triage_all(consensus, [bank_txn()])

    # Act
    rows = _write_and_read(tmp_path, consensus, results)

    # Assert
    assert len(rows) == 1
    row = rows[0]
    assert list(row.keys()) == CSV_COLUMNS
    # annotations
    assert row["invoice"] == "inv"
    assert row["invoice_id"] == "INV-1001"
    assert row["amount"] == "1000.00"
    # both confidences + decision + reason summaries
    assert row["decision"] == "auto_accept"
    assert row["match_score"] == "100"
    assert row["approval_score"] == "100"
    assert row["match_confidence"]
    assert row["approval_confidence"]


def test_absent_annotation_renders_empty(tmp_path):
    # Arrange
    consensus = [consensus_record(dict(CLEAN_LABELS, po_reference=None))]
    results = triage_all(consensus, [bank_txn()])

    # Act
    rows = _write_and_read(tmp_path, consensus, results)

    # Assert
    assert rows[0]["po_reference"] == ""


def test_reason_summary_reflects_fx_review(tmp_path):
    # Arrange
    consensus = [consensus_record(dict(CLEAN_LABELS, currency="EUR"))]
    results = triage_all(consensus, [bank_txn(amount="7450.00")])

    # Act
    rows = _write_and_read(tmp_path, consensus, results)

    # Assert
    assert rows[0]["decision"] == "review"
    assert "FX" in rows[0]["approval_confidence"]
