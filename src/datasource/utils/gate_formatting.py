"""Shared formatting helpers for pipeline gate blockers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


_PREFERRED_DETAIL_ORDER = (
    "source_tier",
    "window_evidence",
    "metric_basis",
)


@dataclass(frozen=True)
class GateBlock:
    title: str
    items: List[str]


def _detail_items(details: Any) -> List[str]:
    if not isinstance(details, dict):
        return []

    keys = [
        key
        for key in _PREFERRED_DETAIL_ORDER
        if key in details and details.get(key) not in (None, "")
    ]
    keys.extend(
        key
        for key in sorted(details)
        if key not in keys and details.get(key) not in (None, "")
    )
    return [f"{key}={details[key]}" for key in keys]


def format_quality_issue(issue: Dict[str, Any]) -> str:
    category = str(issue.get("category") or "unknown")
    key = str(issue.get("key") or "unknown")
    reason = str(issue.get("reason") or "unknown")
    parts = [f"{category}.{key}", reason]
    parts.extend(_detail_items(issue.get("details")))
    return " ".join(parts)


def format_gate_blocks(header: str, blocks: Iterable[GateBlock]) -> str:
    lines = [header, ""]
    for block in blocks:
        items = [str(item) for item in block.items if str(item).strip()]
        if not items:
            continue
        lines.append(f"[{block.title}]")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip()
