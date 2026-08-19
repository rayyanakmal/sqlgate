"""The deterministic gate: intent_validate -> schema_validate -> safety_rules
-> sql_render -> parser_check -> execution_oracle.

The proposer (stub / LLM / fine-tuned) only proposes meaning. The gate decides.
The gate never changes when the proposer changes (SPEC AC-1.5).
"""

from __future__ import annotations

import re
from typing import Any

import sqlglot
from sqlglot import exp

from sqlgate.oracle import Oracle
from sqlgate.patterns import PatternLibrary
from sqlgate.proposer import Proposer, StubProposer
from sqlgate.result import (
    REASON_CROSS_INTENT_OVERRIDE,
    REASON_PARSE_FAIL,
    REASON_SLOT_MISSING,
    REASON_TYPE_MISMATCH,
    REASON_UNBOUNDED_QUERY,
    REASON_UNKNOWN_COLUMN,
    REASON_UNKNOWN_TABLE,
    REASON_UNSAFE_OPERATION,
    GateResult,
    StageTrace,
)
from sqlgate.schema import Schema

WHITESPACE = re.compile(r"\s+")


def normalize(question: str) -> str:
    """Lowercase + collapse whitespace. The dedupe key (internship eval rule)."""
    return WHITESPACE.sub(" ", question.strip().lower())


