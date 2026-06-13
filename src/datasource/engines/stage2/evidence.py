"""Evidence scoring and source-url helpers for Stage2."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from datasource.engines.stage2.snippet_filters import (
    _score_stats,
    _snippet_blob,
    _snippets_have_issuer,
    _snippets_have_expected_period,
)


def _pattern_hits(value: str, patterns: Optional[List[str]]) -> List[str]:
    text = str(value or "").lower()
    hits: List[str] = []
    for pattern in patterns or []:
        needle = str(pattern or "").strip()
        if needle and needle.lower() in text:
            hits.append(needle)
    return hits


def _usage_evidence_score(snippet: Dict[str, Any], keywords: Optional[List[str]]) -> int:  # noqa: E501
    blob = _snippet_blob(snippet)
    return sum(1 for keyword in keywords or [] if str(keyword or "").strip().lower() in blob)  # noqa: E501


def _value_evidence_score(snippet: Dict[str, Any], task: Dict[str, Any]) -> int:  # noqa: E501
    blob = _snippet_blob(snippet).lower()
    if not blob:
        return 0
    non_value_hits = sum(
        1
        for token in (
            "methodology",
            "calculation",
            "weights",
            "rebalance",
            "contract specs",
            "contract specifications",
            "rulebook",
            "target weights",
            "annual rebalance",
            "contract unit",
            "minimum price fluctuation",
            "fact card",
        )
        if token in blob
    )
    if non_value_hits >= 2:
        return 0
    unit = str(task.get("unit") or "").lower()
    indicator = str(task.get("indicator_key") or "").lower()
    numeric_hits = len(re.findall(r"(?<!\d)(?:\d{1,4}(?:,\d{3})*|\d+)(?:\.\d+)?(?!\d)", blob))  # noqa: E501
    if numeric_hits == 0:
        return 0
    score = min(numeric_hits, 3)
    if unit and unit.replace("$", "usd") in blob.replace("$", "usd"):
        score += 2
    if any(token in blob for token in ("price", "level", "last", "settle", "settlement", "收盘", "结算", "点位", "报价")):  # noqa: E501
        score += 2
    if non_value_hits:
        score -= max(4, non_value_hits * 3)
    if indicator and indicator in blob:
        score += 1
    return max(0, score)


def _final_snippet_diagnostics(task: Dict[str, Any], snippets: List[Dict[str, Any]]) -> Dict[str, Any]:  # noqa: E501
    good_url_patterns = task.get("good_url_patterns") or []
    bad_url_patterns = task.get("bad_url_patterns") or []
    evidence_keywords = task.get("evidence_keywords") or []
    usage_evidence_score = 0
    value_evidence_score = 0
    good_url_hit_count = 0
    bad_url_hit_count = 0
    for snippet in snippets:
        url_blob = f"{snippet.get('url') or ''} {_snippet_blob(snippet)}"
        if _pattern_hits(url_blob, good_url_patterns):
            good_url_hit_count += 1
        if _pattern_hits(url_blob, bad_url_patterns):
            bad_url_hit_count += 1
        usage_evidence_score += _usage_evidence_score(snippet, evidence_keywords)  # noqa: E501
        value_evidence_score += _value_evidence_score(snippet, task)
    return {
        "score_stats": _score_stats(snippets),
        "trusted_count": len(snippets),
        "usable_count": len(snippets),
        "issuer_hit": _snippets_have_issuer(
            snippets,
            issuer_hint=task.get("issuer"),
            issuer_aliases=task.get("issuer_aliases"),
        ),
        "period_hit": _snippets_have_expected_period(snippets, task.get("expected_period_tokens")),  # noqa: E501
        "usage_evidence_score": usage_evidence_score,
        "value_evidence_score": value_evidence_score,
        "good_url_hit_count": good_url_hit_count,
        "bad_url_hit_count": bad_url_hit_count,
    }


def _selected_reason_from_diagnostics(
    diagnostics: Dict[str, Any],
    unusable_reason: Optional[str] = None,
) -> str:
    score_stats = diagnostics.get("score_stats") or {}
    return (
        f"trusted={diagnostics.get('trusted_count', 0)} usable={diagnostics.get('usable_count', 0)} "  # noqa: E501
        f"issuer_hit={diagnostics.get('issuer_hit', False)} period_hit={diagnostics.get('period_hit', False)} "  # noqa: E501
        f"usage_evidence={diagnostics.get('usage_evidence_score', 0)} "
        f"value_evidence={diagnostics.get('value_evidence_score', 0)} "
        f"good_url={diagnostics.get('good_url_hit_count', 0)} "
        f"bad_url={diagnostics.get('bad_url_hit_count', 0)} "
        f"score_max={score_stats.get('score_max')}"
        + (f" reason={unusable_reason}" if unusable_reason else "")
    )


def _first_snippet_url(snippets: Optional[List[Dict[str, Any]]]) -> Optional[str]:  # noqa: E501
    for snippet in snippets or []:
        url = snippet.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _normalize_url_for_evidence(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def _snippets_for_source_url(
    snippets: Optional[List[Dict[str, Any]]],
    source_url: Any,
) -> List[Dict[str, Any]]:
    target = _normalize_url_for_evidence(source_url)
    if not target:
        return []
    return [
        snippet
        for snippet in (snippets or [])
        if isinstance(snippet, dict)
        and _normalize_url_for_evidence(snippet.get("url")) == target
    ]


def _snippet_text(snippet: Dict[str, Any]) -> str:
    return " ".join(
        str(snippet.get(field) or "")
        for field in ("title", "snippet", "content", "raw_content")
    )


def _snippet_contains_number(snippet: Dict[str, Any], value: Optional[float]) -> bool:  # noqa: E501
    if value is None:
        return False
    text = _snippet_text(snippet)
    for match in re.finditer(
        r"([+-]?\d[\d,]*(?:\.\d+)?)\s*(亿港元|亿元|亿|billion|bn)",
        text,
        flags=re.IGNORECASE,
    ):
        try:
            candidate = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if abs(candidate - value) <= max(1e-6, abs(value) * 1e-9):
            return True
    return False


def _resolve_field_retry_evidence_source(
    field_extraction: Dict[str, Any],
    snippets: Optional[List[Dict[str, Any]]],
    value: Optional[float],
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    candidates = [snip for snip in (snippets or []) if isinstance(snip, dict)]
    if not candidates:
        source_url = field_extraction.get("source_url")
        return (str(source_url).strip() if source_url else None), []

    source_url_raw = field_extraction.get("source_url")
    source_url = str(source_url_raw).strip() if isinstance(source_url_raw, str) else ""  # noqa: E501
    source_snippets = [
        snip for snip in candidates if str(snip.get("url") or "").strip() == source_url  # noqa: E501
    ]
    source_value_snippets = [
        snip for snip in source_snippets if _snippet_contains_number(snip, value)  # noqa: E501
    ]
    if source_value_snippets:
        return source_url, source_value_snippets

    value_snippets = [snip for snip in candidates if _snippet_contains_number(snip, value)]  # noqa: E501
    if value_snippets:
        value_url = _first_snippet_url(value_snippets)
        same_url_value_snippets = [
            snip for snip in value_snippets if str(snip.get("url") or "").strip() == value_url  # noqa: E501
        ]
        return value_url, same_url_value_snippets or value_snippets

    if source_snippets:
        return source_url, source_snippets
    first_url = _first_snippet_url(candidates)
    return first_url, candidates[:1]


def _field_retry_window_evidence(
    field_scope: str,
    indicator_key: str,
    field_extraction: Dict[str, Any],
    snippets: Optional[List[Dict[str, Any]]],
    metric_basis: str,
    value: Optional[float],
) -> str:
    if not any(_snippet_contains_number(snip, value) for snip in (snippets or [])):  # noqa: E501
        return "unknown"

    explicit = str(field_extraction.get("window_evidence") or "").strip().lower()  # noqa: E501
    if explicit in {"direct_window", "direct_daily_series", "direct_balance_delta"}:  # noqa: E501
        return explicit

    text = " ".join(_snippet_text(s) for s in (snippets or [])).lower()
    if any(token in text for token in ("未披露", "未显示", "没有披露", "无法披露")):
        return "unknown"

    if str(indicator_key).lower() == "margin" and str(metric_basis).lower() == "balance_delta":  # noqa: E501
        if any(token in text for token in ("余额", "balance", "融资融券")):
            return "direct_balance_delta"
        return "unknown"

    field_tokens = {
        "recent_5d": ("近5日", "5日", "5-day", "5 day"),
        "total_120d": ("近120日", "120日", "120-day", "120 day"),
    }
    has_field_token = any(token in text for token in field_tokens.get(field_scope, ()))  # noqa: E501
    has_flow_token = any(
        token in text for token in ("净流入", "净流出", "资金流向", "净申购", "净赎回", "累计", "合计")  # noqa: E501
    )
    if has_field_token and has_flow_token:
        return "direct_window"
    return "unknown"


def _source_label_for_task(
    task: Dict[str, Any],
    source_url: Optional[str],
    extraction_note: Optional[Any] = None,
) -> str:
    backend = str(task.get("search_backend") or "tavily").lower()
    extraction_backend = str(task.get("extraction_backend") or "").lower()
    note = str(extraction_note or "").lower()
    is_regex_note = (
        note.startswith("regex_only")
        or note.startswith("regex_fallback")
        or " regex_fallback" in note
    )
    is_regex_extraction = extraction_backend == "regex" or is_regex_note
    if backend == "structured":
        return "structured"
    if backend == "exa":
        if is_regex_extraction:
            return "exa_regex"
        return "exa+deepseek" if source_url else "exa_regex"
    if is_regex_extraction:
        return "tavily_regex"
    return "tavily+deepseek" if source_url else "tavily_regex"
