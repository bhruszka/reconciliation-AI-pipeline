from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class EnrichedInvoice(BaseModel):
    """Task 1 output for one invoice: its raw text sources (no LLM)."""

    invoice_path: str
    pdf_text: str  # embedded text layer ("" if the PDF is image-only/scanned)
    ocr_text: str  # OCR over the rendered pages


class Currency(StrEnum):
    """The only currencies this distributor deals in (README)."""

    DKK = "DKK"
    EUR = "EUR"
    USD = "USD"


# The po_reference description. Two versions — exactly one must be live; swap by
# commenting one out and uncommenting the other. Mirrors the same choice in
# parsing/prompts.py (_PO_RULE), so keep the two in step.

# LIVE. Generic: a PO is the buyer's number. Names no label, so it transfers to
# distractors we have never seen.
_PO_DESC = (
    "The customer's (buyer's) purchase-order reference — the number the buyer "
    "issued to order these goods, not a number the supplier issued. Return null "
    "if no customer PO is present."
)

# DISABLED — overfits the golden set: it names invoice_08's and invoice_02's own
# distractor labels, so it buys eval points without making the extractor any better on
# an invoice we have not already labeled. See the fuller note in parsing/prompts.py.
# _PO_DESC = (
#     "The customer's (buyer's) purchase-order reference. Do NOT use the supplier's "
#     "own order/job number (e.g. Auftragsnummer), a delivery-note number (e.g. "
#     "Lieferschein), or a customer account number (e.g. Kundennummer) — these are "
#     "not purchase orders. Return null if no customer PO is present."
# )

# Per-field guidance, shared by both schemas. For the loose (model-facing) schema
# these carry the normalization hints the typed schema would otherwise encode.
DESCRIPTIONS = {
    "invoice_id": "The supplier's invoice number/identifier.",
    "supplier_name": "The supplier/vendor issuing the invoice (the seller, not the customer).",
    "amount": (
        "The grand total payable INCLUDING VAT — not the subtotal, not the VAT "
        "amount. A decimal number using a dot decimal separator, e.g. 1234.56."
    ),
    "currency": "The invoice currency: one of DKK, EUR, or USD.",
    "invoice_date": "The invoice issue date as an ISO date, YYYY-MM-DD.",
    "due_date": "The payment due date as an ISO date, YYYY-MM-DD.",
    "po_reference": _PO_DESC,
}


class FieldValue[T](BaseModel):
    """One extracted field: a value plus the exact text it was taken from."""

    value: T | None = Field(
        description=(
            "The value read ONLY from the provided input. Use nothing but what is "
            "explicitly present — no outside knowledge, no guessing, no inference. "
            "Null if the field is absent or you are unsure."
        )
    )
    source_quote: str = Field(
        description=(
            "The snippet copied VERBATIM (character-for-character) from the provided "
            "input that this value was read from. Empty string when value is null."
        )
    )


class RawExtraction(BaseModel):
    """Model-facing schema: every value is a plain string (loose JSON schema)."""

    invoice_id: FieldValue[str] = Field(description=DESCRIPTIONS["invoice_id"])
    supplier_name: FieldValue[str] = Field(description=DESCRIPTIONS["supplier_name"])
    amount: FieldValue[str] = Field(description=DESCRIPTIONS["amount"])
    currency: FieldValue[str] = Field(description=DESCRIPTIONS["currency"])
    invoice_date: FieldValue[str] = Field(description=DESCRIPTIONS["invoice_date"])
    due_date: FieldValue[str] = Field(description=DESCRIPTIONS["due_date"])
    po_reference: FieldValue[str] = Field(description=DESCRIPTIONS["po_reference"])


class InvoiceExtraction(BaseModel):
    """Strict, typed target — enforced locally by coercing a RawExtraction."""

    invoice_id: FieldValue[str] = Field(description=DESCRIPTIONS["invoice_id"])
    supplier_name: FieldValue[str] = Field(description=DESCRIPTIONS["supplier_name"])
    amount: FieldValue[Decimal] = Field(description=DESCRIPTIONS["amount"])
    currency: FieldValue[Currency] = Field(description=DESCRIPTIONS["currency"])
    invoice_date: FieldValue[date] = Field(description=DESCRIPTIONS["invoice_date"])
    due_date: FieldValue[date] = Field(description=DESCRIPTIONS["due_date"])
    po_reference: FieldValue[str] = Field(description=DESCRIPTIONS["po_reference"])


class Usage(BaseModel):
    """Token counts and the gateway's USD cost for one model call."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class AgentResult(BaseModel):
    """One agent's run over one invoice — the record written to extractions.jsonl.

    The caller only runs applicable views (routing lives in eval), so an agent is
    never asked to read a source it doesn't have.
    """

    invoice_path: str
    view: str
    model: str
    status: Literal["ok", "error"] = "ok"
    extraction: dict | None = None  # {field: {value, source_quote, quote_found}}
    error: str | None = None
    usage: Usage | None = None
