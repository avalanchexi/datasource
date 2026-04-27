"""Shared numeric coercion helpers with explicit pipeline semantics."""

from __future__ import annotations

from typing import Any, Optional


def to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def is_legacy_713_placeholder(value: Any) -> bool:
    numeric = to_float(value)
    if numeric is None:
        return False
    return abs(numeric - 7.13) < 1e-6


def is_stage2_number_placeholder(value: Any) -> bool:
    """Stage2/Stage2.5 numeric gate: empty, non-numeric, or zero are invalid."""
    if value in (None, "", "N/A"):
        return True
    numeric = to_float(value)
    if numeric is None:
        return True
    return abs(numeric) < 1e-9


def is_stage2_task_placeholder(value: Any) -> bool:
    """Stage2 task planner gate: only None, zero, and legacy 7.13 trigger tasks."""
    if value in (None, 0, 0.0):
        return True
    return is_legacy_713_placeholder(value)
