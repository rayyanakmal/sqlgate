"""Proposers: turn a question into an IntentProposal (intent + slots).

The proposer only proposes meaning. The gate decides. StubProposer is the
deterministic offline mode (no key, demo always runs); LLMProposer plugs the
same contract via DeepSeek (added in a later story); FineTunedProposer (US-6)
will also implement this protocol.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlgate.schema import Schema

WRITE_VERBS = re.compile(r"\b(delete|drop|update|insert|truncate|alter)\b")

TABLE_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\border[_ ]items\b"), "order_items"),
    (re.compile(r"\border"), "orders"),
    (re.compile(r"\bcustomer"), "customers"),
    (re.compile(r"\bproduct"), "products"),
    (re.compile(r"\breview"), "reviews"),
    (re.compile(r"\bpayment"), "payments"),
    (re.compile(r"\bcategor"), "categories"),
    (re.compile(r"\binventor"), "inventory"),
]

METRIC_KEYWORDS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\brevenue|\bsales|\bamount|\bvalue"), "total_amount", "orders"),
    (re.compile(r"\bprice"), "price", "products"),
    (re.compile(r"\brating"), "rating", "reviews"),
    (re.compile(r"\bquantity|\bstock"), "quantity", "inventory"),
]

AGGREGATE_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsum|\btotal"), "sum"),
    (re.compile(r"\baverage|\bavg"), "avg"),
    (re.compile(r"\bcount"), "count"),
    (re.compile(r"\bminimum|\bmin"), "min"),
    (re.compile(r"\bmaximum|\bmax"), "max"),
]

GROUP_BY_KEYWORDS: list[tuple[re.Pattern[str], str, str | None]] = [
    (re.compile(r"\bby month\b"), "created_at", "month"),
    (re.compile(r"\bby year\b"), "created_at", "year"),
    (re.compile(r"\bby status\b"), "status", None),
    (re.compile(r"\bby country\b"), "country", None),
    (re.compile(r"\bby city\b"), "city", None),
    (re.compile(r"\bby categor\b"), "category_id", None),
    (re.compile(r"\bby warehouse\b"), "warehouse", None),
]


@dataclass
class IntentProposal:
    intent: str | None
    slots: dict[str, Any] = field(default_factory=dict)


class Proposer(Protocol):
    def propose(self, question: str, schema: Schema) -> IntentProposal: ...


class StubProposer:
    """Deterministic keyword-based proposer. Same gate contract as the LLM."""

    def propose(self, question: str, schema: Schema) -> IntentProposal:
        q = question.lower()

        if WRITE_VERBS.search(q):
            return IntentProposal(intent="unsafe_write")

        # table extraction (explicit 'from X' wins; else keyword match)
        table = None
        m = re.search(r"\bfrom\s+([a-z_]+)", q)
        if m:
            table = m.group(1)
        else:
            for pattern, name in TABLE_KEYWORDS:
                if pattern.search(q):
                    table = name
                    break

        # intent classification
        if re.search(r"\bhow many\b", q) or re.search(r"\bcount\b", q):
            return IntentProposal(
                intent="count_rows",
                slots=self._count_slots(q, table, schema),
            )
        if re.search(r"\bhow much\b", q) or re.search(r"\btotal\b", q):
            return IntentProposal(
                intent="aggregation",
                slots=self._aggregation_slots(q, table, schema, "sum"),
            )
        for pattern, agg in AGGREGATE_KEYWORDS:
            if pattern.search(q):
                return IntentProposal(
                    intent="aggregation",
                    slots=self._aggregation_slots(q, table, schema, agg),
                )
        if re.search(r"\b(list|show|display|top|find|select)\b", q):
            return IntentProposal(
                intent="select",
                slots=self._select_slots(q, table, schema),
            )
        return IntentProposal(intent=None, slots={})

    # -- slot extractors ---------------------------------------------------

    def _year_filter(self, q: str, schema: Schema) -> list[dict[str, Any]] | None:
        m = re.search(r"\b(?:for|in)\s+(20\d\d)\b", q)
        if not m:
            return None
        return [{"column": "created_at", "op": "year_eq", "value": int(m.group(1))}]

    def _country_filter(self, q: str) -> list[dict[str, Any]] | None:
        m = re.search(r"\bin\s+([a-z ]+?)\s*$", q)
        if not m:
            return None
        value = m.group(1).strip()
        if value.isdigit():
            return None
        return [{"column": "country", "op": "=", "value": value}]

    def _limit(self, q: str) -> int | None:
        m = re.search(r"\btop\s+(\d+)\b", q)
        return int(m.group(1)) if m else None

    def _count_slots(
        self, q: str, table: str | None, schema: Schema
    ) -> dict[str, Any]:
        slots: dict[str, Any] = {}
        if table:
            slots["table"] = table
        filters = self._year_filter(q, schema) or self._country_filter(q)
        if filters:
            slots["filters"] = filters
        return slots

    def _aggregation_slots(
        self, q: str, table: str | None, schema: Schema, agg: str
    ) -> dict[str, Any]:
        slots: dict[str, Any] = {}
        # metric: 'of the <col> column' beats keyword metrics
        metric = None
        m = re.search(r"\bof the\s+([a-z_]+)\s+column\b", q)
        if m:
            metric = m.group(1)
        else:
            for pattern, col, default_table in METRIC_KEYWORDS:
                if pattern.search(q):
                    metric, table = col, table or default_table
                    break
        if metric:
            slots["metric"] = metric
        if not table:
            # resolve table from the metric column's unique owner
            table = schema.find_table_for_column(metric) if metric else None
        if table:
            slots["table"] = table
        slots["aggregate"] = agg

        for pattern, col, gran in GROUP_BY_KEYWORDS:
            if pattern.search(q):
                group = {"column": col}
                if gran:
                    group["granularity"] = gran
                slots["group_by"] = [group]
                break

        filters = self._year_filter(q, schema)
        if filters:
            slots["filters"] = filters

        limit = self._limit(q)
        if limit:
            slots["limit"] = limit
            slots["order_by"] = [{"column": "result", "dir": "desc"}]
        return slots

    def _select_slots(
        self, q: str, table: str | None, schema: Schema
    ) -> dict[str, Any]:
        slots: dict[str, Any] = {}
        if table:
            slots["table"] = table
        m = re.search(r"\bthe\s+([a-z_]+)\s+column\b", q)
        if m:
            slots["columns"] = [m.group(1)]
        order_by = None
        m = re.search(r"\btop\s+(\d+)\s+[a-z ]*?\bby\s+([a-z_]+)\b", q)
        if m:
            slots["limit"] = int(m.group(1))
            order_by = [{"column": m.group(2), "dir": "desc"}]
        else:
            limit = self._limit(q)
            if limit:
                slots["limit"] = limit
                order_by = [{"column": "result", "dir": "desc"}]
        if order_by:
            slots["order_by"] = order_by
        filters = self._year_filter(q, schema)
        if filters:
            slots["filters"] = filters
        return slots
