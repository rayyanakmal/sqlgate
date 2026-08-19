"""Build the fine-tuning dataset: gate-validated question -> proposal pairs.

The gate is the label oracle: every ACCEPTED question carries a verified
IntentProposal (intent + slots), which is exactly the supervised signal the
proposer needs. Rejected questions are excluded — the gate said no.

Outputs (seeded, deterministic split):
  data/train.jsonl, data/valid.jsonl, data/test.jsonl

Each line: {"question": "...", "intent": "...", "slots": {...}}
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from sqlgate.gate import Gate
from sqlgate.schema import Schema

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = Path(__file__).resolve().parent.parent / "data"
EVAL_DIR = ROOT / "eval_sets"
SEED = 20260819

TRAIN_FRAC, VALID_FRAC = 0.8, 0.1


def collect_accepted(gate: Gate) -> list[dict]:
    records: dict[str, dict] = {}
    for layer in ("golden", "mutation"):
        path = EVAL_DIR / layer / f"{layer}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            q = rec["question"]
            result = gate.process(q)
            if result.accepted:
                records[q] = {
                    "question": q,
                    "intent": result.intent,
                    "slots": result.proposal,
                }
    # optional extra authored questions
    extra = DATA / "extra_questions.txt"
    if extra.exists():
        for q in extra.read_text().splitlines():
            q = q.strip()
            if not q or q in records:
                continue
            result = gate.process(q)
            if result.accepted:
                records[q] = {
                    "question": q,
                    "intent": result.intent,
                    "slots": result.proposal,
                }
    return list(records.values())


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    gate = Gate(schema=Schema.load(ROOT / "data" / "schema.json"), db_path=str(ROOT / "data" / "sample.db"))

    records = collect_accepted(gate)
    rng = random.Random(SEED)
    rng.shuffle(records)
    n_train = int(len(records) * TRAIN_FRAC)
    n_valid = int(len(records) * VALID_FRAC)
    splits = {
        "train": records[:n_train],
        "valid": records[n_train : n_train + n_valid],
        "test": records[n_train + n_valid :],
    }
    for name, items in splits.items():
        path = DATA / f"{name}.jsonl"
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in items))
        print(f"{name}: {len(items)} examples -> {path}")

    intents = {r["intent"] for r in records}
    print(f"total: {len(records)} examples, intents: {sorted(intents)}")


if __name__ == "__main__":
    main()
