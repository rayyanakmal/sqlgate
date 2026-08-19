"""Typer CLI: convert questions and run the regression suite."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from sqlgate.gate import Gate
from sqlgate.proposer import StubProposer
from sqlgate.schema import Schema

app = typer.Typer(add_completion=False)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "data" / "schema.json"
DB_PATH = ROOT / "data" / "sample.db"


def _gate() -> Gate:
    return Gate(schema=Schema.load(SCHEMA_PATH), proposer=StubProposer(), db_path=str(DB_PATH))


@app.command("convert")
def convert(question: str, json_out: bool = False) -> None:
    """Convert a natural-language question to safe SQL (or a rejection)."""
    result = _gate().process(question)
    if json_out:
        payload = {
            "accepted": result.accepted,
            "sql": result.sql,
            "reason": result.reason,
            "detail": result.detail,
            "trace": [{"stage": t.stage, "ok": t.ok, "detail": t.detail} for t in result.trace],
        }
        typer.echo(json.dumps(payload, indent=2))
        return
    if result.accepted:
        typer.echo(f"ACCEPT\n{result.sql}")
        if result.execution and result.execution.ok:
            typer.echo(f"executed: {result.execution.row_count} rows")
    else:
        typer.echo(f"REJECT ({result.reason})\n{result.detail}")


@app.command("regression")
def regression(
    json_out: bool = False,
    eval_dir: str = str(ROOT / "eval_sets"),
) -> None:
    """Run the versioned eval sets through the gate and report per-layer metrics (US-3)."""
    from sqlgate.regression import format_report, run_regression

    metrics = run_regression(_gate(), eval_dir)
    if json_out:
        payload = {
            layer: {
                "total": m.total,
                "conversion": round(m.conversion, 4),
                "execution_success": round(m.execution_success, 4),
                "answer_correctness": round(m.answer_correctness, 4),
                "false_accepts": m.false_accepts,
                "reason_accuracy": round(m.reason_accuracy, 4),
                "usable_draft": round(m.usable_draft, 4),
            }
            for layer, m in metrics.items()
        }
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(format_report(metrics))
    for layer, m in metrics.items():
        if layer == "adversarial" and m.false_accepts > 0:
            typer.echo(f"!! RELEASE BLOCKER: {m.false_accepts} false accepts in {layer}")


@app.command("clusters")
def clusters(eval_dir: str = str(ROOT / "eval_sets")) -> None:
    """US-4.1: cluster rejected questions by rejection reason."""
    from sqlgate.learning import cluster_rejections

    questions = []
    for layer in ("corpus", "mutation", "adversarial"):
        path = Path(eval_dir) / layer / f"{layer}.jsonl"
        if path.exists():
            questions += [json.loads(l)["question"] for l in path.read_text().splitlines() if l.strip()]
    for c in cluster_rejections(_gate(), questions):
        typer.echo(f"{c.reason:<20} {c.count:>3}  e.g. {c.examples[0] if c.examples else ''}")


@app.command("repair")
def repair_cmd(question: str, max_attempts: int = 2) -> None:
    """US-5: try auto-repairing a rejected question with the LLM (needs DEEPSEEK_API_KEY)."""
    from sqlgate.learning import repair
    from sqlgate.llm_proposer import LLMProposer

    out = repair(_gate(), question, LLMProposer(), max_attempts=max_attempts)
    if out["repaired"]:
        typer.echo(f"REPAIRED after {out['attempts']} attempt(s)")
        typer.echo(out["result"].sql)
    else:
        typer.echo(f"NOT REPAIRED after {out['attempts']} attempt(s)")
        typer.echo(f"final: {out['result'].reason} — {out['result'].detail}")


if __name__ == "__main__":
    app()
