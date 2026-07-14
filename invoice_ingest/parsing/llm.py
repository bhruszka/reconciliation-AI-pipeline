from __future__ import annotations

from langchain_openai import ChatOpenAI

from invoice_ingest import config

# Default model — from the environment (LLM_MODEL); override per call / via --model.
DEFAULT_MODEL = config.LLM_MODEL


def build_llm(model: str | None = None, **kwargs) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or config.LLM_MODEL,
        base_url=config.LLM_URL,
        api_key=config.LLM_API_KEY,
        max_tokens=2048,
        timeout=60,
        # Ask the gateway to report the actual USD cost of each call in the response
        # `usage` object (surfaces in response_metadata["token_usage"]["cost"]).
        extra_body={"usage": {"include": True}},
        **kwargs,
    )
