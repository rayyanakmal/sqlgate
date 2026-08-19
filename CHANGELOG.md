# Changelog

## 0.1.0 (2026-08-19)

Initial release. The deterministic gate, demo-able, with the internship pattern applied to a public SQL machine.

### Added

- **The gate (US-1):** question -> proposer (intent + slots) -> six deterministic stages (intent_validate, schema_validate, safety_rules, sql_render, parser_check, execution_oracle). Output is exactly one of: an executed-verified SQL query, or a structured rejection with a reason from the fixed taxonomy (UNKNOWN_TABLE, UNKNOWN_COLUMN, TYPE_MISMATCH, UNSAFE_OPERATION, UNBOUNDED_QUERY, SLOT_MISSING, CROSS_INTENT_OVERRIDE, PARSE_FAIL).
- **Stub proposer:** deterministic keyword-based offline mode. No API key, demo always runs (SPEC AC-1.5).
- **LLM proposer:** DeepSeek-backed, same gate contract, strict-JSON output, defensive parsing.
- **Read-only execution oracle:** SQLite opens `mode=ro` at the engine level, `PRAGMA query_only`, row cap + timeout (SPEC AC-1.2).
- **Cross-intent guard:** a proposer proposal contradicting the deterministic owner-intent classification is blocked (internship invariant #4).
- **Demo UI (US-2):** gate trace table, live query execution, golden-question match/mismatch badges (execution-verified result hashes), and try-to-break-me adversarial examples.
- **Eval sets + regression (US-3):** seeded, regenerable four-layer eval (corpus / golden / adversarial / mutation, 66 records); `sqlgate regression` reports per-layer metrics; false-accepts = 0 is enforced and reported as a release blocker if violated.
- **Pattern suggestions (US-4):** rejection clustering by reason, LLM-drafted pattern proposals, human-approved promotion into the pattern library.
- **Reject vs repair (US-5):** optional LLM auto-repair loop (max N attempts), repair success rate vs plain rejection, fails safe (never silently accepts).
- **Fine-tuned proposer module (US-6):** `proposer_finetune/` — gate-as-label-oracle dataset builder (verified: 27 examples), mlx-lm LoRA training wrapper for Apple Silicon, evaluate-vs-stub comparison, GGUF export for llama.cpp/Pi.

### Verified

- 50/50 tests green; ruff clean; mypy strict clean (12 source files).
- Regression (stub): corpus 100% conversion, golden 100% answer correctness, adversarial 0 false-accepts / 100% reason accuracy, mutation 63.6% conversion (honest — paraphrases are the hard case).
- UI smoke: Streamlit serves HTTP 200, health endpoint ok.
