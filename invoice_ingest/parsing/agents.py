from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from invoice_ingest.parsing.llm import DEFAULT_MODEL, build_llm
from invoice_ingest.parsing.pdf_parsing import render_page_pngs
from invoice_ingest.parsing.prompts import OCR_PROMPT, TEXT_PROMPT, VISION_PROMPT
from invoice_ingest.parsing.schema import (
    AgentResult,
    EnrichedInvoice,
    InvoiceExtraction,
    RawExtraction,
    Usage,
)
from invoice_ingest.shared.compare import quote_in_source

# The enriched-record key each view reads from — the single source of truth for
# view→source. `None` = no text source to ground against (the vision view).
SOURCE_BY_VIEW = {"text": "pdf_text", "ocr": "ocr_text", "vision": None}

# The message content a model sees: a plain string (text views) or a list of
# content blocks (the vision view).
Content = str | list[str | dict]
ContentBuilder = Callable[[EnrichedInvoice], Content]


@dataclass(frozen=True)
class Agent:
    """An agent is its name, its own system prompt, and how it builds message content.

    Invokable: `agent.invoke(record)` pulls this agent's input (OCR text, PDF text,
    or page images) out of the record and returns the structured extraction.
    """

    view: str
    system_prompt: str
    build_content: ContentBuilder

    def invoke(
        self, record: EnrichedInvoice, model: str | None = DEFAULT_MODEL
    ) -> tuple[InvoiceExtraction, Usage]:
        """Run this agent over one enriched record; return (extraction, usage).

        The model is given the LOOSE `RawExtraction` schema (all-string values), so
        its JSON schema passes providers' structured-output validators. We then
        coerce the result into the strict typed `InvoiceExtraction` locally —
        enforcing Decimal/date/enum here, where we control the parser.
        """
        content = self.build_content(record)
        # include_raw=True keeps the underlying AIMessage so we can read token usage
        # and the gateway's per-call USD cost alongside the parsed result.
        structured = build_llm(model).with_structured_output(
            RawExtraction, method="json_schema", include_raw=True
        )
        out = structured.invoke(
            [SystemMessage(self.system_prompt), HumanMessage(content=content)]
        )
        if out["parsed"] is None:
            raise ValueError(f"structured output parse failed: {out['parsing_error']}")
        extraction = InvoiceExtraction.model_validate(out["parsed"].model_dump())
        return extraction, usage_of(out["raw"])


def _text_content(record: EnrichedInvoice, key: str, label: str) -> Content:
    """Content-builder for a text view. Raises if the source is absent — a routing
    bug, since eval only runs applicable views (see eval.runner.applicable_views)."""
    source = getattr(record, key)
    if not source.strip():
        raise ValueError(f"no {label} — this view should have been routed out")
    return f"{label} of the invoice:\n\n{source}"


def _image_content(record: EnrichedInvoice) -> Content:
    """Content-builder for the vision view: rendered page image(s) as blocks."""
    blocks: list[str | dict] = [
        {"type": "text", "text": "Extract the fields from this invoice image."}
    ]
    for png in render_page_pngs(Path(record.invoice_path)):
        b64 = base64.b64encode(png).decode("ascii")
        blocks.append(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        )
    return blocks


AGENTS: dict[str, Agent] = {
    "ocr": Agent("ocr", OCR_PROMPT, lambda r: _text_content(r, "ocr_text", "OCR text")),
    "text": Agent("text", TEXT_PROMPT, lambda r: _text_content(r, "pdf_text", "PDF text layer")),
    "vision": Agent("vision", VISION_PROMPT, _image_content),
}
VIEWS = tuple(AGENTS)


def usage_of(raw_message) -> Usage:
    """Extract token usage and the gateway's USD cost from a raw AIMessage."""
    tokens = getattr(raw_message, "usage_metadata", None) or {}
    meta = getattr(raw_message, "response_metadata", None) or {}
    token_usage = meta.get("token_usage") or {}
    return Usage(
        input_tokens=tokens.get("input_tokens"),
        output_tokens=tokens.get("output_tokens"),
        cost_usd=token_usage.get("cost"),  # present when usage accounting is on
    )


def _add_grounding(extraction: dict, source: str | None) -> None:
    """Augment each field in place with `quote_found`, a grounding signal.

    `True`/`False` = the field's source_quote does / does not appear in the agent's
    source text. `None` = not checkable: the field has no value, or the view has no
    text source (vision — its quote is kept as evidence only).
    """
    for field in extraction.values():
        if field["value"] is None or not field["source_quote"] or source is None:
            field["quote_found"] = None
        else:
            field["quote_found"] = quote_in_source(field["source_quote"], source)


def run_agent(record: EnrichedInvoice, view: str, model: str | None = DEFAULT_MODEL) -> AgentResult:
    """Run one agent over one enriched record; return a typed AgentResult.

      - status "ok"    → `extraction` = {field: {value, source_quote, quote_found}}, usage set.
      - status "error" → a bad PDF or a failed model call. Emitted as a record (never
                  crashes the run) — the per-document error record the exercise asks for.
    """
    result = AgentResult(invoice_path=record.invoice_path, view=view, model=model)
    try:
        ext_obj, usage = AGENTS[view].invoke(record, model)
        # mode="json" → Decimal/date/enum become JSON-native strings for the JSONL.
        extraction = ext_obj.model_dump(mode="json")
        source_key = SOURCE_BY_VIEW[view]
        _add_grounding(extraction, getattr(record, source_key) if source_key else None)
        result.extraction = extraction
        result.usage = usage
    except Exception as exc:  # noqa: BLE001 - deliberate: emit an error record, never crash the run
        result.status = "error"
        result.error = f"{type(exc).__name__}: {exc}"
    return result
