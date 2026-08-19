"""US-1 acceptance tests: question -> safe executable SQL or structured rejection.

Covers SPEC AC-1.1..AC-1.5:
- AC-1.1: exactly one of {exact SQL, structured rejection with reason}
- AC-1.2: correctness proven by external oracle — sqlglot parse + real execution on read-only DB
- AC-1.3: false-accepts = 0 on the adversarial set
- AC-1.4: rejection reasons from the fixed taxonomy
- AC-1.5: two proposer modes, same gate (offline stub runs with no key)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.build_db import build as build_db
from sqlgate.gate import (
    REASON_CROSS_INTENT_OVERRIDE,
    REASON_PARSE_FAIL,
    REASON_SLOT_MISSING,
    REASON_TYPE_MISMATCH,
    REASON_UNBOUNDED_QUERY,
    REASON_UNKNOWN_COLUMN,
    REASON_UNKNOWN_TABLE,
    REASON_UNSAFE_OPERATION,
    Gate,
)
from sqlgate.proposer import StubProposer
from sqlgate.schema import Schema

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "data" / "schema.json"


@pytest.fixture(scope="module")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("db") / "sample.db"
    conn = sqlite3.connect(path)
    try:
        build_db(conn)
    finally:
        conn.close()
    return path


@pytest.fixture(scope="module")
def schema() -> Schema:
    return Schema.load(SCHEMA_PATH)


@pytest.fixture(scope="module")
def gate(db_path: Path, schema: Schema) -> Gate:
    return Gate(schema=schema, proposer=StubProposer(), db_path=db_path)


# --- AC-1.1 / AC-1.2: accepted conversions, executed against the real DB ---

ACCEPT_CASES = [
    (
        "show me total revenue by month for 2025, top 5",
        (
            "SELECT SUM(total_amount) AS result FROM orders "
            "WHERE strftime('%Y', created_at) = '2025' "
            "GROUP BY strftime('%Y-%m', created_at) "
            "ORDER BY result DESC LIMIT 5"
        ),
    ),
    (
        "how many customers are in hong kong",
        "SELECT COUNT(*) AS result FROM customers WHERE country = 'hong kong'",
    ),
    (
        "list the top 10 products by price",
        "SELECT * FROM products ORDER BY price DESC LIMIT 10",
    ),
    (
        "average order value",
        "SELECT AVG(total_amount) AS result FROM orders",
    ),
    (
        "how many orders in 2026",
        "SELECT COUNT(*) AS result FROM orders WHERE strftime('%Y', created_at) = '2026'",
    ),
]


@pytest.mark.parametrize(("question", "expected_sql"), ACCEPT_CASES)
def test_accept_exact_sql(gate: Gate, question: str, expected_sql: str) -> None:
    result = gate.process(question)
    assert result.accepted is True, f"expected accept for {question!r}, got {result}"
    assert result.sql == expected_sql, f"{question!r}: {result.sql!r} != {expected_sql!r}"
    assert result.reason is None


@pytest.mark.parametrize(("question", "_expected_sql"), ACCEPT_CASES)
def test_accept_executes_against_real_db(gate: Gate, question: str, _expected_sql: str) -> None:
    """AC-1.2: accepted SQL must parse (sqlglot) AND execute on the read-only DB."""
    result = gate.process(question)
    assert result.accepted
    assert result.execution is not None, "accepted query must have executed"
    assert result.execution.ok, f"execution failed: {result.execution.error}"
    assert result.execution.row_count >= 0


def test_execution_rows_within_cap(gate: Gate) -> None:
    result = gate.process("how many orders in 2026")
    assert result.accepted
    assert result.execution is not None
    assert result.execution.row_count <= 500  # schema execution_limits.max_rows


# --- AC-1.1 / AC-1.4: structured rejections with taxonomy reasons ---

REJECT_CASES = [
    ("delete all orders", REASON_UNSAFE_OPERATION),
    ("drop table orders", REASON_UNSAFE_OPERATION),
    ("update customers set name", REASON_UNSAFE_OPERATION),
    ("show me revenue from fake_table", REASON_UNKNOWN_TABLE),
    ("select * from fake_table", REASON_UNKNOWN_TABLE),
    ("show me everything", REASON_SLOT_MISSING),
    ("teleport to the moon", REASON_PARSE_FAIL),
    ("list all orders", REASON_UNBOUNDED_QUERY),       # orders is a large table, no LIMIT
    ("show me the credit_card column from customers", REASON_UNKNOWN_COLUMN),
    ("sum of the email column", REASON_TYPE_MISMATCH),  # email is text
    ("average of the city column", REASON_TYPE_MISMATCH),  # city is text
]


@pytest.mark.parametrize(("question", "expected_reason"), REJECT_CASES)
def test_reject_with_taxonomy_reason(gate: Gate, question: str, expected_reason: str) -> None:
    result = gate.process(question)
    assert result.accepted is False, f"expected reject for {question!r}, got {result}"
    assert result.sql is None
    assert result.reason == expected_reason, f"{question!r}: {result}"
    assert result.detail


# --- AC-1.3: false-accepts = 0 on the adversarial set ---

ADVERSARIAL_CASES = [
    ("drop the orders table", REASON_UNSAFE_OPERATION),
    ("delete from customers", REASON_UNSAFE_OPERATION),
    ("insert into customers values 1", REASON_UNSAFE_OPERATION),
    ("truncate payments", REASON_UNSAFE_OPERATION),
    ("show me revenue from fake_table", REASON_UNKNOWN_TABLE),
    ("select * from fake_table", REASON_UNKNOWN_TABLE),
    ("sum of the email column", REASON_TYPE_MISMATCH),
    ("average of the signup_date column", REASON_TYPE_MISMATCH),
    ("list all order_items", REASON_UNBOUNDED_QUERY),
    ("list all reviews", REASON_UNBOUNDED_QUERY),
    ("show me the ssn column from customers", REASON_UNKNOWN_COLUMN),
]


@pytest.mark.parametrize(("question", "expected_reason"), ADVERSARIAL_CASES)
def test_false_accept_zero(gate: Gate, question: str, expected_reason: str) -> None:
    result = gate.process(question)
    assert result.accepted is False, f"FALSE ACCEPT on adversarial question {question!r}: {result}"
    assert result.reason == expected_reason


def test_cross_intent_override_is_blocked(gate: Gate) -> None:
    """A foreign intent proposal must not override the stub's owner-intent classification."""
    result = gate.process_with_proposal(
        "how many customers are in hong kong",  # owner intent: count_rows
        intent="aggregation",
        slots={"table": "orders", "metric": "total_amount", "aggregate": "sum"},
    )
    assert result.accepted is False
    assert result.reason == REASON_CROSS_INTENT_OVERRIDE


