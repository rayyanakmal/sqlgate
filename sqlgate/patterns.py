"""Pattern library: intent -> SQL template (the deterministic render layer)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlgate.schema import Schema


@dataclass(frozen=True)
class SlotSpec:
    type: str
    required: bool = True
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class Pattern:
    intent: str
    description: str
    slot_spec: dict[str, SlotSpec]
    sql_template: str
    render_rules: dict[str, str]

    def slot_names(self) -> set[str]:
        return set(self.slot_spec)


class PatternLibrary:
    def __init__(self, patterns: dict[str, Pattern]) -> None:
        self.patterns = patterns

    @classmethod
    def load(cls, path: str | Path) -> PatternLibrary:
        raw = json.loads(Path(path).read_text())
        patterns: dict[str, Pattern] = {}
        for p in raw["patterns"]:
            spec = {
                name: SlotSpec(
                    type=s["type"],
                    required=s.get("required", True),
                    values=tuple(s.get("values", [])),
                )
                for name, s in p["slot_spec"].items()
            }
            patterns[p["intent"]] = Pattern(
                intent=p["intent"],
                description=p["description"],
                slot_spec=spec,
                sql_template=p["sql_template"],
                render_rules=p.get("render_rules", {}),
            )
        return cls(patterns)

    def get(self, intent: str) -> Pattern | None:
        return self.patterns.get(intent)

    def render(self, intent: str, slots: dict[str, object], schema: Schema) -> str:
        """Render the pattern template deterministically from validated slots.

        Every optional slot absent from `slots` renders as an empty fragment.
        `render_rules` wraps a slot's value (e.g. filters -> ' WHERE {filters}').
        """
        pattern = self.get(intent)
        assert pattern is not None, f"unknown intent: {intent}"
        fragments: dict[str, str] = {}
        for name, spec in pattern.slot_spec.items():
            # an absent column_list renders as '*' (project everything)
            if spec.type == "column_list" and name not in slots:
                fragments[name] = "*"
                continue
            if name not in slots:
                fragments[name] = ""
                continue
            value = render_slot_value(name, slots[name], spec, schema)
            rule = pattern.render_rules.get(name, "{" + name + "}")
            fragments[name] = rule.format(**{name: value})
        return pattern.sql_template.format(**fragments)


def render_slot_value(
    name: str, value: object, spec: SlotSpec, schema: Schema
) -> str:
    """Turn a slot value into its SQL fragment (no prefix wrapping here)."""
    if spec.type == "table":
        return str(value)
    if spec.type == "column":
        return str(value)
    if spec.type == "column_list":
        if value is None:
            return "*"
        cols = value if isinstance(value, list) else [value]
        return ", ".join(str(c) for c in cols)
    if spec.type == "filters":
        entries = value if isinstance(value, list) else []
        parts = []
        for f in entries:  # list of {column, op, value}
            assert isinstance(f, dict)
            col = f["column"]
            op = f["op"]
            val = f["value"]
            if op == "year_eq":
                parts.append(f"strftime('%Y', {col}) = '{val}'")
            else:
                parts.append(f"{col} = '{val}'")
        return " AND ".join(parts)
    if spec.type == "group_by":
        entries = value if isinstance(value, list) else []
        parts = []
        for g in entries:  # list of {column, granularity?}
            assert isinstance(g, dict)
            col = g["column"]
            gran = g.get("granularity")
            if gran == "month":
                parts.append(f"strftime('%Y-%m', {col})")
            elif gran == "year":
                parts.append(f"strftime('%Y', {col})")
            else:
                parts.append(str(col))
        return ", ".join(parts)
    if spec.type == "order_list":
        entries = value if isinstance(value, list) else []
        parts = []
        for o in entries:  # list of {column, dir}
            assert isinstance(o, dict)
            col = o["column"]
            direction = o.get("dir", "asc").upper()
            parts.append(f"{col} {direction}")
        return ", ".join(parts)
    if spec.type == "integer":
        return str(value)
    if spec.type == "enum":
        return str(value).upper()
    return str(value)
