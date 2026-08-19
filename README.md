# SQLGate

**Natural language to safe, executable SQL through a deterministic gate.**

Ask a question in plain English ("show me total revenue by month for 2025, top 5").
SQLGate returns the exact SQL — validated against the real schema, passed through
safety rules, parsed with a real SQL grammar, and **executed against a read-only
database to prove it runs** — or it rejects, with a reason. Never both, never silent.

```
question → [proposer: intent + slots] → [gate: intent_validate → schema_validate →
safety_rules → sql_render → parser_check → execution_oracle] → exact SQL OR rejection
```

## Why this exists

Most "AI can answer your data questions" tools generate SQL and cross their fingers.
SQLGate is built on the opposite principle, proven in production at Hitachi Rail:
**the LLM only proposes meaning; deterministic code disposes the form.** Every stage
after the proposer is rules — schema validation, safety checks, a real SQL parser,
and actual execution against an engine-level read-only database. Wrong output is
structurally impossible, not merely unlikely.

The headline metric is **false-accepts = 0**: the adversarial eval set (DROP TABLE,
DELETE, unknown tables/columns, unbounded scans) is rejected 100% with correct reasons.

No Hitachi data is used — the demo runs on a toy e-commerce schema with seeded,
regenerable data and authored, provenance-tagged golden eval sets.

## Try it

The demo UI runs fully offline with the deterministic stub proposer — no API key:

```bash
uv sync
uv run python scripts/build_db.py          # build the seeded sample.db
uv run streamlit run sqlgate/ui/streamlit_app.py
```

Or via CLI:

```bash
uv run sqlgate convert "show me total revenue by month for 2025, top 5"
uv run sqlgate convert "drop table orders"          # -> REJECT (UNSAFE_OPERATION)
uv run sqlgate regression                           # per-layer eval metrics
uv run pytest -x --tb=short                         # 50 acceptance tests
```

## The gate, stage by stage

| Stage | What it does | Rejects with |
|---|---|---|
| 1. intent_validate | Required slots present, types correct | SLOT_MISSING, PARSE_FAIL, UNSAFE_OPERATION |
| 2. schema_validate | Tables/columns exist, types compatible | UNKNOWN_TABLE, UNKNOWN_COLUMN, TYPE_MISMATCH |
| 3. safety_rules | SELECT-only; LIMIT on large-table scans | UNSAFE_OPERATION, UNBOUNDED_QUERY |
| 4. sql_render | Deterministic render from the pattern library | — |
| 5. parser_check | Real SQL grammar (sqlglot), single SELECT | PARSE_FAIL |
| 6. execution_oracle | Runs on the read-only DB (row cap + timeout) | PARSE_FAIL (internal render bug) |

Proposers are pluggable behind one contract (SPEC AC-1.5): the **stub** (deterministic,
offline, $0), **DeepSeek LLM** (capped in the public demo), and a **fine-tuned LoRA
proposer** trained on your own Mac. The gate never changes.

## Project layout

```
sqlgate/
├── sqlgate/               # gate core (gate, proposer, patterns, schema, oracle, result)
│   └── ui/streamlit_app.py# demo UI
├── data/                  # schema.json, patterns.json (authored vocabulary)
├── eval_sets/             # seeded 4-layer eval (corpus/golden/adversarial/mutation)
├── scripts/               # build_db.py, build_eval_sets.py
├── proposer_finetune/     # US-6: train a LoRA proposer on Apple Silicon (mlx-lm)
└── tests/                 # 50 tests, including the adversarial false-accept-zero suite
```

## The upgrade path: fine-tune your own proposer

The gate generates its own training data — every accepted conversion is a verified
(question → intent + slots) pair. `proposer_finetune/` turns that into a LoRA
fine-tune on Apple Silicon (MacBook Air 24GB is plenty for a 3B model), then
evaluates it through the SAME gate and eval sets as the stub. See
`proposer_finetune/README.md`.

## Safety notes

- The embedded DB opens `mode=ro` at the **engine level** — writes are impossible,
  not just discouraged.
- Every execution runs with a row cap and timeout.
- The DeepSeek key (if enabled) lives in Streamlit secrets only, never in the repo.
- The adversarial eval set is a committed, versioned artifact; a false-accept is a
  release blocker.

## License

MIT. See [LICENSE](LICENSE). Eval questions are authored golden data (provenance in
`eval_sets/README.md`); benchmark design inspired by Spider/BIRD and the NL2Test
(ISSTA 2026) experience paper.

## Status

v0.1.0 — US-1..US-6 implemented. SPEC.md is the contract; ARCHITECTURE.md traces
every design decision to its source.
