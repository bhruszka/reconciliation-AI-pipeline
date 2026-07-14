"""The error-record contract: a bad PDF or a failed model call must produce an
error record (status="error", with a reason) instead of crashing the run — the
per-document error record the brief (Task 1) requires.

These exercise the branch in parsing.agents.run_agent without a real LLM call:
  - the vision view fails at content-build (fitz.open on a missing PDF), before
    any network call — a genuine "bad PDF" path;
  - the text view is driven to fail via a monkeypatched Agent.invoke, covering
    the "failed model call" path.
"""
from __future__ import annotations

from invoice_ingest.parsing import agents
from invoice_ingest.parsing.agents import run_agent
from invoice_ingest.parsing.schema import EnrichedInvoice


def _record(pdf_text: str = "PDF text", ocr_text: str = "OCR text") -> EnrichedInvoice:
    return EnrichedInvoice(invoice_path="does/not/exist.pdf", pdf_text=pdf_text, ocr_text=ocr_text)


def test_bad_pdf_yields_error_record_not_crash():
    # Arrange — the vision view renders the PDF; the path doesn't exist, so
    # fitz.open raises during content build, before any model call.
    record = _record()

    # Act — must not raise.
    result = run_agent(record, "vision", model="test-model")

    # Assert — a well-formed error record, not an exception.
    assert result.status == "error"
    assert result.extraction is None
    assert result.error  # non-empty reason string ("<ExcType>: <message>")
    assert result.invoice_path == "does/not/exist.pdf"
    assert result.view == "vision"


def test_failed_model_call_yields_error_record(monkeypatch):
    # Arrange — force the LLM call to blow up for the text view.
    def boom(self, record, model=None):
        raise RuntimeError("gateway 503")

    monkeypatch.setattr(agents.Agent, "invoke", boom)

    # Act
    result = run_agent(_record(), "text", model="test-model")

    # Assert — the reason names the failure so it's debuggable in the output.
    assert result.status == "error"
    assert result.extraction is None
    assert "gateway 503" in result.error
