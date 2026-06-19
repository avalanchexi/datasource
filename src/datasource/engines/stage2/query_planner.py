"""Query planning helpers for Stage2."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from datasource.engines.stage2.evidence import (
    _pattern_hits,
    _selected_reason_from_diagnostics,
    _usage_evidence_score,
    _value_evidence_score,
)
from datasource.engines.stage2.snippet_filters import (
    _filter_by_domain,
    _filter_by_keyword_rules,
    _prefer_fresh_snippets,
    _prefer_latest_report_snippets,
    _score_stats,
    _snippet_blob,
    _snippets_have_expected_period,
    _snippets_have_issuer,
    _strict_indicator_tokens,
)


def _exa_search_type(indicator_key: str) -> Optional[str]:
    keyword_keys = {
        "GC=F",
        "CL=F",
        "BZ=F",
        "HG=F",
        "BCOM",
        "GSG",
        "USDCNY",
        "USDCNH",
        "DXY",
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "US10Y",
        "CN10Y",
        "CN10Y_CDB",
        "000001",
        "000016",
        "000300",
        "399001",
        "399006",
    }
    if indicator_key in keyword_keys:
        return "keyword"
    return None


def _start_date_from_max_age(max_age_days: Optional[int]) -> Optional[str]:
    if not max_age_days:
        return None
    dt = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    return dt.strftime("%Y-%m-%d")


def _candidate_query_quality(
    task: Dict[str, Any],
    candidate: Dict[str, Any],
    snippets: List[Dict[str, Any]],
) -> Dict[str, Any]:
    preferred_domains = candidate.get("preferred_domains") or task.get("preferred_domains")  # noqa: E501
    required_keywords = list(task.get("required_keywords") or [])
    required_keywords.extend(candidate.get("required_keywords") or [])
    exclude_keywords = list(task.get("exclude_keywords") or [])
    exclude_keywords.extend(candidate.get("exclude_keywords") or [])
    strict_required_keywords = bool(
        candidate.get("strict_required_keywords", task.get("strict_required_keywords", False))  # noqa: E501
    )
    strict_issuer_match = bool(candidate.get("strict_issuer_match", task.get("strict_issuer_match", False)))  # noqa: E501

    trusted = _filter_by_domain(
        snippets,
        preferred_domains,
        indicator_key=task.get("indicator_key"),
        fallback_to_original=False,
    )
    trusted_or_raw = trusted or list(snippets)
    fresh = _prefer_fresh_snippets(trusted_or_raw, task.get("max_age_days"))
    latest = _prefer_latest_report_snippets(fresh, task.get("indicator_key"))
    keyword_filtered = _filter_by_keyword_rules(
        latest,
        required_keywords=required_keywords,
        exclude_keywords=exclude_keywords,
        fallback_to_original=False,
    )
    trusted_count = len(trusted)
    raw_for_checks = keyword_filtered or latest or trusted_or_raw
    issuer_hit = _snippets_have_issuer(
        raw_for_checks,
        issuer_hint=task.get("issuer"),
        issuer_aliases=task.get("issuer_aliases"),
    )
    period_hit = _snippets_have_expected_period(raw_for_checks, task.get("expected_period_tokens"))  # noqa: E501
    unusable_reason: Optional[str] = None
    strict_indicator_tokens = _strict_indicator_tokens(task.get("indicator_key"))  # noqa: E501
    strict_indicator_hit = not strict_indicator_tokens or any(
        token in _snippet_blob(snip) for token in strict_indicator_tokens for snip in raw_for_checks  # noqa: E501
    )
    if strict_required_keywords and ((required_keywords and not keyword_filtered) or not strict_indicator_hit):  # noqa: E501
        unusable_reason = "strict_keyword_miss"
    elif strict_issuer_match and not issuer_hit:
        unusable_reason = "strict_issuer_miss"

    usable = [] if unusable_reason else (keyword_filtered or latest or trusted or list(snippets))  # noqa: E501
    good_url_patterns = candidate.get("good_url_patterns") or task.get("good_url_patterns") or []  # noqa: E501
    bad_url_patterns = candidate.get("bad_url_patterns") or task.get("bad_url_patterns") or []  # noqa: E501
    evidence_keywords = candidate.get("evidence_keywords") or task.get("evidence_keywords") or []  # noqa: E501

    def _score_usable(current: List[Dict[str, Any]]) -> Dict[str, Any]:
        scored: List[Dict[str, Any]] = []
        for snippet in current:
            url_blob = f"{snippet.get('url') or ''} {_snippet_blob(snippet)}"
            bad_hits = _pattern_hits(url_blob, bad_url_patterns)
            good_hits = _pattern_hits(url_blob, good_url_patterns)
            evidence_score = _usage_evidence_score(snippet, evidence_keywords)
            value_score = _value_evidence_score(snippet, task)
            scored.append(
                {
                    "snippet": snippet,
                    "bad_hits": bad_hits,
                    "good_hits": good_hits,
                    "evidence_score": evidence_score,
                    "value_score": value_score,
                }
            )
        return {
            "scored": scored,
            "bad_url_hit_count": sum(1 for item in scored if item["bad_hits"]),
            "good_url_hit_count": sum(1 for item in scored if item["good_hits"]),  # noqa: E501
            "usage_evidence_score": sum(int(item["evidence_score"]) for item in scored),  # noqa: E501
            "value_evidence_score": sum(int(item["value_score"]) for item in scored),  # noqa: E501
        }

    usable_scores = _score_usable(usable)
    scored_usable: List[Dict[str, Any]] = usable_scores["scored"]
    original_bad_url_hit_count = int(usable_scores["bad_url_hit_count"])

    if any(item["bad_hits"] for item in scored_usable) and any(not item["bad_hits"] for item in scored_usable):  # noqa: E501
        kept = [item for item in scored_usable if not item["bad_hits"]]
        usable = [item["snippet"] for item in kept]
        usable_scores = _score_usable(usable)
        scored_usable = usable_scores["scored"]

    indicator_key_normalized = str(task.get("indicator_key") or "")
    if (
        indicator_key_normalized.lower() == "etf"
        and scored_usable
        and all(item["bad_hits"] for item in scored_usable)
    ):
        unusable_reason = "search_result_scope_mismatch"
        usable = []
        usable_scores = _score_usable(usable)
        scored_usable = usable_scores["scored"]
    elif (
        indicator_key_normalized == "BCOM"
        and scored_usable
        and all(item["bad_hits"] for item in scored_usable)
    ):
        unusable_reason = "search_result_scope_mismatch"
        usable = []
        usable_scores = _score_usable(usable)
        scored_usable = usable_scores["scored"]
    elif (
        indicator_key_normalized.lower() in {"rrr", "reserve_ratio"}
        and scored_usable
        and all(item["bad_hits"] for item in scored_usable)
    ):
        unusable_reason = "search_result_scope_mismatch"
        usable = []
        usable_scores = _score_usable(usable)
        scored_usable = usable_scores["scored"]

    if usable and not unusable_reason:
        issuer_hit = _snippets_have_issuer(
            usable,
            issuer_hint=task.get("issuer"),
            issuer_aliases=task.get("issuer_aliases"),
        )
        period_hit = _snippets_have_expected_period(usable, task.get("expected_period_tokens"))  # noqa: E501
        if strict_issuer_match and not issuer_hit:
            unusable_reason = "strict_issuer_miss"
            usable = []
            usable_scores = _score_usable(usable)

    requires_value_evidence = bool(task.get("required_output_fields") or task.get("evidence_keywords"))  # noqa: E501
    high_score = [s for s in usable if s.get("score") is None or s.get("score", 0) >= 0.5]  # noqa: E501
    if high_score:
        high_score_scores = _score_usable(high_score)
        high_score_value = int(high_score_scores["value_evidence_score"])
        current_value = int(usable_scores["value_evidence_score"])
        if not requires_value_evidence or high_score_value >= current_value or current_value <= 0:  # noqa: E501
            usable = high_score
            usable_scores = high_score_scores
            issuer_hit = _snippets_have_issuer(
                usable,
                issuer_hint=task.get("issuer"),
                issuer_aliases=task.get("issuer_aliases"),
            )
            period_hit = _snippets_have_expected_period(usable, task.get("expected_period_tokens"))  # noqa: E501

    usage_evidence_score = int(usable_scores["usage_evidence_score"])
    value_evidence_score = int(usable_scores["value_evidence_score"])
    good_url_hit_count = int(usable_scores["good_url_hit_count"])
    bad_url_hit_count = max(original_bad_url_hit_count, int(usable_scores["bad_url_hit_count"]))  # noqa: E501

    if usable and not unusable_reason and requires_value_evidence and value_evidence_score <= 0:  # noqa: E501
        unusable_reason = "value_evidence_miss"
        usable = []
        usable_scores = _score_usable(usable)
        usage_evidence_score = int(usable_scores["usage_evidence_score"])
        value_evidence_score = int(usable_scores["value_evidence_score"])
        good_url_hit_count = int(usable_scores["good_url_hit_count"])
        bad_url_hit_count = max(original_bad_url_hit_count, int(usable_scores["bad_url_hit_count"]))  # noqa: E501

    score_stats = _score_stats(usable)
    usable_count = len(usable)
    quality_score = (
        trusted_count * 100.0
        + usable_count * 15.0
        + (25.0 if period_hit else 0.0)
        + (15.0 if issuer_hit else 0.0)
        + ((score_stats.get("score_max") or 0.0) * 10.0)
        + usage_evidence_score * 12.0
        + value_evidence_score * 18.0
        + good_url_hit_count * 25.0
        - bad_url_hit_count * 140.0
    )
    if unusable_reason:
        quality_score = -1.0
    return {
        "snippets": usable,
        "trusted_count": trusted_count,
        "usable_count": usable_count,
        "issuer_hit": issuer_hit,
        "period_hit": period_hit,
        "score_stats": score_stats,
        "quality_score": quality_score,
        "usage_evidence_score": usage_evidence_score,
        "value_evidence_score": value_evidence_score,
        "good_url_hit_count": good_url_hit_count,
        "bad_url_hit_count": bad_url_hit_count,
        "unusable_reason": unusable_reason,
        "selected_reason": _selected_reason_from_diagnostics(
            {
                "score_stats": score_stats,
                "trusted_count": trusted_count,
                "usable_count": usable_count,
                "issuer_hit": issuer_hit,
                "period_hit": period_hit,
                "usage_evidence_score": usage_evidence_score,
                "value_evidence_score": value_evidence_score,
                "good_url_hit_count": good_url_hit_count,
                "bad_url_hit_count": bad_url_hit_count,
            },
            unusable_reason,
        ),
    }


def _dedupe_candidate_queries(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:  # noqa: E501
    seen = set()
    result: List[Dict[str, Any]] = []
    for candidate in candidates:
        query = str(candidate.get("query") or "").strip()
        field_scope = str(candidate.get("field_scope") or "")
        if not query:
            continue
        sig = (query, field_scope)
        if sig in seen:
            continue
        seen.add(sig)
        result.append(candidate)
    return result


def _expand_query_candidates(
    task: Dict[str, Any],
    *,
    directed_query_override: Optional[str] = None,
    field_scopes: Optional[List[str]] = None,
    include_primary: bool = True,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    if directed_query_override:
        candidates.append(
            {
                "query": directed_query_override,
                "family": "directed_retry",
                "field_scope": None,
                "preferred_domains": task.get("preferred_domains") or [],
                "exclude_domains": task.get("exclude_domains") or [],
                "required_keywords": task.get("required_keywords") or [],
                "exclude_keywords": task.get("exclude_keywords") or [],
            }
        )
    if include_primary:
        for family in task.get("query_families") or []:
            for query in family.get("queries") or []:
                candidates.append(
                    {
                        "query": query,
                        "family": family.get("name") or "default",
                        "field_scope": family.get("field_scope"),
                        "preferred_domains": family.get("preferred_domains") or task.get("preferred_domains") or [],  # noqa: E501
                        "exclude_domains": list(task.get("exclude_domains") or [])  # noqa: E501
                        + list(family.get("exclude_domains") or []),
                        "required_keywords": list(task.get("required_keywords") or [])  # noqa: E501
                        + list(family.get("required_keywords") or []),
                        "exclude_keywords": list(task.get("exclude_keywords") or [])  # noqa: E501
                        + list(family.get("exclude_keywords") or []),
                        "time_range": family.get("time_range") or task.get("time_range"),  # noqa: E501
                        "topic": family.get("topic") or task.get("topic"),
                        "max_results": family.get("max_results") or task.get("max_results"),  # noqa: E501
                        "search_depth": family.get("search_depth") or task.get("search_depth"),  # noqa: E501
                        "days": family.get("days") if family.get("days") is not None else task.get("days"),  # noqa: E501
                        "chunks_per_source": family.get("chunks_per_source")
                        if family.get("chunks_per_source") is not None
                        else task.get("chunks_per_source"),
                        "auto_parameters": family.get("auto_parameters")
                        if family.get("auto_parameters") is not None
                        else task.get("auto_parameters"),
                    }
                )
    if include_primary and not candidates:
        primary_query = task.get("query") or task.get("indicator_key")
        if primary_query:
            candidates.append(
                {
                    "query": primary_query,
                    "family": "legacy_primary",
                    "field_scope": None,
                    "preferred_domains": task.get("preferred_domains") or [],
                    "exclude_domains": task.get("exclude_domains") or [],
                    "required_keywords": task.get("required_keywords") or [],
                    "exclude_keywords": task.get("exclude_keywords") or [],
                    "time_range": task.get("time_range"),
                    "topic": task.get("topic"),
                    "max_results": task.get("max_results"),
                    "search_depth": task.get("search_depth"),
                    "days": task.get("days"),
                    "chunks_per_source": task.get("chunks_per_source"),
                    "auto_parameters": task.get("auto_parameters"),
                }
            )
        for query in task.get("queries") or []:
            candidates.append(
                {
                    "query": query,
                    "family": "legacy_alt",
                    "field_scope": None,
                    "preferred_domains": task.get("preferred_domains") or [],
                    "exclude_domains": task.get("exclude_domains") or [],
                    "required_keywords": task.get("required_keywords") or [],
                    "exclude_keywords": task.get("exclude_keywords") or [],
                    "time_range": task.get("time_range"),
                    "topic": task.get("topic"),
                    "max_results": task.get("max_results"),
                    "search_depth": task.get("search_depth"),
                    "days": task.get("days"),
                    "chunks_per_source": task.get("chunks_per_source"),
                    "auto_parameters": task.get("auto_parameters"),
                }
            )
    selected_fields = field_scopes or []
    for field_scope in selected_fields:
        for query in (task.get("field_queries") or {}).get(field_scope, []):
            candidates.append(
                {
                    "query": query,
                    "family": f"field:{field_scope}",
                    "field_scope": field_scope,
                    "preferred_domains": task.get("preferred_domains") or [],
                    "exclude_domains": task.get("exclude_domains") or [],
                    "required_keywords": task.get("required_keywords") or [],
                    "exclude_keywords": task.get("exclude_keywords") or [],
                    "time_range": task.get("time_range"),
                    "topic": task.get("topic"),
                    "max_results": task.get("max_results"),
                    "search_depth": task.get("search_depth"),
                    "days": task.get("days"),
                    "chunks_per_source": task.get("chunks_per_source"),
                    "auto_parameters": task.get("auto_parameters"),
                }
            )
    deduped = _dedupe_candidate_queries(candidates)
    if include_primary and not field_scopes:
        limit_raw = task.get("max_query_candidates")
        try:
            limit = int(limit_raw) if limit_raw is not None else 0
        except (TypeError, ValueError):
            limit = 0
        if limit > 0:
            directed = [item for item in deduped if item.get("family") == "directed_retry"]  # noqa: E501
            primary = [item for item in deduped if item.get("family") != "directed_retry"]  # noqa: E501
            if len(primary) > limit:
                return directed + primary[:limit]
    return deduped


def _build_directed_query(
    task: Dict[str, Any],
    extraction: Dict[str, Any],
    skip_reason: Optional[str],
    extra_reason: Optional[str],
) -> Optional[str]:
    base_query = (task.get("query") or task.get("indicator_key") or "").strip()
    if not base_query:
        return None
    trigger_text = " ".join(
        [
            str(skip_reason or ""),
            str(extra_reason or ""),
            str(extraction.get("manual_reason") or ""),
            str(extraction.get("note") or ""),
        ]
    ).lower()
    if task.get("field_queries"):
        if "recent_5d" in trigger_text or "近5日" in trigger_text:
            values = (task.get("field_queries") or {}).get("recent_5d") or []
            if values:
                return values[0]
        if "total_120d" in trigger_text or "120日" in trigger_text or "累计" in trigger_text:  # noqa: E501
            values = (task.get("field_queries") or {}).get("total_120d") or []
            if values:
                return values[0]
    hint_tokens: List[str] = ["最新", "官方", "数据"]
    unit = (task.get("unit") or "").strip()
    issuer = (task.get("issuer") or "").strip()
    if unit:
        hint_tokens.append(f"单位{unit}")
    if issuer:
        hint_tokens.append(f"发布机构{issuer}")

    indicator = str(task.get("indicator_key") or "").lower()
    if indicator in {"industrial", "industrial_sales", "cpi", "ppi", "pmi", "pmi_new_orders", "gdp"}:  # noqa: E501
        now = datetime.now()
        year = now.year
        month = now.month - 1 if now.month > 1 else 12
        if now.month == 1:
            year -= 1
        hint_tokens.append(f"{year}年{month}月")
        hint_tokens.append("同比")

    if "low_score_all" in trigger_text or "低分" in trigger_text:
        hint_tokens.append("公告")
        hint_tokens.append("统计公报")
    if "单位不匹配" in trigger_text:
        hint_tokens.append("精确单位")
    if "发布机构" in trigger_text:
        hint_tokens.append("发布机构原文")
    expected_tokens = task.get("expected_period_tokens") or []
    if expected_tokens:
        hint_tokens.append(str(expected_tokens[0]))

    directed = f"{base_query} {' '.join(hint_tokens)}".strip()
    return directed if directed != base_query else None


def _should_retry_with_directed_query(
    extraction: Dict[str, Any],
    skip_reason: Optional[str],
    extra_reason: Optional[str],
    *,
    attempt: int,
    max_retries: int,
    directed_retry_done: bool,
) -> bool:
    if directed_retry_done:
        return False
    # 当前循环使用 count(start=1)，最多允许触发一次定向重试
    if attempt > max(1, max_retries):
        return False
    trigger_text = " ".join(
        [
            str(skip_reason or ""),
            str(extra_reason or ""),
            str(extraction.get("manual_reason") or ""),
            str(extraction.get("note") or ""),
        ]
    ).lower()
    triggers = [
        "low_score_all",
        "单位不匹配",
        "缺少发布机构",
        "no_value",
        "deepseek_no_value",
        "no_deepseek_key",
    ]
    return any(t in trigger_text for t in triggers)
