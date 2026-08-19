"""Train the LoRA proposer with mlx_lm.lora (macOS/Apple Silicon only).

Wraps the official mlx-lm LoRA CLI with the repo's config.yaml so a single
command reproduces the documented run. Fuse mode merges the adapter into the
base weights for GGUF export.

Usage:
  python scripts/train.py --model Qwen/Qwen2.5-3B-Instruct
  python scripts/train.py --fuse            # after training: merge adapter
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=CONFIG["model"])
    parser.add_argument("--fuse", action="store_true", help="merge adapter into weights")
    args = parser.parse_args()

    if args.fuse:
        cmd = [
            sys.executable, "-m", "mlx_lm.fuse",
            "--model", args.model,
            "--adapter-path", str(ROOT / "adapters"),
            "--save-path", str(ROOT / "fused_model"),
        ]
    else:
        cmd = [
            sys.executable, "-m", "mlx_lm.lora",
            "--model", args.model,
            "--train",
            "--data", str(DATA),
            "--adapter-path", str(ROOT / "adapters"),
            "--batch-size", str(CONFIG["train_batch_size"]),
            "--num-layers", str(CONFIG["lora_layers"]),
            "--rank", str(CONFIG["lora_rank"]),
            "--alpha", str(CONFIG["lora_alpha"]),
            "--iters", str(CONFIG["iters"]),
            "--learning-rate", str(CONFIG["learning_rate"]),
            "--steps-per-report", str(CONFIG["steps_per_report"]),
            "--steps-per-eval", str(CONFIG["steps_per_eval"]),
            "--val-batches", str(CONFIG["val_batches"]),
            "--seed", str(CONFIG["seed"]),
            "--max-seq-len", str(CONFIG["max_seq_length"]),
        ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
