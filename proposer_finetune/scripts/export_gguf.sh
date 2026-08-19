#!/usr/bin/env bash
# Fuse + export the trained proposer to GGUF for llama.cpp / Ollama (macOS).
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${1:-Qwen/Qwen2.5-3B-Instruct}"
GGUF_DIR="gguf"

echo "== fusing adapter into base weights =="
python scripts/train.py --model "$MODEL" --fuse

echo "== converting to GGUF (Q4_K_M) =="
mkdir -p "$GGUF_DIR"
python -m llama_cpp.convert_hf_to_gguf fused_model \
  --outfile "$GGUF_DIR/sqlgate-proposer-q4.gguf" --outtype q4_k_m

echo "== done: $GGUF_DIR/sqlgate-proposer-q4.gguf =="
echo "Load with: ollama create sqlgate-proposer -f Modelfile  (or llama.cpp directly)"
