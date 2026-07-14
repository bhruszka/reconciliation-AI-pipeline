from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class Outcome(StrEnum):
    """How one extracted field scored against its gold label."""

    CORRECT = "correct"
    MISS = "miss"  # extractor admitted unknown where a real value exists
    HALLUCINATION = "hallucination"  # extractor gave a confident value that's wrong


class Grounding(BaseModel):
    """Per-view grounding: how many present values had a verified source_quote."""

    grounded: int = 0
    checkable: int = 0
    rate: float = 0.0


class FieldAccuracy(BaseModel):
    correct: int = 0
    hallucination: int = 0
    miss: int = 0
    total: int = 0
    accuracy: float = 0.0


class ViewAccuracy(BaseModel):
    cost_usd: float | None = None  # call cost; for consensus, the OCR + partner runs behind it
    fields: dict[str, FieldAccuracy] = {}
    overall: FieldAccuracy = FieldAccuracy()


class Failure(BaseModel):
    invoice: str
    view: str
    field: str
    outcome: str
    gold: str | None = None
    extracted: str | None = None


class ReportMeta(BaseModel):
    timestamp: str
    model: str
    golden_count: int
    views: list[str]
    total_cost_usd: float


class EvalReport(BaseModel):
    meta: ReportMeta
    accuracy: dict[str, ViewAccuracy]
    grounding: dict[str, Grounding]
    failures: list[Failure]
