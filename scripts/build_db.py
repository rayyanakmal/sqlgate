"""Build the seeded, regenerable sample database (data/sample.db).

Thin wrapper around sqlgate.db (single source of truth). The DB is generated,
gitignored, and rebuilt automatically at Gate construction when missing.

Run: uv run python scripts/build_db.py
"""

from __future__ import annotations

from pathlib import Path

from sqlgate.db import ensure_sample_db

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "sample.db"


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    path = ensure_sample_db(DB_PATH)
    print(f"built {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