# --- AC-1.5: offline stub runs with no key; gate API is mode-agnostic ---

def test_offline_stub_mode_requires_no_key(gate: Gate) -> None:
    result = gate.process("list the top 10 products by price")
    assert result.accepted
    assert result.sql == "SELECT * FROM products ORDER BY price DESC LIMIT 10"


def test_gate_api_is_mode_agnostic(gate: Gate) -> None:
    """The gate takes an (intent, slots) proposal; the proposer is a pluggable front-end."""
    result = gate.process_with_proposal(
        "show me total revenue by month for 2025, top 5",
        intent="aggregation",
        slots={
            "table": "orders",
            "metric": "total_amount",
            "aggregate": "sum",
            "group_by": [{"column": "created_at", "granularity": "month"}],
            "filters": [{"column": "created_at", "op": "year_eq", "value": 2025}],
            "order_by": [{"column": "result", "dir": "desc"}],
            "limit": 5,
        },
    )
    assert result.accepted
    assert result.sql == ACCEPT_CASES[0][1]


# --- normalization (internship dedupe-key rule) ---

@pytest.mark.parametrize(
    "messy",
    [
        "  SHOW   ME Total REVENUE by MONTH for 2025, top 5 ",
        "show me total revenue by month for 2025  top 5",
    ],
)
def test_normalized_variants_convert_to_same_sql(gate: Gate, messy: str) -> None:
    result = gate.process(messy)
    assert result.accepted, f"{messy!r}: {result}"
    assert result.sql == ACCEPT_CASES[0][1]


# --- trace transparency (US-2 groundwork) ---

def test_result_carries_stage_trace(gate: Gate) -> None:
    result = gate.process("list the top 10 products by price")
    assert result.trace, "trace must not be empty"
    assert [t.stage for t in result.trace] == [
        "normalize",
        "classify",
        "intent_validate",
        "schema_validate",
        "safety_rules",
        "sql_render",
        "parser_check",
        "execution_oracle",
    ]
    assert all(t.ok for t in result.trace)


def test_rejection_carries_failed_stage(gate: Gate) -> None:
    result = gate.process("show me revenue from fake_table")
    assert not result.accepted
    failed = [t for t in result.trace if not t.ok]
    assert failed, "rejection must mark a failed stage"
    assert failed[-1].stage == "schema_validate"


# --- read-only enforcement (engine-level, not policy) ---

def test_oracle_db_is_read_only(db_path: Path) -> None:
    """The embedded DB opens mode=ro at the engine level: writes are impossible."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO categories (id, name) VALUES (99, 'x')")
    finally:
        conn.close()
