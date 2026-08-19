# SQLGate — natural language to safe, executable SQL through a deterministic gate

> spec-version: 1.0
> last-updated: 2026-08-19
> research base: /home/rayyan/hermes-resources/gate-demo-research.md + P1 SQL landscape (2026-08-19, see Sources)
> origin: Hitachi rail-test step conversion system (Phase 3 hybrid verdict) — the pattern, applied to a public SQL machine. No Hitachi data.
> history: v0.1 (Gherkin) and v0.2 (SQL draft) were superseded by this clean-slate rewrite.

## Overview

SQLGate is a portfolio demo of the internship's core architecture: **the LLM proposes meaning, deterministic code disposes form.**

A data analyst types a question ("show me total revenue by month for 2025, top 5"). SQLGate returns either the exact, safe SQL query for it — validated against a real schema, passed through safety rules, executed against a real read-only database to prove it runs — or a structured rejection with a reason. Every stage of the gate is visible in the UI.

The demo ships with a real embedded database so **visitors can execute the output themselves and try to break the safety boundary**, plus a versioned, regenerable eval set and a learning loop (rejected questions → proposed new query patterns → human approval → coverage lift).

Domain: a toy e-commerce database (SQLite, ~8 tables, seeded regenerable data). Not rail. Nothing imported from Hitachi.

## Problem statement

Data teams are being told LLMs can answer questions in plain English. The gap: generated SQL is untrusted — it can be syntactically valid yet wrong (wrong table, wrong join, wrong filter), or genuinely dangerous (DROP, DELETE, unbounded scans). Production guidance (2026) is explicit: prompt engineering cannot guarantee database safety; a validation layer must parse the SQL, bind it to catalog metadata, apply policy rules, and record the decision. That validation layer is the gate.

## Personas

| Persona | What they do with SQLGate |
|---|---|
| **Portfolio reviewer / interviewer** | Tests the demo live: asks questions, executes queries, tries to break the gate. Judges: is this safe-by-design, or another LLM chatbot? |
| **Data analyst (visitor)** | Types questions, reads generated SQL, executes against the sample DB, checks answers against gold. |
| **Rayyan (maintainer)** | Runs the regression suite, approves query-pattern promotions, trains the fine-tuned proposer on Mac. |

## Goals / Metrics of success

- **Primary:** false-accepts = 0 on the adversarial set (headline — the gate never lets an unsafe or schema-invalid query through).
- **Secondary:** conversion rate, execution success rate, answer correctness vs gold, rejection-reason accuracy, usable-draft % — all reported per eval layer, versioned.
- **Demo goal:** a visitor can execute the output, compare to gold, and try to break the safety boundary — all live, without an LLM key (stub mode).

## Prerequisites (Human Tasks)

| Task | Status |
|---|---|
| DeepSeek API key for LLM proposer mode | Present on Pi (~/.hermes env); goes to Streamlit secrets at launch |
| Offline mode | No key needed — deterministic stub proposer |
| Spider benchmark subset (public NL→SQL) | Downloaded by committed script; small e-commerce subset only |
| Nothing else | DB schema/data, corpus, golden/adversarial/mutation pipelines are committed scripts |

## US-1: Convert a question to safe, executable SQL (the core)

**AC-1.1:** Given an informal question, when the user submits it, then the app returns exactly one of: an exact SQL query, or a structured rejection with a reason. Never both, never silent.

**AC-1.2:** Correctness is proven by an external oracle: every accepted query (a) parses with a real SQL parser (sqlglot), (b) validates against the real schema (tables, columns, types), and (c) **executes successfully against the embedded read-only SQLite DB**. Execution success is the oracle — never string comparison in app code. (Industry-standard: Execution Accuracy, per the ETM paper.)

**AC-1.3:** False-accepts = 0 on the adversarial set: every unsafe query (DROP/DELETE/UPDATE/INSERT, unknown table/column, unbounded full scan) is rejected with its expected reason.

**AC-1.4:** Rejection reasons come from a fixed taxonomy (UNKNOWN_TABLE, UNKNOWN_COLUMN, TYPE_MISMATCH, UNSAFE_OPERATION, UNBOUNDED_QUERY, SLOT_MISSING, CROSS_INTENT_OVERRIDE, PARSE_FAIL). One reason per rejection, machine-readable.

**AC-1.5:** Two proposer modes, same gate: offline stub (deterministic, no key — demo always runs) and LLM proposer (DeepSeek). Switching modes never changes gate behavior.

