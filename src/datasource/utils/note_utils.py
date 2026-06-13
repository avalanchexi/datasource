"""Shared note append helpers with intentionally distinct semantics."""

from __future__ import annotations

from typing import Any, Dict, Optional


def append_note_text(note: Optional[str], extra: Optional[str]) -> Optional[str]:
    base = (note or "").strip()
    tail = (extra or "").strip()
    if not tail:
        return base or None
    if not base:
        return tail
    if tail in base:
        return base
    return f"{base} {tail}".strip()


def append_note_once(note: str, addition: str) -> str:
    if not addition:
        return note
    if addition in note:
        return note
    if note:
        return f"{note}；{addition}"
    return addition


def append_note_to_entry(entry: Dict[str, Any], message: str) -> None:
    if not message:
        return
    note = entry.get("note") or ""
    if note:
        note += "；"
    note += message
    entry["note"] = note
