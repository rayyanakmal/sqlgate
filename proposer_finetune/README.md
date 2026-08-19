# Fine-tuned proposer module (US-6)

Train a small LoRA adapter that maps a natural-language question -> intent + slots,
then plug it into the SAME gate as the stub and the DeepSeek LLM. The gate never
changes; only the proposer does (SPEC AC-1.5).

**Why LoRA, why a small model:** the proposer only extracts meaning (intent + slots).
It never renders SQL — the deterministic gate does that. So a 3B model fine-tuned on
a few hundred examples is enough; the data comes from the gate itself (the gate is
the label oracle: every accepted conversion is a verified (question -> proposal) pair).

**Who can run this:** macOS with Apple Silicon (M1/M2/M3/M4), 24GB unified memory is
plenty for 3B. The dataset builder also runs anywhere (pure Python + the gate).

## 0. Prerequisites

- macOS (Apple Silicon)
- Python 3.11+ and `uv` (https://docs.astral.sh/uv/)
- The SQLGate repo cloned

## 1. Setup

```bash
cd sqlgate/proposer_finetune
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

## 2. Build the dataset (runs anywhere — the gate is the label oracle)

```bash
uv run python scripts/build_dataset.py
```

This walks the golden + mutation eval sets through the gate. Every ACCEPTED question
becomes a training example: `{"question": "...", "intent": "...", "slots": {...}}`
(that's the verified proposal). Rejected questions are excluded (the gate said no).
Output: `data/train.jsonl`, `data/valid.jsonl`, `data/test.jsonl` (seeded split,
deterministic). You can add more questions to `data/extra_questions.txt` to grow it.

## 3. Train (macOS only)

```bash
uv run python scripts/train.py --model Qwen/Qwen2.5-3B-Instruct
```

Wraps `mlx_lm.lora` with the config in `config.yaml` (rank 8, alpha 16, 3 epochs,
attention layers). Trained adapter lands in `adapters/`. On a MacBook Air this is
~30-60 minutes for a few hundred examples.

## 4. Evaluate (macOS only)

```bash
uv run python scripts/evaluate.py --adapter adapters/
```

Runs the fine-tuned proposer through the SAME gate and eval sets as the stub, and
prints the comparison table (conversion / execution success / false-accepts /
reason accuracy). False-accepts MUST stay 0 for every proposer — if the fine-tuned
proposer ever makes the gate accept an adversarial line, the gate is doing its job
(rejecting at the safety/schema stages), and the table shows it honestly.

## 5. Export to GGUF (optional — run the model on a Pi via llama.cpp/Ollama)

```bash
uv run python scripts/train.py --fuse          # merge adapter into weights
uv run python scripts/export_gguf.sh           # -> gguf/ Q4_K_M
```

## Files

| File | Purpose |
|---|---|
| `scripts/build_dataset.py` | gate-validated question/proposal pairs -> train/valid/test |
| `scripts/train.py` | mlx_lm.lora wrapper (config.yaml) |
| `scripts/evaluate.py` | fine-tuned proposer through the gate, comparison table |
| `scripts/export_gguf.sh` | fuse + GGUF export for llama.cpp/Ollama |
| `config.yaml` | training hyperparameters |
| `data/extra_questions.txt` | optional extra questions to grow the dataset |

## Honest limits

- Training runs on Apple Silicon only (mlx). The Pi can *run* the exported GGUF
  but not train it.
- The dataset is small by design (the gate + golden pairs). Small data + LoRA +
  meaning-extraction = the point, not a limitation.
- The committed comparison table in the demo is produced by this evaluate script on
  your Mac, then committed (AC-6.5) — the model itself is never served publicly.
