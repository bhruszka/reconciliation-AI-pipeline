from __future__ import annotations

import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from rapidfuzz import fuzz

# supplier_name: token_set_ratio (0-100) above which two names are the "same
# entity". Token-set matching is subset/word-order robust, so "Acme Tools" and
# "Acme Tools Inc." score 100; paired with diacritic folding it also catches
# "München"/"Munchen". 85 still rejects genuinely different suppliers.
SUPPLIER_THRESHOLD = 85


def _norm_id(s: str) -> str:
    """Normalize an identifier: strip, uppercase, drop internal whitespace."""
    return "".join(str(s).split()).upper()


def _norm_text(s: str) -> str:
    """Normalize free text: fold diacritics, collapse whitespace, lowercase.

    Folding maps 'München' -> 'munchen' so the accent isn't a spurious mismatch.
    """
    folded = unicodedata.normalize("NFKD", str(s))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return " ".join(folded.split()).lower()


def cmp_identifier(gold: str, extracted: str) -> bool:
    """Normalized exact match — invoice_id, po_reference, currency."""
    return _norm_id(gold) == _norm_id(extracted)


def cmp_amount(gold: str, extracted: str) -> bool:
    """Exact numeric equality — formatting/trailing zeros ignored, no tolerance."""
    try:
        return Decimal(str(gold)) == Decimal(str(extracted))
    except InvalidOperation:
        return False


def cmp_date(gold: str, extracted: str) -> bool:
    """Parse both to dates and compare (both are ISO once normalized)."""
    try:
        return date.fromisoformat(str(gold)) == date.fromisoformat(str(extracted))
    except ValueError:
        return False


def cmp_supplier(gold: str, extracted: str) -> bool:
    """Fuzzy entity match: same supplier if token_set_ratio clears the threshold."""
    return fuzz.token_set_ratio(_norm_text(gold), _norm_text(extracted)) >= SUPPLIER_THRESHOLD


# Which comparator each field uses, and how we compare it.
FIELD_COMPARATORS = {
    "invoice_id": cmp_identifier,     # normalized exact (strip, uppercase, no spaces)
    "supplier_name": cmp_supplier,    # fuzzy entity match (token_set_ratio + diacritic fold)
    "amount": cmp_amount,             # exact numeric equality
    "currency": cmp_identifier,       # normalized exact (enum code)
    "invoice_date": cmp_date,         # parsed-date equality (format-agnostic)
    "due_date": cmp_date,             # parsed-date equality (format-agnostic)
    "po_reference": cmp_identifier,   # normalized exact
}

FIELDS = tuple(FIELD_COMPARATORS)


def values_match(field: str, gold_value: str, extracted_value: str) -> bool:
    """True if the extractor's value equals the gold value for this field.

    This answers ONLY "are these two present values the same?" using the field's
    comparator. Both values must be present — deciding what an absent value means
    (miss vs. correct abstention) is grading, and lives in eval.classify.
    """
    return FIELD_COMPARATORS[field](gold_value, extracted_value)


def quote_in_source(quote: str, source: str) -> bool:
    """True if `quote` appears (verbatim, up to normalization) in `source`.

    Grounding check: reuses the same normalization as the fuzzy comparator
    (diacritic-fold + whitespace-collapse + lowercase) so OCR line breaks and accent
    differences don't cause a false negative, then does a substring test.
    """
    return _norm_text(quote) in _norm_text(source)
