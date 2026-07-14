"""View routing: which agents apply to an invoice (eval.runner.applicable_views)."""
from __future__ import annotations

from invoice_ingest.eval.runner import applicable_views
from invoice_ingest.parsing.schema import EnrichedInvoice


def test_digital_pdf_runs_all_views():
    # Arrange
    record = EnrichedInvoice(invoice_path="x.pdf", pdf_text="hello", ocr_text="hello")

    # Act
    views = applicable_views(record)

    # Assert
    assert views == ["ocr", "text", "vision"]


def test_image_only_pdf_routes_out_text():
    # Arrange — no text layer, so the text agent should be routed out (not errored).
    record = EnrichedInvoice(invoice_path="scan.pdf", pdf_text="", ocr_text="scanned")

    # Act
    views = applicable_views(record)

    # Assert
    assert "text" not in views
    assert set(views) == {"ocr", "vision"}


def test_whitespace_only_text_is_treated_as_absent():
    # Arrange
    record = EnrichedInvoice(invoice_path="x.pdf", pdf_text="   \n ", ocr_text="ocr")

    # Act
    views = applicable_views(record)

    # Assert
    assert "text" not in views
