"""Field comparators and grounding substring check."""
from __future__ import annotations

import pytest

from invoice_ingest.shared.compare import (
    _norm_id,
    _norm_text,
    cmp_amount,
    cmp_date,
    cmp_identifier,
    cmp_supplier,
    quote_in_source,
    values_match,
)


class TestNormalization:
    def test_norm_id_strips_case_and_whitespace(self):
        # Arrange
        raw = "  inv 123 "

        # Act
        result = _norm_id(raw)

        # Assert
        assert result == "INV123"

    def test_norm_text_folds_diacritics_and_lowercases(self):
        # Arrange
        raw = "München"

        # Act
        result = _norm_text(raw)

        # Assert
        assert result == "munchen"

    def test_norm_text_collapses_whitespace(self):
        # Arrange
        raw = "a\n  b\tc"

        # Act
        result = _norm_text(raw)

        # Assert
        assert result == "a b c"


class TestAmount:
    @pytest.mark.parametrize(
        ("gold", "extracted", "expected"),
        [
            ("1000.00", "1000", True),      # trailing zeros ignored
            ("1000.50", "1000.5", True),    # formatting ignored
            ("1000.00", "1000.01", False),  # one cent off is not a match
            ("abc", "1000", False),         # non-numeric never matches
        ],
    )
    def test_exact_numeric_equality(self, gold, extracted, expected):
        # Arrange — inputs from parametrize

        # Act
        result = cmp_amount(gold, extracted)

        # Assert
        assert result is expected


class TestDate:
    @pytest.mark.parametrize(
        ("gold", "extracted", "expected"),
        [
            ("2026-04-01", "2026-04-01", True),
            ("2026-04-01", "2026-04-02", False),
            ("not-a-date", "2026-04-01", False),
        ],
    )
    def test_parsed_date_equality(self, gold, extracted, expected):
        # Arrange — inputs from parametrize

        # Act
        result = cmp_date(gold, extracted)

        # Assert
        assert result is expected


class TestIdentifier:
    @pytest.mark.parametrize(
        ("gold", "extracted", "expected"),
        [
            ("inv-100", "INV-100", True),   # case-insensitive
            ("PO 44", "po44", True),        # space-insensitive
            ("INV-100", "INV-101", False),
        ],
    )
    def test_normalized_exact_match(self, gold, extracted, expected):
        # Arrange — inputs from parametrize

        # Act
        result = cmp_identifier(gold, extracted)

        # Assert
        assert result is expected


class TestSupplier:
    @pytest.mark.parametrize(
        ("gold", "extracted", "expected"),
        [
            ("Acme Tools", "Acme Tools Inc.", True),        # subset / word-order robust
            ("München Hardware", "Munchen Hardware", True),  # diacritic fold
            ("Acme Tools", "Globex Corporation", False),
        ],
    )
    def test_fuzzy_entity_match(self, gold, extracted, expected):
        # Arrange — inputs from parametrize

        # Act
        result = cmp_supplier(gold, extracted)

        # Assert
        assert result is expected


class TestValuesMatch:
    @pytest.mark.parametrize(
        ("field", "gold", "extracted", "expected"),
        [
            ("amount", "10.00", "10", True),
            ("amount", "10.00", "10.01", False),
            ("supplier_name", "Acme A/S", "Acme A/S Ltd", True),
        ],
    )
    def test_dispatches_to_field_comparator(self, field, gold, extracted, expected):
        # Arrange — inputs from parametrize

        # Act
        result = values_match(field, gold, extracted)

        # Assert
        assert result is expected

    def test_unknown_field_raises(self):
        # Arrange
        unknown_field = "nope"

        # Act / Assert
        with pytest.raises(KeyError):
            values_match(unknown_field, "a", "a")


class TestGrounding:
    def test_verbatim_substring_is_grounded(self):
        # Arrange
        quote, source = "Total 1000", "Invoice\nTotal 1000 DKK"

        # Act
        result = quote_in_source(quote, source)

        # Assert
        assert result is True

    def test_normalization_survives_linebreaks_and_accents(self):
        # Arrange
        quote, source = "Munchen", "Rechnung\nMünchen  GmbH"

        # Act
        result = quote_in_source(quote, source)

        # Assert
        assert result is True

    def test_absent_quote_is_not_grounded(self):
        # Arrange
        quote, source = "Total 9999", "Invoice Total 1000 DKK"

        # Act
        result = quote_in_source(quote, source)

        # Assert
        assert result is False
