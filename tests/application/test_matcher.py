"""Match/approval scoring and triage routing (the core Task 3 logic)."""
from __future__ import annotations

import pytest

from invoice_ingest.application.matcher import (
    amount_exact,
    approval_score,
    date_ok,
    diagnose_amount,
    extraction_issues,
    find_match,
    match_score,
    triage,
)
from tests.factories import CLEAN_LABELS, bank_txn, consensus_record


class TestMatchScore:
    @pytest.mark.parametrize(
        ("ref_match", "name_score", "expected"),
        [
            (True, 100, 100),  # reference + strong name → near perfect
            (True, 0, 60),     # reference only (bank name too truncated to score)
            (False, 90, 36),   # name only (0.40 * 90)
        ],
    )
    def test_identity_score(self, ref_match, name_score, expected):
        # Arrange — inputs from parametrize

        # Act
        result = match_score(ref_match=ref_match, name_score=name_score)

        # Assert
        assert result == expected


class TestApprovalScore:
    @pytest.mark.parametrize(
        ("amount_exact", "amount_category", "date_ok", "expected"),
        [
            (True, None, True, 100),          # exact amount + date
            (False, "fx", True, 65),          # benign mismatch → partial amount credit
            (False, "batch", True, 65),       # benign mismatch → partial amount credit
            (False, "unexplained", True, 30), # unexplained → no amount credit
            (True, None, False, 70),          # missing date drops 30
        ],
    )
    def test_reconciliation_score(self, amount_exact, amount_category, date_ok, expected):
        # Arrange — inputs from parametrize

        # Act
        result = approval_score(amount_exact, amount_category, date_ok)

        # Assert
        assert result == expected


class TestAmountExact:
    def test_exact_dkk_matches(self):
        # Arrange
        cons = consensus_record()
        txn = bank_txn(amount="1000.00")

        # Act
        result = amount_exact(cons, txn)

        # Assert
        assert result is True

    def test_foreign_currency_never_exact(self):
        # Arrange
        cons = consensus_record(dict(CLEAN_LABELS, currency="EUR"))
        txn = bank_txn(amount="1000.00")

        # Act
        result = amount_exact(cons, txn)

        # Assert
        assert result is False


class TestDateOk:
    @pytest.mark.parametrize(
        ("payment_date", "expected"),
        [
            ("2026-04-10", True),   # inside the invoice→due window (+ grace)
            ("2026-08-01", False),  # far outside the window
        ],
    )
    def test_payment_within_window(self, payment_date, expected):
        # Arrange
        cons = consensus_record()
        txn = bank_txn(date=payment_date)

        # Act
        result = date_ok(cons, txn)

        # Assert
        assert result is expected

    def test_missing_due_date_uses_invoice_date(self):
        # Arrange — only invoice_date (2026-04-01) present; payment lands on it.
        cons = consensus_record(dict(CLEAN_LABELS, due_date=None))
        txn = bank_txn(date="2026-04-01")

        # Act / Assert — the single present date defines the window (not zeroed out).
        assert date_ok(cons, txn) is True

    def test_missing_invoice_date_uses_due_date(self):
        # Arrange — only due_date (2026-04-15) present; payment lands on it.
        cons = consensus_record(dict(CLEAN_LABELS, invoice_date=None))
        txn = bank_txn(date="2026-04-15")

        # Act / Assert
        assert date_ok(cons, txn) is True

    def test_both_dates_missing_is_false(self):
        # Arrange — neither date present.
        cons = consensus_record(dict(CLEAN_LABELS, invoice_date=None, due_date=None))
        txn = bank_txn(date="2026-04-10")

        # Act / Assert
        assert date_ok(cons, txn) is False

    def test_both_dates_present_in_window_still_passes(self):
        # Arrange — regression: both-dates behavior unchanged.
        cons = consensus_record()
        txn = bank_txn(date="2026-04-10")

        # Act / Assert
        assert date_ok(cons, txn) is True


