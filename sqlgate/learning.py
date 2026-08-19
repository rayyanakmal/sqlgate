"""US-4 pattern suggestions + US-5 reject-vs-repair.

US-4: rejected questions are clustered by rejection reason; for a chosen cluster
the LLM drafts a proposed pattern (intent + slot shape + template SQL); a human
approves before it enters the library; re-running the regression shows coverage lift.
US-5: optional auto-repair mode — on rejection, the LLM gets the rejection detail
and retries (max N attempts); repair success rate is reported against plain rejection.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlgate.gate import Gate
from sqlgate.llm_proposer import Completer, LLMProposer
from sqlgate.schema import Schema

REPAIR_PROMPT = """The proposed intent/slots were rejected by the safety gate:
Question: {question}
Rejection: {reason} — {detail}

Return STRICT JSON only: {{"intent": "<aggregation|count_rows|select|null>", "slots": {{...}}}}
Fix the proposal so it passes validation. If it cannot be fixed safely, return intent null.
"""


@dataclass
class RejectionCluster:
    reason: str
    count: int
    examples: list[str] = field(default_factory=list)


def cluster_rejections(gate: Gate, questions: list[str]) -> list[RejectionCluster]:
    """Cluster rejected questions by rejection reason (AC-4.1)."""
    buckets: dict[str, list[str]] = defaultdict(list)
    for q in questions:
        result = gate.process(q)
        if not result.accepted and result.reason:
            buckets[result.reason].append(q)
    clusters = [
        RejectionCluster(reason=r, count=len(qs), examples=qs[:3])
        for r, qs in sorted(buckets.items(), key=lambda kv: -len(kv[1]))
    ]
    return clusters


def draft_pattern(
    cluster: RejectionCluster, proposer: LLMProposer, schema: Schema
) -> dict[str, Any] | None:
    """US-4.2: LLM drafts a proposed pattern entry for a rejection cluster."""
    if proposer is None:
        return None
    examples = "\n".join(f"- {q}" for q in cluster.examples)
    prompt = (
        "The following questions were all rejected with the same reason:\n"
        f"{examples}\n\n"
        "Propose ONE new query pattern (intent, slot spec, and SQL template) that would "
        "safely cover them. Return STRICT JSON: "
        '{"intent": "...", "description": "...", "slot_spec": {...}, "sql_template": "..."}. '
        "Only use tables/columns in this schema:\n"
        f"{_manifest(schema)}"
    )
    content = proposer.complete(
        "Return STRICT JSON only. Never propose write operations.", prompt
    )
    if content is None:
        return None
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw.get("intent"), str):
        return None
    return raw if isinstance(raw, dict) else None


def approve_pattern(pattern: dict[str, Any], patterns_path: str | Path) -> None:
    """US-4.3: human-approved pattern is appended to the pattern library."""
    path = Path(patterns_path)
    data = json.loads(path.read_text())
    data["patterns"].append(pattern)
    data["version"] = data.get("version", 1) + 1
    path.write_text(json.dumps(data, indent=2) + "\n")


def repair(
    gate: Gate,
    question: str,
    proposer: Completer,
    max_attempts: int = 2,
) -> Any:
    """US-5: on rejection, feed the error back to the LLM and retry."""
    from sqlgate.gate import normalize

    result = gate.process(question)
    if result.accepted:
        return {"repaired": False, "already_accepted": True, "result": result}

    q = normalize(question)
    attempts = 0
    while attempts < max_attempts:
        attempts += 1
        content = proposer.complete(
            "Return STRICT JSON only. Never propose write operations.",
            REPAIR_PROMPT.format(question=q, reason=result.reason, detail=result.detail),
        )
        if content is None:
            break
        try:
            raw = json.loads(content)
        except json.JSONDecodeError:
            break
        intent = raw.get("intent")
        slots = raw.get("slots") if isinstance(raw.get("slots"), dict) else {}
        if intent is None:
            break
        candidate = gate.process_with_proposal(question, intent=str(intent), slots=slots)
        if candidate.accepted:
            return {"repaired": True, "attempts": attempts, "result": candidate}
        result = candidate
    return {"repaired": False, "attempts": attempts, "result": result}


def _llm_json(proposer: Completer, prompt: str) -> dict[str, Any] | None:
    """One strict-JSON chat call (used by draft_pattern and repair)."""
    return _llm_chat(proposer, prompt)


def _llm_chat(proposer: Completer, prompt: str) -> dict[str, Any] | None:
    import httpx

    api_key = getattr(proposer, "api_key", "")
    model = getattr(proposer, "model", "deepseek-chat")
    if not api_key:
        return None
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Return STRICT JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                return None
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _manifest(schema: Schema) -> str:
    lines = []
    for name, table in schema.tables.items():
        cols = ", ".join(f"{c.name}:{c.type}" for c in table.columns)
        lines.append(f"- {name} ({cols})")
    return "\n".join(lines)


def reason_distribution(gate: Gate, questions: list[str]) -> Counter[str]:
    """Count rejection reasons across a question set (for the comparison screen)."""
    counts: Counter[str] = Counter()
    for q in questions:
        result = gate.process(q)
        if not result.accepted:
            counts[result.reason or "UNKNOWN"] += 1
    return counts
