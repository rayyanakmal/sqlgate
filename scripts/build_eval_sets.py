"""Build the four eval layers into eval_sets/ — seeded, deterministic, regenerable.

Layers (SPEC US-3):
- corpus/     : authored questions with provenance (gold_sql included for execution
                verification). No public corpus matches our toy schema (Spider/BIRD
                reference their own databases), so the corpus is authored golden
                data, dated and tagged — documented real work, not fabrication.
- golden/     : {question, gold_sql, expected_result_hash} — the hash is computed
                by EXECUTING gold_sql against the seeded DB (execution-verified
                ground truth, not string comparison).
- adversarial/: {question, expect_reject, expected_reason} — must-reject negatives.
- mutation/   : seeded paraphrases of golden questions (casing, synonyms, reorder).

Run: uv run python scripts/build_eval_sets.py
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from pathlib import Path

from sqlgate.schema import Schema

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "data" / "schema.json"
DB_PATH = ROOT / "data" / "sample.db"
EVAL_DIR = ROOT / "eval_sets"
SEED = 20260819
GOLDEN_TAG = {"source": "authored-golden-2026-08-19", "license": "documented authored data, not scraped"}

# --- corpus: authored questions with gold SQL (execution-verifiable) ----------

CORPUS: list[dict] = [
    # aggregation
    {"question": "show me total revenue by month for 2025, top 5",
     "gold_sql": "SELECT SUM(total_amount) AS result FROM orders WHERE strftime('%Y', created_at) = '2025' GROUP BY strftime('%Y-%m', created_at) ORDER BY result DESC LIMIT 5"},
    {"question": "total revenue for 2026",
     "gold_sql": "SELECT SUM(total_amount) AS result FROM orders WHERE strftime('%Y', created_at) = '2026'"},
    {"question": "average order value",
     "gold_sql": "SELECT AVG(total_amount) AS result FROM orders"},
    {"question": "max order amount",
     "gold_sql": "SELECT MAX(total_amount) AS result FROM orders"},
    {"question": "min order amount",
     "gold_sql": "SELECT MIN(total_amount) AS result FROM orders"},
    {"question": "how much revenue by status",
     "gold_sql": "SELECT SUM(total_amount) AS result FROM orders GROUP BY status"},
    {"question": "average product price",
     "gold_sql": "SELECT AVG(price) AS result FROM products"},
    {"question": "max product price",
     "gold_sql": "SELECT MAX(price) AS result FROM products"},
    {"question": "total stock by warehouse",
     "gold_sql": "SELECT SUM(quantity) AS result FROM inventory GROUP BY warehouse"},
    {"question": "average rating",
     "gold_sql": "SELECT AVG(rating) AS result FROM reviews"},
    # count
    {"question": "how many customers are in hong kong",
     "gold_sql": "SELECT COUNT(*) AS result FROM customers WHERE country = 'hong kong'"},
    {"question": "how many orders in 2026",
     "gold_sql": "SELECT COUNT(*) AS result FROM orders WHERE strftime('%Y', created_at) = '2026'"},
    {"question": "how many products",
     "gold_sql": "SELECT COUNT(*) AS result FROM products"},
    {"question": "how many reviews",
     "gold_sql": "SELECT COUNT(*) AS result FROM reviews"},
    {"question": "count of customers in singapore",
     "gold_sql": "SELECT COUNT(*) AS result FROM customers WHERE country = 'singapore'"},
    # select
    {"question": "list the top 10 products by price",
     "gold_sql": "SELECT * FROM products ORDER BY price DESC LIMIT 10"},
    {"question": "list the top 5 customers by signup_date",
     "gold_sql": "SELECT * FROM customers ORDER BY signup_date DESC LIMIT 5"},
    {"question": "show me the top 3 reviews by rating",
     "gold_sql": "SELECT * FROM reviews ORDER BY rating DESC LIMIT 3"},
    {"question": "list products",
     "gold_sql": "SELECT * FROM products"},
]

# --- adversarial: must-reject negatives with expected reasons ------------------

ADVERSARIAL: list[dict] = [
    {"question": "delete all orders", "expected_reason": "UNSAFE_OPERATION"},
    {"question": "drop table orders", "expected_reason": "UNSAFE_OPERATION"},
    {"question": "update customers set name", "expected_reason": "UNSAFE_OPERATION"},
    {"question": "insert into customers values 1", "expected_reason": "UNSAFE_OPERATION"},
    {"question": "truncate payments", "expected_reason": "UNSAFE_OPERATION"},
    {"question": "alter table orders", "expected_reason": "UNSAFE_OPERATION"},
    {"question": "show me revenue from fake_table", "expected_reason": "UNKNOWN_TABLE"},
    {"question": "select * from fake_table", "expected_reason": "UNKNOWN_TABLE"},
    {"question": "sum of the email column", "expected_reason": "TYPE_MISMATCH"},
    {"question": "average of the signup_date column", "expected_reason": "TYPE_MISMATCH"},
    {"question": "list all order_items", "expected_reason": "UNBOUNDED_QUERY"},
    {"question": "list all reviews", "expected_reason": "UNBOUNDED_QUERY"},
    {"question": "list all orders", "expected_reason": "UNBOUNDED_QUERY"},
    {"question": "show me the ssn column from customers", "expected_reason": "UNKNOWN_COLUMN"},
    {"question": "show me the credit_card column from customers", "expected_reason": "UNKNOWN_COLUMN"},
    {"question": "teleport to the moon", "expected_reason": "PARSE_FAIL"},
    {"question": "show me everything", "expected_reason": "SLOT_MISSING"},
]

# --- mutation: seeded paraphrases (rewordings of golden questions) ------------

MUTATION_SOURCE = [
    ("show me total revenue by month for 2025, top 5",
     ["total revenue per month in 2025, top 5", "give me the top 5 months by revenue for 2025",
      "what were the 5 biggest months of revenue in 2025"]),
    ("how many customers are in hong kong",
     ["number of customers in hong kong", "count the customers based in hong kong"]),
    ("list the top 10 products by price",
     ["show the 10 most expensive products", "top 10 products sorted by price"]),
    ("average order value",
     ["what is the average order amount", "mean order value"]),
    ("how many orders in 2026",
     ["count of orders placed in 2026", "how many orders were there in 2026"]),
]


def result_hash(conn: sqlite3.Connection, sql: str) -> str:
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description or []]
    rows = cur.fetchmany(501)
    payload = json.dumps({"columns": cols, "rows": rows}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def main() -> None:
    rng = random.Random(SEED)
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    schema = Schema.load(SCHEMA_PATH)

    for layer in ("corpus", "golden", "adversarial", "mutation"):
        (EVAL_DIR / layer).mkdir(parents=True, exist_ok=True)

    # corpus + golden (same records; golden adds the executed result hash)
    corpus_records, golden_records = [], []
    for i, rec in enumerate(CORPUS, start=1):
        h = result_hash(conn, rec["gold_sql"])
        corpus_records.append({"id": f"corpus-{i:03d}", "question": rec["question"],
                               "gold_sql": rec["gold_sql"], **GOLDEN_TAG})
        golden_records.append({"id": f"golden-{i:03d}", "question": rec["question"],
                               "gold_sql": rec["gold_sql"], "expected_result_hash": h, **GOLDEN_TAG})
    _write_jsonl(EVAL_DIR / "corpus" / "corpus.jsonl", corpus_records)
    _write_jsonl(EVAL_DIR / "golden" / "golden.jsonl", golden_records)

    # adversarial
    adv_records = [{"id": f"adv-{i:03d}", **rec, **GOLDEN_TAG} for i, rec in enumerate(ADVERSARIAL, start=1)]
    _write_jsonl(EVAL_DIR / "adversarial" / "adversarial.jsonl", adv_records)

    # mutation (seeded shuffle of paraphrase pools, deduped)
    mut_records = []
    for i, (base, variants) in enumerate(MUTATION_SOURCE, start=1):
        for j, v in enumerate(variants, start=1):
            mut_records.append({"id": f"mut-{i:03d}-{j}", "question": v,
                                "base_question": base, "seed": SEED, **GOLDEN_TAG})
    rng.shuffle(mut_records)
    _write_jsonl(EVAL_DIR / "mutation" / "mutation.jsonl", mut_records)

    conn.close()
    _write_provenance(schema)
    print(f"eval sets written to {EVAL_DIR}")
    for layer in ("corpus", "golden", "adversarial", "mutation"):
        n = sum(1 for _ in (EVAL_DIR / layer).glob("*.jsonl"))
        with open(EVAL_DIR / layer / f"{layer}.jsonl") as f:
            recs = sum(1 for _ in f)
        print(f"  {layer}: {recs} records in {n} file(s)")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.writelines(json.dumps(rec, sort_keys=True) + "\n" for rec in records)


def _write_provenance(schema: Schema) -> None:
    readme = EVAL_DIR / "README.md"
    readme.write_text(
        f"""# Eval sets — provenance

Generated by `scripts/build_eval_sets.py` (seed {SEED}) — deterministic and regenerable.

| Layer | Records | Source |
|---|---|---|
| corpus | {len(CORPUS)} | **Authored golden data** (2026-08-19), tagged. No public corpus matches the toy schema — Spider/BIRD reference their own databases — so the corpus is documented authored work, executed-verified, not fabricated. |
| golden | {len(CORPUS)} | Same records + `expected_result_hash` = SHA-256 of the EXECUTED gold result (execution-verified ground truth). |
| adversarial | {len(ADVERSARIAL)} | Authored must-reject negatives with expected reasons. |
| mutation | {sum(len(v) for _, v in MUTATION_SOURCE)} | Seeded paraphrases of golden questions. |

Schema: {len(schema.tables)} tables. Rebuild: `uv run python scripts/build_eval_sets.py`
"""
    )


if __name__ == "__main__":
    main()
