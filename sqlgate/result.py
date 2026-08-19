"""Result types and the fixed rejection taxonomy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- rejection taxonomy (SPEC AC-1.4, fixed) ---
REASON_UNKNOWN_TABLE = "UNKNOWN_TABLE"
REASON_UNKNOWN_COLUMN = "UNKNOWN_COLUMN"
REASON_TYPE_MISMATCH = "TYPE_MISMATCH"
REASON_UNSAFE_OPERATION = "UNSAFE_OPERATION"
REASON_UNBOUNDED_QUERY = "UNBOUNDED_QUERY"
REASON_SLOT_MISSING = "SLOT_MISSING"
REASON_CROSS_INTENT_OVERRIDE = "CROSS_INTENT_OVERRIDE"
REASON_PARSE_FAIL = "PARSE_FAIL"

VALID_REASONS = {
    REASON_UNKNOWN_TABLE,
    REASON_UNKNOWN_COLUMN,
    REASON_TYPE_MISMATCH,
    REASON_UNSAFE_OPERATION,
    REASON_UNBOUNDED_QUERY,
    REASON_SLOT_MISSING,
    REASON_CROSS_INTENT_OVERRIDE,
    REASON_PARSE_FAIL,
}

# The demo's gate stage order (US-2 trace; also mirrors the internship gate)
STAGE_NAMES = [
    "normalize",
    "classify",
    "intent_validate",
    "schema_validate",
    "safety_rules",
    "sql_render",
    "parser_check",
    "execution_oracle",
]


@dataclass
class StageTrace:
    """One gate stage's outcome, recorded for the transparency view."""

    stage: str
    ok: bool
    detail: str = ""


@dataclass
class ExecutionResult:
    """Outcome of running an accepted query against the read-only DB."""

    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    error: str | None = None


@dataclass
class GateResult:
    """Exactly one of {sql, rejection} — never both, never silent (AC-1.1)."""

    accepted: bool
    sql: str | None = None
    reason: str | None = None
    detail: str = ""
    intent: str | None = None
    proposal: dict[str, Any] | None = None
    execution: ExecutionResult | None = None
    trace: list[StageTrace] = field(default_factory=list)

    @classmethod
    def reject(cls, reason: str, detail: str, trace: list[StageTrace]) -> GateResult:
        assert reason in VALID_REASONS, f"invalid rejection reason: {reason}"
        return cls(accepted=False, reason=reason, detail=detail, trace=trace)

    @classmethod
    def accept(
        cls,
        sql: str,
        intent: str,
        proposal: dict[str, Any],
        execution: ExecutionResult,
        trace: list[StageTrace],
    ) -> GateResult:
        return cls(
            accepted=True,
            sql=sql,
            intent=intent,
            proposal=proposal,
            execution=execution,
            trace=trace,
        )

    def failed_stage(self) -> StageTrace | None:
        for t in self.trace:
            if not t.ok:
                return t
        return None
