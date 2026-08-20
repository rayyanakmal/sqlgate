<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/tests-50%20passing-brightgreen" alt="50 tests passing">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <img src="https://img.shields.io/badge/version-v0.1.0-blue" alt="v0.1.0">
</p>

<h1 align="center">🔒 SQLGate</h1>
<p align="center"><em>Natural language to safe, executable SQL — through a deterministic gate.</em></p>

<p align="center">
  <a href="https://sqlgate-vtvw4eerkeztryivq3eueb.streamlit.app/"><strong>🚀 Try the Live Demo</strong></a> ·
  <a href="#what-it-does"><strong>What it does</strong></a> ·
  <a href="#how-it-works"><strong>How it works</strong></a> ·
  <a href="#quick-start"><strong>Quickstart</strong></a> ·
  <a href="#features"><strong>Features</strong></a> ·
  <a href="#the-gate"><strong>The gate</strong></a> ·
  <a href="#fine-tune-your-own"><strong>Fine-tune your own</strong></a> ·
  <a href="#versions"><strong>Versions</strong></a> ·
  <a href="SPEC.md"><strong>Spec</strong></a> ·
  <a href="ARCHITECTURE.md"><strong>Architecture</strong></a>
</p>

---

## What it does

**SQLGate answers plain-English questions about your data with SQL that is *proven* to run — or it refuses, with a reason.**

Most "AI for your database" tools generate SQL and hope it's right. SQLGate is built on the opposite principle: **the LLM only proposes meaning; deterministic code disposes the form.** Every stage after the proposer is rules — schema validation, safety checks, a real SQL parser, and actual execution against a database that is read-only at the engine level.

Think of it as **an interpreter with a rulebook** — the AI suggests what your question means, a strict clerk checks it line by line against the schema and the safety rules, and the only two possible outcomes are:

- **An exact SQL query that already executed successfully** (with the rows to prove it), or
- **A structured rejection with a machine-readable reason** (`UNKNOWN_TABLE`, `UNSAFE_OPERATION`, `UNBOUNDED_QUERY`, …) — never a guess, never a silent fix.

The headline metric is **false-accepts = 0**: the built-in adversarial set (`DROP TABLE`, `DELETE`, unknown columns, unbounded scans) is rejected 100% of the time, with the correct reason every time.

The pattern is the production-proven verdict from a safety-critical LLM internship at Hitachi Rail — applied here to a public, testable machine. **No Hitachi data is used**: the demo runs on a toy e-commerce schema with seeded, regenerable data.

---

## Screenshots

### Golden questions — correctness proven by execution

<div align="center">
  <a href="https://sqlgate-vtvw4eerkeztryivq3eueb.streamlit.app/">
    <img src="assets/dashboard.png" alt="SQLGate demo — golden questions tab: each question executed against the read-only DB with a MATCH badge when the result equals the expected hash" width="700">
  </a>
  <p><em>Live app: golden questions run through the full gate and execute for real — MATCH badges compare the result against the expected answer hash.</em></p>
</div>

---

## How it works

```
  1. PROPOSE           2. GATE (deterministic)                   3. EXECUTE
  ────────────         ──────────────────────────                ─────────────
  A proposer (stub,    intent_validate → schema_validate →       Runs on a REAL
  DeepSeek LLM, or     safety_rules → sql_render →               read-only SQLite
  fine-tuned LoRA)     parser_check (sqlglot)                    DB (mode=ro) —
  turns the question                                          proves it runs,
  into intent + slots                                         row cap + timeout
```

- **Proposers are pluggable, the gate never changes** — swap the stub for an LLM or a fine-tuned model and the gate behaves identically (SPEC AC-1.5)
- **Rejection is the default posture** — no guessing, no silent fixes, every rejection carries a reason from a fixed taxonomy
- **Correctness is proven by execution** — accepted SQL actually runs against the read-only database; golden questions compare against expected result hashes, never string-matching in app code

---

## Quick Start

