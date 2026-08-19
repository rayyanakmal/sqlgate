"""US-3 / US-4 / US-5 tests: regression runner, rejection clustering, pattern
approval, and the reject-vs-repair loop (with a deterministic fake LLM)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from scripts.build_db import build as build_db
from sqlgate.gate import Gate
from sqlgate.learning import (
    approve_pattern,
    cluster_rejections,
    draft_pattern,
    repair,
)
from sqlgate.proposer import IntentProposal, Proposer
from sqlgate.regression import run_regression
from sqlgate.result import REASON_UNSAFE_OPERATION
from sqlgate.schema import Schema

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "data" / "schema.json"
EVAL_DIR = ROOT / "eval_sets"
PATTERNS_PATH = ROOT / "data" / "patterns.json"


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
def gate(db_path: Path) -> Gate:
    return Gate(schema=Schema.load(SCHEMA_PATH), db_path=str(db_path))


# --- US-3: regression runner over committed eval sets -------------------------

def test_regression_runs_all_layers(gate: Gate) -> None:
    metrics = run_regression(gate, EVAL_DIR)
    assert set(metrics) == {"corpus", "golden", "adversarial", "mutation"}
    for layer in ("corpus", "golden"):
        assert metrics[layer].total > 0


def test_regression_false_accept_zero(gate: Gate) -> None:
    metrics = run_regression(gate, EVAL_DIR)
    assert metrics["adversarial"].false_accepts == 0, "headline metric violated"
    assert metrics["adversarial"].reason_accuracy == 1.0


def test_regression_golden_answer_correctness(gate: Gate) -> None:
    metrics = run_regression(gate, EVAL_DIR)
    assert metrics["golden"].answer_correctness == 1.0


def test_regression_conversion_is_reported_honestly(gate: Gate) -> None:
    metrics = run_regression(gate, EVAL_DIR)
    # mutation paraphrases are the hard case; conversion must be <= corpus
    assert 0.0 <= metrics["mutation"].conversion <= metrics["corpus"].conversion


# --- US-4: clustering + pattern approval --------------------------------------

def test_cluster_rejections_groups_by_reason(gate: Gate) -> None:
    questions = [
        "delete all orders",
        "drop table orders",
        "select * from fake_table",
        "show me revenue from fake_table",
        "teleport to the moon",
    ]
    clusters = cluster_rejections(gate, questions)
    reasons = {c.reason for c in clusters}
    assert REASON_UNSAFE_OPERATION in reasons
    unsafe = next(c for c in clusters if c.reason == REASON_UNSAFE_OPERATION)
    assert unsafe.count == 2
    assert len(unsafe.examples) == 2


def test_approve_pattern_appends_to_library(tmp_path: Path) -> None:
    lib = tmp_path / "patterns.json"
    lib.write_text(json.dumps({"version": 1, "patterns": []}))
    approve_pattern({"intent": "join", "description": "x"}, lib)
    data = json.loads(lib.read_text())
    assert data["version"] == 2
    assert data["patterns"][0]["intent"] == "join"


def test_draft_pattern_without_llm_returns_none(gate: Gate) -> None:
    from sqlgate.learning import RejectionCluster

    cluster = RejectionCluster(reason="UNKNOWN_TABLE", count=1, examples=["select * from fake_table"])
    assert draft_pattern(cluster, proposer=None, schema=gate.schema) is None  # type: ignore[arg-type]


# --- US-5: reject vs repair with a deterministic fake LLM ----------------------

class FakeLLM(Proposer):
    """Returns scripted strict-JSON completions, like the real LLM would."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls = 0

    def propose(self, question: str, schema: Schema) -> IntentProposal:
        resp = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if resp.get("intent") is None:
            return IntentProposal(intent=None, slots={})
        return IntentProposal(intent=resp["intent"], slots=resp.get("slots", {}))

    def complete(self, system: str, user: str) -> str | None:
        resp = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return json.dumps(resp)


def test_repair_fixes_rejected_question(gate: Gate) -> None:
    """US-5: a 'select * from fake_table' rejection gets repaired to a valid query."""
    fake = FakeLLM(
        responses=[
            {"intent": "select", "slots": {"table": "products", "limit": 10}},
        ]
    )
    out = repair(gate, "select * from fake_table", fake, max_attempts=2)
    assert out["repaired"] is True
    assert out["attempts"] == 1
    assert out["result"].accepted


def test_repair_gives_up_without_wrong_accept(gate: Gate) -> None:
    """If the fake LLM keeps proposing garbage, repair fails SAFELY (no accept)."""
    fake = FakeLLM(
        responses=[
            {"intent": None},
        ]
    )
    out = repair(gate, "delete all orders", fake, max_attempts=2)
    assert out["repaired"] is False
    assert out["result"].accepted is False  # never silently accepts a write