Edge cases:
- Empty/whitespace/casing variants → normalized before the gate; normalized input is the dedupe key (internship eval rule).
- "show me everything" (no table/columns) → SLOT_MISSING. Never guessed.
- "delete all orders" → UNSAFE_OPERATION (SELECT-only by policy).
- "select * from fake_table" → UNKNOWN_TABLE.
- "sum of the email column" → TYPE_MISMATCH (column not numeric).
- Query with no LIMIT on a large table → UNBOUNDED_QUERY (rewrite or reject).
- LLM proposer returns garbage intent → PARSE_FAIL/UNKNOWN. Stub never reaches the LLM in offline mode.

## US-2: Show the gate working + let visitors test it (transparency)

**AC-2.1:** The UI shows the full chain for the last submitted question: input → proposer output (intent + slots) → each gate stage (schema validation, safety rules, parser check) → final SQL or rejection.

**AC-2.2:** Every sample question shown in the UI traces to a provenance record (Spider source, or authored golden data tagged as such). Zero fabricated sample questions.

**AC-2.3:** For any accepted query, the visitor can press **Execute** and see the real result table from the embedded read-only DB (row cap + timeout enforced).

**AC-2.4:** For golden questions, the demo displays the expected result side-by-side with a match/mismatch badge (execution-accuracy style, not string match).

**AC-2.5:** The UI includes live "try to break me" examples (DROP TABLE, DELETE, unbounded scan, unknown table) — the gate rejects each with a visible reason. The safety boundary is attackable by the visitor and holds.

## US-3: Regression suite (versioned eval)

**AC-3.1:** `scripts/build_eval_sets.py` regenerates all four layers (corpus, golden, adversarial, mutation) deterministically from a seeded RNG; outputs are committed and versioned.

**AC-3.2:** The regression tab runs the eval set and reports per-layer tables: conversion rate, execution success rate, answer correctness (gold comparison), false-accepts (headline: must be 0), rejection-reason accuracy, usable-draft %.

**AC-3.3:** Adding/removing a query pattern changes the eval run and reports coverage lift — the number that replaces "hybrid lift" as the success metric.

**AC-3.4:** A single CLI command reproduces a regression run.

## US-4: Query-pattern suggestions (the differentiator)

**AC-4.1:** The app clusters rejected questions by rejection reason and shows the clusters.

**AC-4.2:** For a chosen cluster, the LLM drafts a proposed query pattern (intent + slot shape + template SQL).

**AC-4.3:** Human approves/edits/rejects the proposal before it enters the pattern library. Never auto-promote (research consensus: human review mandatory).

**AC-4.4:** After promotion, re-running the eval shows the coverage lift — the internship's actual lever (template promotion, not more LLM), made visible as a product loop.

## US-5: Reject vs repair comparison

**AC-5.1:** Optional "auto-repair" mode: on validation failure, feed the error back to the LLM and retry (max N=2 attempts).

**AC-5.2:** The app reports repair success rate vs plain rejection rate side by side. The comparison numbers are themselves an eval screen.

**AC-5.3:** Default posture stays reject-with-reason. Repair is opt-in per run.

## US-6: Fine-tuned proposer module (the upgrade path)

**AC-6.1:** `proposer_finetune/` ships in the repo with a clean-slate README: anyone can install deps, build the dataset, and train a LoRA proposer (informal question → intent + slots) on Apple Silicon via mlx-lm.

**AC-6.2:** `build_dataset.py` produces train/valid/test splits from gate-validated conversions + golden pairs (the gate is the label oracle) — seeded, deterministic.

**AC-6.3:** `evaluate.py` runs the fine-tuned proposer through the SAME gate and eval sets as stub and LLM proposers, and outputs a comparison table (conversion, execution success, false-accepts, reason accuracy). False-accepts must stay 0 for every proposer — the gate enforces it regardless.

**AC-6.4:** A `FineTunedProposer` implements the same proposer interface (AC-1.5) and runs locally (mlx-lm on Mac; optional GGUF export for llama.cpp/Pi).