```bash
# Clone + install
git clone https://github.com/rayyanakmal/sqlgate.git
cd sqlgate
uv sync

# Build the seeded sample database (regenerable, deterministic)
uv run python scripts/build_db.py

# Convert a question — offline, no API key needed
uv run sqlgate convert "show me total revenue by month for 2025, top 5"
# ACCEPT
# SELECT SUM(total_amount) AS result FROM orders WHERE strftime('%Y', created_at) = '2025'
#   GROUP BY strftime('%Y-%m', created_at) ORDER BY result DESC LIMIT 5
# executed: 5 rows

# Watch it refuse, with a reason
uv run sqlgate convert "drop table orders"
# REJECT (UNSAFE_OPERATION)
# write operations are not allowed (SELECT-only)

# Launch the web dashboard
uv run streamlit run sqlgate/ui/streamlit_app.py

# Run the regression suite against the committed eval sets
uv run sqlgate regression

# Run the acceptance tests
uv run pytest -x --tb=short
```

---

## Features

### ✅ Safety that's structural, not aspirational
- **Deterministic gate** — six stages of pure rules between the AI and your data: intent validation, schema validation, safety rules, deterministic rendering, real SQL grammar parsing (sqlglot), and execution
- **Read-only at the engine level** — the database opens with SQLite `mode=ro`; writes are *impossible*, not just discouraged, plus a row cap and timeout on every execution
- **False-accepts = 0** — the committed adversarial eval set is rejected 100% with correct reasons; a single false-accept is a release blocker

### 🔍 Transparency — watch every decision
- **Gate trace** — the UI shows every stage: what the proposer proposed, which stage rejected it, and why
- **Try to break me** — a live adversarial tab where visitors attempt `DELETE`, unknown tables, and unbounded scans, and watch them all get rejected
- **Golden questions** — four committed questions with expected-result hashes; the app executes them live and badges MATCH / MISMATCH

### 📊 Measured, not claimed
- **Four-layer eval sets** — corpus (authored golden questions), golden (execution-verified answer hashes), adversarial (must-reject negatives), mutation (paraphrase stress test) — all seeded and regenerable
- **Per-layer metrics** — `sqlgate regression` reports conversion rate, execution success, answer correctness, false-accepts, and rejection-reason accuracy
- **Honest numbers** — the stub converts 100% of the corpus, but only ~64% of paraphrased mutations; that gap is the whole point of the fine-tuned proposer upgrade path

### 🛠️ LLM-powered, human-approved learning loop
- **Rejection clustering** — rejected questions group by reason, so coverage gaps are visible (`sqlgate clusters`)
- **Pattern suggestions** — the LLM drafts a new pattern for a cluster; a human approves before it enters the library (US-4)
- **Reject vs repair** — optional auto-repair with the LLM, capped attempts, fails safe (US-5)

### 🎓 The upgrade path: fine-tune your own proposer
- **The gate generates its own training data** — every accepted conversion is a verified (question → intent + slots) pair
- **Train on Apple Silicon** — LoRA fine-tune a 3B model with `mlx-lm` (~30–60 min on a MacBook Air)
- **Evaluate through the same gate** — the fine-tuned proposer is measured against the same eval sets, and false-accepts must stay 0

---

## The Gate

| Stage | What it does | Rejects with |
|---|---|---|
| 1. intent_validate | Required slots present, types correct | `SLOT_MISSING`, `PARSE_FAIL`, `UNSAFE_OPERATION` |
| 2. schema_validate | Tables/columns exist, types compatible | `UNKNOWN_TABLE`, `UNKNOWN_COLUMN`, `TYPE_MISMATCH` |
| 3. safety_rules | SELECT-only; LIMIT required on large-table scans | `UNSAFE_OPERATION`, `UNBOUNDED_QUERY` |
| 4. sql_render | Deterministic render from the pattern library | — |
| 5. parser_check | Real SQL grammar (sqlglot), single SELECT | `PARSE_FAIL` |
| 6. execution_oracle | Runs on the read-only DB (row cap + timeout) | `PARSE_FAIL` (internal render bug) |