class TestDiagnoseAmount:
    @pytest.mark.parametrize(
        ("currency", "reference", "expected_category"),
        [
            ("EUR", "INV-1001", "fx"),                 # foreign currency paid in DKK
            ("DKK", "INV-1001+INV-1002", "batch"),     # reference lists several invoices
            ("DKK", "INV-1001 -2%", "discount"),       # early-payment discount note
            ("DKK", "INV-1001", "unexplained"),        # no benign cause
        ],
    )
    def test_mismatch_classification(self, currency, reference, expected_category):
        # Arrange
        cons = consensus_record(dict(CLEAN_LABELS, currency=currency))
        txn = bank_txn(reference=reference, amount="7000")

        # Act
        category, _reason = diagnose_amount(cons, txn)

        # Assert
        assert category == expected_category


class TestExtractionIssues:
    def test_clean_record_has_no_issues(self):
        # Arrange
        cons = consensus_record()

        # Act
        issues = extraction_issues(cons)

        # Assert
        assert issues == []

    def test_missing_disagreed_ungrounded_are_flagged(self):
        # Arrange
        cons = consensus_record()
        cons["extraction"]["invoice_id"]["value"] = None            # missing
        cons["extraction"]["amount"]["agreement"] = False           # disagreement
        cons["extraction"]["supplier_name"]["quote_found"] = False  # ungrounded

        # Act
        issues = extraction_issues(cons)

        # Assert
        assert "invoice_id missing" in issues
        assert "amount disagreement" in issues
        assert "supplier_name ungrounded" in issues


class TestFindMatch:
    def test_reference_hit_wins_over_name_only(self):
        # Arrange
        cons = consensus_record()
        txns = [
            bank_txn(txn_id="NAME", reference="OTHER", counterparty="Acme Tools A/S"),
            bank_txn(txn_id="REF", reference="INV-1001", counterparty="Zzz"),
        ]

        # Act
        match = find_match(cons, txns)

        # Assert
        assert match["txn"]["txn_id"] == "REF"

    def test_no_candidate_returns_none(self):
        # Arrange
        cons = consensus_record()
        txns = [bank_txn(reference="X", counterparty="Globex")]

        # Act
        match = find_match(cons, txns)

        # Assert
        assert match is None


class TestTriage:
    def test_clean_invoice_auto_accepts(self):
        # Arrange
        cons = consensus_record()
        txns = [bank_txn()]

        # Act
        result = triage(cons, txns)

        # Assert
        assert result["status"] == "auto_accept"
        assert result["match_score"] >= 95 and result["approval_score"] == 100
        assert result["match_reasons"] and result["approval_reasons"]

    def test_fx_invoice_goes_to_review(self):
        # Arrange
        cons = consensus_record(dict(CLEAN_LABELS, currency="EUR"))
        txns = [bank_txn(amount="7450.00")]

        # Act
        result = triage(cons, txns)

        # Assert
        assert result["status"] == "review"
        assert any("FX" in reason for reason in result["approval_reasons"])

    def test_name_only_match_is_rejected(self):
        # Arrange — supplier matches but the invoice id isn't in any bank reference.
        cons = consensus_record()
        txns = [bank_txn(reference="UNRELATED", counterparty="Acme Tools A/S")]

        # Act
        result = triage(cons, txns)

        # Assert
        assert result["status"] == "reject"
        assert result["match_score"] < 50

    def test_missing_critical_field_is_data_integrity_reject(self):
        # Arrange
        cons = consensus_record(dict(CLEAN_LABELS, invoice_id=None))
        txns = [bank_txn()]

        # Act
        result = triage(cons, txns)

        # Assert
        assert result["status"] == "reject"
        assert any("data-integrity" in reason for reason in result["approval_reasons"])

    def test_no_bank_transaction_goes_to_review(self):
        # Arrange
        cons = consensus_record()
        txns = [bank_txn(reference="X", counterparty="Globex")]

        # Act
        result = triage(cons, txns)

        # Assert
        assert result["status"] == "review"
        assert result["txn_id"] is None

    def test_confident_ref_but_unexplained_amount_rejects(self):
        # Arrange — DKK, exact reference, but the bank paid a different amount.
        cons = consensus_record()
        txns = [bank_txn(reference="INV-1001", amount="9999.99")]

        # Act
        result = triage(cons, txns)

        # Assert
        assert result["status"] == "reject"
