"""Schema: the SQL registry. Loads data/schema.json and answers validation questions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

NUMERIC_TYPES = {"integer", "real", "float", "numeric", "decimal"}


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    key: bool = False
    fk: str | None = None


@dataclass(frozen=True)
class Table:
    name: str
    description: str
    columns: tuple[Column, ...]

    def column(self, name: str) -> Column | None:
        for c in self.columns:
            if c.name == name:
                return c
        return None


class Schema:
    def __init__(
        self,
        tables: dict[str, Table],
        large_tables: set[str],
        max_rows: int,
        timeout_seconds: int,
    ) -> None:
        self.tables = tables
        self.large_tables = large_tables
        self.max_rows = max_rows
        self.timeout_seconds = timeout_seconds

    @classmethod
    def load(cls, path: str | Path) -> Schema:
        raw = json.loads(Path(path).read_text())
        tables: dict[str, Table] = {}
        for name, t in raw["tables"].items():
            cols = tuple(
                Column(
                    name=c["name"],
                    type=c["type"],
                    key=c.get("key", False),
                    fk=c.get("fk"),
                )
                for c in t["columns"]
            )
            tables[name] = Table(name=name, description=t["description"], columns=cols)
        return cls(
            tables=tables,
            large_tables=set(raw.get("large_tables", [])),
            max_rows=int(raw["execution_limits"]["max_rows"]),
            timeout_seconds=int(raw["execution_limits"]["timeout_seconds"]),
        )

    def table(self, name: str) -> Table | None:
        return self.tables.get(name)

    def column(self, table: str, column: str) -> Column | None:
        t = self.table(table)
        return t.column(column) if t else None

    def column_type(self, table: str, column: str) -> str | None:
        c = self.column(table, column)
        return c.type if c else None

    def is_numeric(self, table: str, column: str) -> bool:
        t = self.column_type(table, column)
        return t is not None and t in NUMERIC_TYPES

    def find_table_for_column(self, column: str) -> str | None:
        """The unique table owning a column, or None if ambiguous/unknown."""
        owners = [name for name, t in self.tables.items() if t.column(column) is not None]
        return owners[0] if len(owners) == 1 else None
