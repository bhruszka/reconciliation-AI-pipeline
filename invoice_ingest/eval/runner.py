from __future__ import annotations

from invoice_ingest.parsing.agents import AGENTS, DEFAULT_MODEL, SOURCE_BY_VIEW, VIEWS
from invoice_ingest.parsing.agents import run_agent as _parsing_run_agent
from invoice_ingest.parsing.schema import AgentResult, EnrichedInvoice


def applicable_views(record: EnrichedInvoice) -> list[str]:
    """Views that can run on this invoice — the routing decision.

    A view applies when its text source is present; `vision` (no text source)
    always applies. So the text agent is routed OUT of an image-only PDF
    (`pdf_text == ""`) rather than run and marked skipped.
    """
    views = []
    for view in VIEWS:
        source_key = SOURCE_BY_VIEW[view]
        if source_key is None or getattr(record, source_key).strip():
            views.append(view)
    return views


def run_agent(
    record: EnrichedInvoice, view: str, model: str | None = DEFAULT_MODEL
) -> AgentResult | None:
    """Routed run: None if the view doesn't apply to this invoice, else the result."""
    if view not in applicable_views(record):
        return None
    return _parsing_run_agent(record, view, model)


def run_all_views(record: EnrichedInvoice, model: str | None = DEFAULT_MODEL) -> list[AgentResult]:
    """Run every applicable view over one invoice."""
    return [_parsing_run_agent(record, v, model) for v in applicable_views(record)]


# Re-export so callers (harness, extract) get everything routing-related from here.
__all__ = ["applicable_views", "run_agent", "run_all_views", "AGENTS", "VIEWS", "DEFAULT_MODEL"]