```
question → [proposer: intent + slots] → [gate stages 1–6] → exact SQL OR rejection
```

---

## Project layout

```
sqlgate/
├── sqlgate/                # gate core (gate, proposer, patterns, schema, oracle, result)
│   └── ui/streamlit_app.py # demo UI
├── data/                   # schema.json + patterns.json (authored, human-reviewed)
├── eval_sets/              # seeded 4-layer eval (corpus/golden/adversarial/mutation)
├── scripts/                # build_db.py, build_eval_sets.py
├── proposer_finetune/      # LoRA proposer training for Apple Silicon (mlx-lm)
└── tests/                  # 50 tests incl. the adversarial false-accept-zero suite
```

---

## Fine-tune your own

The gate turns its own rejections and accepted conversions into a training curriculum:

```bash
cd proposer_finetune
uv run python scripts/build_dataset.py   # gate-validated pairs → train/valid/test
uv run python scripts/train.py --model Qwen/Qwen2.5-3B-Instruct   # mlx-lm LoRA, ~30–60 min
uv run python scripts/evaluate.py --adapter adapters/             # same gate, same eval sets
```

See [`proposer_finetune/README.md`](proposer_finetune/README.md) for the full guide.

---

## Built with

- **Python 3.11+** — gate core, typer CLI
- **SQLite** — real embedded database, engine-level `mode=ro`
- **sqlglot** — real SQL grammar parsing
- **Streamlit** — web dashboard
- **DeepSeek** — optional LLM proposer mode (capped in the public demo)

---

## Project Status

**v0.1.0** — the full deterministic gate: six stages, pluggable proposers, execution-verified correctness, committed adversarial eval with zero false-accepts, and the fine-tuned proposer upgrade path. See [Versions](#versions).

### Roadmap

- [x] Gate core with six deterministic stages (US-1)
- [x] Demo UI: gate trace, live execution, golden comparison, try-to-break-me (US-2)
- [x] Four-layer eval sets + regression runner (US-3)
- [x] Rejection clustering + human-approved pattern promotion (US-4)
- [x] Reject-vs-repair with capped LLM retries, fails safe (US-5)
- [x] Fine-tuned proposer module: dataset builder, mlx-lm training, GGUF export (US-6)
- [ ] LLM proposer toggle in the public demo (DeepSeek key in Streamlit secrets)
- [ ] Committed fine-tuned comparison table (run evaluate.py on a Mac)
- [ ] CI regression gate (false-accepts must stay 0 on every push)

---

## Versions

| Version | What it is | Release notes |
|---------|-----------|---------------|
| **v0.1.0** | The deterministic gate — NL to safe, executable SQL, with adversarial eval (0 false-accepts), golden execution verification, and the LoRA proposer upgrade path | [GitHub Release](https://github.com/rayyanakmal/sqlgate/releases/tag/v0.1.0) |

**Live demo:** https://sqlgate-vtvw4eerkeztryivq3eueb.streamlit.app/ — ask a question in the Convert tab, watch the gate trace, or try to break it in the adversarial tab. All golden answers are execution-verified against the committed eval sets.

---

## References

- [SPEC.md](SPEC.md) — Full behavior spec with acceptance criteria
- [ARCHITECTURE.md](ARCHITECTURE.md) — Design, interfaces, extension points
- [CHANGELOG.md](CHANGELOG.md) — Version history
- [assets/dashboard.png](assets/dashboard.png) — Demo screenshot (golden questions tab)
- [eval_sets/README.md](eval_sets/README.md) — Eval provenance: what's authored, what's seeded, how to regenerate
- [proposer_finetune/README.md](proposer_finetune/README.md) — Train your own LoRA proposer on Apple Silicon

---

## License

[MIT](LICENSE)

---

<p align="center">
  Built by <a href="https://github.com/rayyanakmal">@rayyanakmal</a>
</p>