class Gate:
    def __init__(
        self,
        schema: Schema,
        proposer: Proposer | None = None,
        db_path: str = "data/sample.db",
        patterns_path: str = "data/patterns.json",
    ) -> None:
        self.schema = schema
        self.proposer: Proposer = proposer or StubProposer()
        self.patterns = PatternLibrary.load(patterns_path)
        self.oracle = Oracle(
            db_path=db_path,
            max_rows=schema.max_rows,
            timeout_seconds=schema.timeout_seconds,
        )

    # -- entry points -----------------------------------------------------

    def process(self, question: str) -> GateResult:
        """Full pipeline with the configured proposer (offline stub by default)."""
        trace: list[StageTrace] = []
        q = normalize(question)
        trace.append(StageTrace("normalize", True, q))

        proposal = self.proposer.propose(q, self.schema)
        if proposal.intent is None:
            trace.append(StageTrace("classify", False, "no intent recognized"))
            return GateResult.reject(REASON_PARSE_FAIL, "could not parse a known intent", trace)
        trace.append(
            StageTrace("classify", True, f"intent={proposal.intent}, slots={proposal.slots}")
        )
        return self._evaluate(proposal.intent, proposal.slots, q, trace)

    def process_with_proposal(
        self, question: str, intent: str, slots: dict[str, Any]
    ) -> GateResult:
        """Evaluate an externally supplied proposal (LLM / fine-tuned / tests).

        Cross-intent guard: if the supplied intent contradicts what the
        deterministic stub classifies as the owner intent, the proposal is
        blocked (internship invariant #4, made first-class).
        """
        trace: list[StageTrace] = []
        q = normalize(question)
        trace.append(StageTrace("normalize", True, q))

        owner = StubProposer().propose(q, self.schema)
        if owner.intent is not None and owner.intent != intent:
            trace.append(
                StageTrace(
                    "classify",
                    False,
                    f"proposed intent={intent} contradicts owner intent={owner.intent}",
                )
            )
            return GateResult.reject(REASON_CROSS_INTENT_OVERRIDE, trace[-1].detail, trace)
        trace.append(StageTrace("classify", True, f"intent={intent}, slots={slots}"))
        return self._evaluate(intent, slots, q, trace)

    # -- the gate ---------------------------------------------------------

    def _evaluate(
        self, intent: str, slots: dict[str, Any], q: str, trace: list[StageTrace]
    ) -> GateResult:
        # stage 1: intent_validate
        if intent == "unsafe_write":
            trace.append(
                StageTrace("intent_validate", False, "write operations are not allowed (SELECT-only)")
            )
            return GateResult.reject(REASON_UNSAFE_OPERATION, trace[-1].detail, trace)
        pattern = self.patterns.get(intent)
        if pattern is None:
            trace.append(StageTrace("intent_validate", False, f"unknown intent {intent}"))
            return GateResult.reject(REASON_PARSE_FAIL, trace[-1].detail, trace)
        missing = [name for name, spec in pattern.slot_spec.items() if spec.required and name not in slots]
        if missing:
            trace.append(StageTrace("intent_validate", False, f"missing required slots: {missing}"))
            return GateResult.reject(REASON_SLOT_MISSING, trace[-1].detail, trace)
        trace.append(StageTrace("intent_validate", True, f"pattern {intent} matched"))

        # stage 2: schema_validate
        schema_check = self._schema_validate(intent, slots)
        if not schema_check[0]:
            trace.append(StageTrace("schema_validate", False, schema_check[1]))
            return GateResult.reject(schema_check[2], schema_check[1], trace)
        trace.append(StageTrace("schema_validate", True, "tables/columns exist, types compatible"))

        # stage 3: safety_rules
        safety = self._safety_check(intent, slots)
        if not safety[0]:
            trace.append(StageTrace("safety_rules", False, safety[1]))
            return GateResult.reject(safety[2], safety[1], trace)
        trace.append(StageTrace("safety_rules", True, "SELECT-only, bounded query"))

        # stage 4: sql_render (deterministic from the pattern library)
        sql = self.patterns.render(intent, slots, self.schema)
        trace.append(StageTrace("sql_render", True, sql))

        # stage 5: parser_check (real SQL grammar via sqlglot)
        parse_ok, parse_detail = self._parser_check(sql)
        if not parse_ok:
            trace.append(StageTrace("parser_check", False, parse_detail))
            return GateResult.reject(REASON_PARSE_FAIL, parse_detail, trace)
        trace.append(StageTrace("parser_check", True, "sqlglot: valid single SELECT"))

        # stage 6: execution_oracle (real engine, read-only)
        execution = self.oracle.execute(sql)
        if not execution.ok:
            trace.append(StageTrace("execution_oracle", False, execution.error or "execution failed"))
            return GateResult.reject(REASON_PARSE_FAIL, execution.error or "execution failed", trace)
        trace.append(
            StageTrace("execution_oracle", True, f"executed, {execution.row_count} rows")
        )
        return GateResult.accept(sql, intent, slots, execution, trace)

    # -- stage implementations --------------------------------------------

    def _schema_validate(
        self, intent: str, slots: dict[str, Any]
    ) -> tuple[bool, str, str]:
        table = slots.get("table")
        if table is None or self.schema.table(str(table)) is None:
            return False, f"table '{table}' does not exist in the schema", REASON_UNKNOWN_TABLE

        for key in ("metric",):
            col = slots.get(key)
            if col is not None and self.schema.column(str(table), str(col)) is None:
                return False, f"column '{col}' does not exist in table '{table}'", REASON_UNKNOWN_COLUMN

        # aggregation metric must be numeric
        if intent == "aggregation":
            metric = slots.get("metric")
            if metric is not None and not self.schema.is_numeric(str(table), str(metric)):
                return False, f"column '{metric}' is not numeric; cannot aggregate", REASON_TYPE_MISMATCH

        for key in ("filters", "group_by", "order_by"):
            entries = slots.get(key) or []
            for entry in entries:
                col = entry.get("column")
                if col == "result":  # aggregate alias, valid only in order_by
                    continue
                if col is not None and self.schema.column(str(table), str(col)) is None:
                    return False, f"column '{col}' does not exist in table '{table}'", REASON_UNKNOWN_COLUMN

        cols = slots.get("columns")
        if cols:
            for col in cols:
                if col == "*":
                    continue
                if self.schema.column(str(table), str(col)) is None:
                    return False, f"column '{col}' does not exist in table '{table}'", REASON_UNKNOWN_COLUMN

        return True, "", ""

    def _safety_check(
        self, intent: str, slots: dict[str, Any]
    ) -> tuple[bool, str, str]:
        if intent == "unsafe_write":
            return False, "write operations are not allowed (SELECT-only)", REASON_UNSAFE_OPERATION

        # unbounded scans on large tables need a LIMIT (SPEC US-1 edge case).
        # Only the raw-scan `select` intent is unbounded: aggregations collapse
        # to summaries and count_rows returns a single number.
        table = str(slots.get("table", ""))
        if intent == "select" and table in self.schema.large_tables and slots.get("limit") is None:
            return False, f"'{table}' is a large table; a LIMIT is required", REASON_UNBOUNDED_QUERY
        return True, "", ""

    def _parser_check(self, sql: str) -> tuple[bool, str]:
        try:
            statements = sqlglot.parse(sql, read="sqlite")
        except Exception as e:  # noqa: BLE001 - any parse failure is a rejection
            return False, f"sqlglot parse failed: {e}"
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            return False, "must be a single SELECT statement"
        return True, ""
