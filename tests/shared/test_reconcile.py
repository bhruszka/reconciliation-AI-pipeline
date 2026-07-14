"""Consensus building: strict agreement between OCR and its partner view."""
from __future__ import annotations

from invoice_ingest.shared.reconcile import build_consensus, reconcile_invoice
from tests.factories import CLEAN_LABELS, agent_record


def test_agreeing_views_yield_the_value():
    # Arrange
    records = [agent_record("ocr", CLEAN_LABELS), agent_record("text", CLEAN_LABELS)]

    # Act
    ext = build_consensus(records)[0]["extraction"]

    # Assert
    assert ext["amount"]["value"] == "1000.00"
    assert ext["amount"]["agreement"] is True


def test_disagreeing_views_abstain():
    # Arrange
    ocr = agent_record("ocr", dict(CLEAN_LABELS, amount="1000.00"))
    text = agent_record("text", dict(CLEAN_LABELS, amount="2000.00"))

    # Act
    ext = build_consensus([ocr, text])[0]["extraction"]

    # Assert
    assert ext["amount"]["value"] is None
    assert ext["amount"]["agreement"] is False


def test_both_absent_is_agreement_on_absence():
    # Arrange
    values = dict(CLEAN_LABELS, po_reference=None)
    records = [agent_record("ocr", values), agent_record("text", values)]

    # Act
    ext = build_consensus(records)[0]["extraction"]

    # Assert
    assert ext["po_reference"]["value"] is None
    assert ext["po_reference"]["agreement"] is True


def test_only_one_view_has_value_is_disagreement():
    # Arrange
    ocr = agent_record("ocr", dict(CLEAN_LABELS, po_reference="PO-9"))
    text = agent_record("text", dict(CLEAN_LABELS, po_reference=None))

    # Act
    ext = build_consensus([ocr, text])[0]["extraction"]

    # Assert
    assert ext["po_reference"]["value"] is None
    assert ext["po_reference"]["agreement"] is False


def test_partner_falls_back_to_vision_when_text_absent():
    # Arrange — image-only invoice: no text view, so vision partners OCR.
    records = [
        agent_record("ocr", CLEAN_LABELS),
        agent_record("vision", CLEAN_LABELS, quote_found=None),
    ]

    # Act
    cons = build_consensus(records)[0]

    # Assert
    assert cons["partner"] == "vision"
    assert cons["extraction"]["amount"]["value"] == "1000.00"


def test_errored_view_is_not_usable():
    # Arrange — text errored → treated as absent; OCR alone can't reach consensus.
    records = [
        agent_record("ocr", CLEAN_LABELS),
        agent_record("text", CLEAN_LABELS, status="error"),
    ]

    # Act
    cons = build_consensus(records)[0]

    # Assert
    assert cons["partner"] == "vision"  # text not ok → partner is vision (also absent)
    assert cons["extraction"]["amount"]["value"] is None


def test_consensus_carries_ocr_grounding_for_emitted_value():
    # Arrange
    views = {
        "ocr": agent_record("ocr", CLEAN_LABELS, quote_found=True),
        "text": agent_record("text", CLEAN_LABELS, quote_found=True),
    }

    # Act
    ext = reconcile_invoice(views)["extraction"]

    # Assert
    assert ext["invoice_id"]["quote_found"] is True