**AC-6.5:** A committed comparison table (trained on the user's Mac, results committed) appears in the demo UI — the upgrade path's numbers are public without serving the model.

## Data Contracts

IntentProposal (proposer output, the intermediate representation):
```json
{
  "intent": "aggregation",
  "slots": {
    "table": "orders",
    "group_by": ["month"],
    "aggregate": "sum",
    "metric": "amount",
    "filters": [{"column": "year", "op": "=", "value": 2025}],
    "order_by": [{"column": "revenue", "dir": "desc"}],
    "limit": 5
  }
}
```

Schema entry (the registry for SQL):
```json
{
  "table": "orders",
  "columns": [
    {"name": "id", "type": "integer", "key": true},
    {"name": "customer_id", "type": "integer", "fk": "customers.id"},
    {"name": "amount", "type": "real"},
    {"name": "created_at", "type": "datetime"}
  ]
}
```

Rejection:
```json
{"accepted": false, "reason": "UNKNOWN_COLUMN", "detail": "column 'email' does not exist in table 'orders'", "intent_proposed": "aggregation"}
```

Eval sets (four layers, JSONL with provenance per record):
- `corpus/` — Spider subset questions (real, public, cited; e-commerce domains)
- `golden/` — {question, gold_sql, expected_result_hash} pairs
- `adversarial/` — {question, expect_reject, expected_reason} negatives (unsafe ops, unknown schema, unbounded scans)
- `mutation/` — scripted seeded paraphrases of golden questions

Metrics (reported per layer):
- conversion rate = accepted / total
- execution success rate = accepted queries that run without error against the embedded DB
- answer correctness = accepted queries whose result matches the gold result (golden layer only)
- false-accepts = adversarial lines accepted (must be 0)
- rejection-reason accuracy = adversarial rejections carrying the expected reason
- usable-draft % = accepted + acceptable-after-minor-edit (NL2Test-style)

## Hosting / Demo Modes (locked)

| Proposer | Where it runs | Cost | Public testing |
|---|---|---|---|
| Stub (deterministic) | Streamlit Cloud free tier | $0, no secrets, always on | Unlimited — the gate story is fully visible without any LLM |
| LLM (DeepSeek) | Streamlit Cloud + `st.secrets` | fractions of a cent per call | Per-session cap (~20 conversions) |
| Fine-tuned (mlx-lm) | Local: Mac (MLX) or Pi (GGUF/llama.cpp) | $0 | Local showpiece + committed comparison table (AC-6.5) |

Execution safety: embedded SQLite opens read-only (URI `mode=ro`, engine-level), row cap + timeout on every query. LLM key lives in Streamlit secrets only, never in the repo. Prepaid balance as hard ceiling.

## Out of Scope (v0.1)

- Bring-your-own-schema / multi-DB support (v2 extension point)
- Visualization / dashboard generation from results
- Vanna-style RAG retrieval layer (schema-in-prompt is enough; RAG adds staleness risk — research verdict)
- WrenAI-style semantic layer (over-architecture for a demo)
- Constrained decoding (Outlines/XGrammar) as the headline — technique, not outcome
- Silent auto-fix as the default posture (kills the safety story)
- Any Hitachi data, rail vocab, or intern metrics (1,515→505→510 are theirs; not reused)
- Full Spider/BIRD benchmark runs (Spider 2.0 and BIRD are agentic/33GB-scale — cite, don't run; use a small e-commerce subset)
- GitHub Actions CI for the corpus scraper (local committed script is enough for v0.1)

## Extension Points

- Proposer interface: stub ↔ DeepSeek ↔ fine-tuned (open/closed) — the gate never changes
- Gate stages: new stages slot into the chain without touching existing ones
- Bring-your-own-schema: a v2 "upload your own SQLite file" path — the gate adapts to the uploaded schema
- Metrics: new metrics plug into the report without changing the eval runner

## Sources (P1)

- dpriver.com — "Text-to-SQL Security: 10 Risks Before Production" (2026-05): validation layer = parse → catalog bind → policy rules → risk score → record decision. Our gate, described by the industry.
- arXiv 2407.07313 (ETM) — Execution Accuracy vs Exact Set Matching analysis: execution is the standard oracle; the two metrics disagree — we report both, headline on execution.
- Spider (10,181 Q / 200 DBs / 138 domains) + BIRD (12,751 Q / 33.4GB) — public benchmarks; we use a small Spider e-commerce subset.
- vanna.ai / WrenAI landscape — both solve context-retrieval, not safety; neither demos a visible, attackable gate. Stale-example degradation is a known Vanna failure mode (avoid RAG as core).
- db-agent (GitHub) — production text-to-SQL agent with safety guardrails; confirms schema-aware + guardrail pattern at enterprise scale.
- gate-demo-research.md — the internship-pattern research base (NL2Test etc.).

## Changelog

- 1.0 (2026-08-19): clean-slate rewrite. Project named SQLGate; SQL domain locked; visitor-testable execution oracle (US-2.3–2.5); US-6 fine-tuned proposer module; hosting modes; P1 research folded in (execution-accuracy oracle, Spider subset, skip-RAG verdict).
