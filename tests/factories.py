"""Shared factories for the non-LLM unit tests (imported as `tests.factories`).

Everything here constructs the plain dicts the pipeline passes around (agent
records, consensus records, bank transactions) so tests never touch an LLM.
"""
from __future__ import annotations

from invoice_ingest.shared.compare import FIELDS

# A clean, fully-reconciling invoice: DKK, exact amount, in-window dates.
CLEAN_LABELS = {
    "invoice_id": "INV-1001",
    "supplier_name": "Acme Tools A/S",
    "amount": "1000.00",
    "currency": "DKK",
    "invoice_date": "2026-04-01",
    "due_date": "2026-04-15",
    "po_reference": "PO-77",
}


def field(value, *, source_quote="src", quote_found=True, agreement=True) -> dict:
    """One field entry as it appears inside a record's `extraction`."""
    if value is None:
        source_quote, quote_found = "", None
    return {
        "value": value,
        "source_quote": source_quote,
        "quote_found": quote_found,
        "agreement": agreement,
    }


def agent_record(view: str, values: dict, *, invoice_path="golden/pdfs/inv.pdf",
                 status="ok", quote_found=True) -> dict:
    """An AgentResult-shaped dict for one view (as written to extractions.jsonl)."""
    extraction = None
    if status == "ok":
        extraction = {
            f: field(values.get(f), quote_found=quote_found) for f in FIELDS
        }
    return {
        "invoice_path": invoice_path,
        "view": view,
        "model": "test-model",
        "status": status,
        "extraction": extraction,
    }


def consensus_record(values: dict | None = None, *, invoice_path="golden/pdfs/inv.pdf",
                     agreement=True, quote_found=True) -> dict:
    """A consensus record with every field set to `values` (defaults to CLEAN_LABELS)."""
    values = CLEAN_LABELS if values is None else values
    return {
        "invoice_path": invoice_path,
        "view": "consensus",
        "partner": "text",
        "status": "ok",
        "extraction": {
            f: field(values.get(f), agreement=agreement, quote_found=quote_found)
            for f in FIELDS
        },
    }


def bank_txn(txn_id="TXN-1", reference="INV-1001", counterparty="Acme Tools A/S",
             amount="1000.00", date="2026-04-10") -> dict:
    """A bank transaction row as `matcher.load_bank` would produce it."""
    from datetime import date as _date
    from decimal import Decimal

    return {
        "txn_id": txn_id,
        "reference": reference,
        "counterparty": counterparty,
        "amount": amount,
        "amount_dkk": abs(Decimal(amount)),
        "date": date,
        "date_obj": _date.fromisoformat(date) if date else None,
    }
