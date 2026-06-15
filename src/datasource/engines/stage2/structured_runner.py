"""Structured provider stats and fallback helpers for Stage2."""
from __future__ import annotations

from typing import Any, Dict, Optional


def _structured_stats(stats: Dict[str, Any]) -> Dict[str, Any]:
    structured = stats.setdefault(
        "structured_provider",
        {
            "attempt": 0,
            "success": 0,
            "fallback": 0,
            "by_key": {},
            "error_breakdown": {},
            "latency_ms": [],
            "latency_ms_by_provider": {},
        },
    )
    structured.setdefault("attempt", 0)
    structured.setdefault("success", 0)
    structured.setdefault("fallback", 0)
    structured.setdefault("by_key", {})
    structured.setdefault("error_breakdown", {})
    structured.setdefault("latency_ms", [])
    structured.setdefault("latency_ms_by_provider", {})
    return structured


def _structured_key_stats(stats: Dict[str, Any], indicator_key: str) -> Dict[str, Any]:  # noqa: E501
    structured = _structured_stats(stats)
    by_key = structured.setdefault("by_key", {})
    return by_key.setdefault(indicator_key, {"attempt": 0, "success": 0, "fallback": 0})  # noqa: E501


def _record_structured_attempt(stats: Dict[str, Any], indicator_key: str) -> None:  # noqa: E501
    structured = _structured_stats(stats)
    structured["attempt"] = structured.get("attempt", 0) + 1
    key_stats = _structured_key_stats(stats, indicator_key)
    key_stats["attempt"] = key_stats.get("attempt", 0) + 1
    stats["structured_attempt"] = stats.get("structured_attempt", 0) + 1


def _record_structured_latency_by_provider(
    structured: Dict[str, Any],
    provider_name: Optional[str],
    latency_ms: Optional[int],
) -> None:
    if latency_ms is None:
        return
    provider_key = str(provider_name or "unknown")
    by_provider = structured.setdefault("latency_ms_by_provider", {})
    if isinstance(by_provider, dict):
        by_provider.setdefault(provider_key, []).append(latency_ms)


def _record_structured_success(
    stats: Dict[str, Any],
    indicator_key: str,
    latency_ms: int,
    provider_name: Optional[str] = None,
) -> None:
    structured = _structured_stats(stats)
    structured["success"] = structured.get("success", 0) + 1
    structured.setdefault("latency_ms", []).append(latency_ms)
    _record_structured_latency_by_provider(structured, provider_name, latency_ms)  # noqa: E501
    key_stats = _structured_key_stats(stats, indicator_key)
    key_stats["success"] = key_stats.get("success", 0) + 1
    stats["structured_success"] = stats.get("structured_success", 0) + 1


def _record_structured_fallback(
    stats: Dict[str, Any],
    indicator_key: str,
    reason: str,
    latency_ms: Optional[int] = None,
    provider_name: Optional[str] = None,
) -> None:
    structured = _structured_stats(stats)
    structured["fallback"] = structured.get("fallback", 0) + 1
    if latency_ms is not None:
        structured.setdefault("latency_ms", []).append(latency_ms)
    _record_structured_latency_by_provider(structured, provider_name, latency_ms)  # noqa: E501
    key_stats = _structured_key_stats(stats, indicator_key)
    key_stats["fallback"] = key_stats.get("fallback", 0) + 1
    key_stats["last_fallback_reason"] = reason
    breakdown = structured.setdefault("error_breakdown", {})
    breakdown[reason] = breakdown.get(reason, 0) + 1
    stats["structured_fallback"] = stats.get("structured_fallback", 0) + 1


def _mark_structured_fallback_on_task(
    task: Dict[str, Any],
    *,
    reason: str,
    latency_ms: int,
    diagnostics: Optional[Dict[str, Any]] = None,
    provider_name: Optional[Any] = None,
) -> None:
    task["structured_provider_attempted"] = True
    task["structured_provider_fallback_reason"] = reason
    task["structured_provider_latency_ms"] = latency_ms
    task["structured_provider_diagnostics"] = diagnostics or {}
    if provider_name:
        task["structured_provider_name"] = provider_name
