"""Execution oracle: run accepted SQL against the read-only embedded SQLite DB.

Read-only at the ENGINE level (URI mode=ro), not by policy: writes are
impossible even if a query tries. Row cap + timeout protect the demo from
runaway queries.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlgate.result import ExecutionResult


class Oracle:
    def __init__(self, db_path: str | Path, max_rows: int, timeout_seconds: int) -> None:
        self.db_path = Path(db_path)
        self.max_rows = max_rows
        self.timeout_seconds = timeout_seconds

    def execute(self, sql: str) -> ExecutionResult:
        """Run one SELECT against the read-only DB. Never raises for SQL errors."""
        uri = f"file:{self.db_path}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=self.timeout_seconds)
            try:
                conn.execute("PRAGMA query_only=ON")
                cur = conn.execute(sql)
                cols = [d[0] for d in cur.description or []]
                rows = cur.fetchmany(self.max_rows + 1)
                truncated = len(rows) > self.max_rows
                return ExecutionResult(
                    ok=True,
                    columns=cols,
                    rows=rows[: self.max_rows],
                    row_count=len(rows[: self.max_rows]),
                    error="result truncated" if truncated else None,
                )
            finally:
                conn.close()
        except sqlite3.Error as e:
            return ExecutionResult(ok=False, error=str(e))
