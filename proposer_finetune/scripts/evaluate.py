"""Evaluate the fine-tuned proposer through the SAME gate and eval sets.

Prints the comparison table (stub vs fine-tuned): conversion / execution
success / false-accepts / reason accuracy. False-accepts must stay 0 for
every proposer — the gate enforces it regardless of who proposes.

Usage (macOS, after training):
  python scripts/evaluate.py --adapter proposer_finetune/adapters
  python scripts/evaluate.py --adapter ... --json > proposer_comparison.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from sqlgate.gate import Gate
from sqlgate.proposer import IntentProposal, StubProposer
from sqlgate.regression import format_report, run_regression
from sqlgate.schema import Schema

ROOT = Path(__file__).resolve().parent.parent.parent


class FineTunedProposer:
    """Proposes via the trained MLX adapter (mlx_lm.generate). Same contract as stub."""

    def __init__(self, adapter_path: str | Path, model: str = "Qwen/Qwen2.5-3B-Instruct") -> None:
        self.adapter_path = str(adapter_path)
        self.model = model

    def propose(self, question: str, schema: Schema) -> IntentProposal:
        prompt = (
            "Return STRICT JSON only: {\"intent\": \"aggregation|count_rows|select|null\", "
            "\"slots\": {...}}. Question: " + question
        )
        try:
            out = subprocess.run(
                [
                    sys.executable, "-m", "mlx_lm.generate",
                    "--model", self.model,
                    "--adapter-path", self.adapter_path,
                    "--prompt", prompt,
                    "--max-tokens", "200",
                ],
                capture_output=True, text=True, timeout=120, check=False,
            )
            content = out.stdout
        except Exception:  # noqa: BLE001
            return IntentProposal(intent=None, slots={})
        try:
            start = content.index("{")
            end = content.rindex("}") + 1
            data = json.loads(content[start:end])
        except (ValueError, json.JSONDecodeError):
            return IntentProposal(intent=None, slots={})
        intent = data.get("intent")
        slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
        return IntentProposal(intent=intent if isinstance(intent, str) else None, slots=slots)


def compare(gate: Gate, adapter_path: str, eval_dir: Path) -> dict:
    stub = run_regression(gate, eval_dir)  # gate already wired to StubProposer
    fine_gate = Gate(
        schema=gate.schema,
        proposer=FineTunedProposer(adapter_path),
        db_path="data/sample.db",
    )
    fine = run_regression(fine_gate, eval_dir)
    return {"stub": stub, "fine_tuned": fine}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    gate = Gate(
        schema=Schema.load(ROOT / "data" / "schema.json"),
        proposer=StubProposer(),
        db_path=str(ROOT / "data" / "sample.db"),
    )
    result = compare(gate, args.adapter, ROOT / "eval_sets")
    if args.json:
        payload = {
            name: {
                layer: {
                    "total": m.total,
                    "conversion": round(m.conversion, 4),
                    "execution_success": round(m.execution_success, 4),
                    "answer_correctness": round(m.answer_correctness, 4),
                    "false_accepts": m.false_accepts,
                    "reason_accuracy": round(m.reason_accuracy, 4),
                }
                for layer, m in metrics.items()
            }
            for name, metrics in result.items()
        }
        print(json.dumps(payload, indent=2))
    else:
        print("== stub ==")
        print(format_report(result["stub"]))
        print("== fine-tuned ==")
        print(format_report(result["fine_tuned"]))
        for layer, m in result["fine_tuned"].items():
            if layer == "adversarial" and m.false_accepts > 0:
                print(f"!! RELEASE BLOCKER: {m.false_accepts} false accepts (fine-tuned)")


if __name__ == "__main__":
    main()
