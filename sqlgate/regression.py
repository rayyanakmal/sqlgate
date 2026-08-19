"""US-3 regression runner: run the eval layers through the gate, report metrics.

Per-layer metrics (SPEC US-3 / Data Contracts):
- conversion rate         = accepted / total
- execution success rate  = accepted & executed ok / accepted
- answer correctness      = accepted & result hash == gold hash / accepted (golden layer)
- false-accepts           = adversarial lines accepted (headline: must be 0)
- rejection-reason accuracy = adversarial rejections carrying the expected reason
- usable-draft %          = accepted + accepted-after-minor-edit (v0.1: accepted only,
                            repair-mode numbers arrive with US-5)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlgate.gate import Gate
from sqlgate.result import ExecutionResult

Layer = str


@dataclass
class LayerMetrics:
    layer: str
    total: int = 0
    accepted: int = 0
    executed_ok: int = 0
    correct: int = 0
    false_accepts: int = 0
    reason_accurate: int = 0
    details: list[dict[str, object]] = field(default_factory=list)

    @property
    def conversion(self) -> float:
        return self.accepted / self.total if self.total else 0.0

    @property
    def execution_success(self) -> float:
        return self.executed_ok / self.accepted if self.accepted else 0.0

    @property
    def answer_correctness(self) -> float:
        return self.correct / self.accepted if self.accepted else 0.0

    @property
    def false_accept_rate(self) -> float:
        return self.false_accepts / self.total if self.total else 0.0

    @property
    def reason_accuracy(self) -> float:
        return self.reason_accurate / self.total if self.total else 0.0

    @property
    def usable_draft(self) -> float:
        # v0.1: identical to conversion; US-5 repair mode adds the delta
        return self.conversion


def run_regression(gate: Gate, eval_dir: str | Path) -> dict[Layer, LayerMetrics]:
    eval_dir = Path(eval_dir)
    out: dict[Layer, LayerMetrics] = {}
    for layer in ("corpus", "golden", "adversarial", "mutation"):
        m = LayerMetrics(layer=layer)
        path = eval_dir / layer / f"{layer}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            m.total += 1
            result = gate.process(rec["question"])
            entry = {"id": rec.get("id"), "question": rec["question"], "accepted": result.accepted,
                     "reason": result.reason, "sql": result.sql}
            if result.accepted:
                m.accepted += 1
                if result.execution and result.execution.ok:
                    m.executed_ok += 1
                    entry["row_count"] = result.execution.row_count
                    if layer == "golden":
                        h = _result_hash_of(result.execution)
                        if h == rec.get("expected_result_hash"):
                            m.correct += 1
                            entry["correct"] = True
                        else:
                            entry["correct"] = False
                if layer == "adversarial":
                    m.false_accepts += 1
            else:
                if layer == "adversarial" and result.reason == rec.get("expected_reason"):
                    m.reason_accurate += 1
            m.details.append(entry)
        out[layer] = m
    return out


def _result_hash_of(execution: ExecutionResult) -> str:
    import hashlib

    payload = json.dumps({"columns": execution.columns, "rows": execution.rows}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def format_report(metrics: dict[Layer, LayerMetrics]) -> str:
    header = (
        f"{'layer':<12} {'total':>6} {'conv%':>7} {'exec%':>7} {'corr%':>7} "
        f"{'false-acc':>9} {'reason%':>8} {'usable%':>8}"
    )
    lines = [header, "-" * len(header)]
    for layer in ("corpus", "golden", "adversarial", "mutation"):
        m = metrics.get(layer)
        if m is None:
            continue
        lines.append(
            f"{m.layer:<12} {m.total:>6} {m.conversion * 100:>6.1f}% "
            f"{m.execution_success * 100:>6.1f}% {m.answer_correctness * 100:>6.1f}% "
            f"{m.false_accepts:>9} {m.reason_accuracy * 100:>7.1f}% "
            f"{m.usable_draft * 100:>7.1f}%"
        )
    return "\n".join(lines)
