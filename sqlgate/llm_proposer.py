"""LLMProposer: DeepSeek-backed proposer implementing the same contract as the stub.

The gate treats stub and LLM identically (SPEC AC-1.5). The LLM sees the schema
manifest and pattern library in its system prompt; it must return strict JSON
{intent, slots}. Defensive parsing: anything unusable -> intent=None (PARSE_FAIL).
Key comes from DEEPSEEK_API_KEY (env). Never committed.
"""

from __future__ import annotations

import json
import os
from typing import Protocol

import httpx

from sqlgate.proposer import IntentProposal
from sqlgate.schema import Schema

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
TIMEOUT = 30.0

SYSTEM_PROMPT = """You are the proposer half of a safe text-to-SQL system. A deterministic
gate validates everything after you, so you only propose MEANING, never final SQL.

Given a user question and the schema below, return STRICT JSON only:
{"intent": "<one of: aggregation | count_rows | select>", "slots": {...}}

Slot rules:
- aggregation: table (string), metric (column name), aggregate (sum|avg|count|min|max),
  optional group_by ([{"column": ..., "granularity": "month"|"year"|null}]),
  optional filters ([{"column": ..., "op": "=" | "year_eq", "value": ...}]),
  optional order_by ([{"column": ..., "dir": "asc"|"desc"}]), optional limit (int)
- count_rows: table, optional filters (same shape)
- select: table, optional columns (list) or omit for *, optional filters/order_by/limit

Only reference tables and columns that exist in the schema. Never propose write
operations. If the question is not answerable as SQL, return {"intent": null}.

SCHEMA:
{schema}
"""


class Completer(Protocol):
    """Anything that can produce one strict-JSON chat completion."""

    def complete(self, system: str, user: str) -> str | None: ...


class LLMProposer(Completer):
    """DeepSeek-backed proposer. Same protocol as StubProposer."""

    def __init__(self, api_key: str | None = None, model: str = MODEL) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.model = model

    def propose(self, question: str, schema: Schema) -> IntentProposal:
        if not self.api_key:
            return IntentProposal(intent=None, slots={})
        manifest = _schema_manifest(schema)
        content = self.complete(SYSTEM_PROMPT.format(schema=manifest), question)
        if content is None:
            return IntentProposal(intent=None, slots={})
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return IntentProposal(intent=None, slots={})
        intent = data.get("intent")
        slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
        return IntentProposal(intent=intent if isinstance(intent, str) else None, slots=slots)

    def complete(self, system: str, user: str) -> str | None:
        """One strict-JSON chat call. Shared by propose, draft_pattern, and repair."""
        if not self.api_key:
            return None
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.post(
                    API_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return content if isinstance(content, str) else None
        except Exception:  # noqa: BLE001 - any LLM failure degrades to PARSE_FAIL
            return None


def _schema_manifest(schema: Schema) -> str:
    lines = []
    for name, table in schema.tables.items():
        cols = ", ".join(f"{c.name}:{c.type}" for c in table.columns)
        lines.append(f"- {name} ({cols})")
    return "\n".join(lines)
