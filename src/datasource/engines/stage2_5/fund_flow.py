"""Stage2.5 fund flow gate helpers."""
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from datasource.engines.stage2_5.common import (
    _coerce_bool,
    _extract_domain,
    _extract_source_url,
)
from datasource.utils.note_utils import append_note_once as _append_note_once


def _normalize_fund_flow_payload(raw_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: E501
    normalized = dict(payload or {})
    if raw_key == "etf_flow":
        normalized.setdefault('recent_5d', normalized.get('recent_week'))
        normalized.setdefault('note', normalized.get('hot_sectors'))
    if raw_key == "margin_trading":
        normalized.setdefault('total_120d', normalized.get('balance'))
        normalized.setdefault('note', normalized.get('ratio'))
        normalized.setdefault('recent_5d', None)
    return normalized


def _default_fund_flow_metric_basis(key: str, payload: Dict[str, Any]) -> str:
    if payload.get("metric_basis"):
        return str(payload.get("metric_basis"))
    if key in {"northbound", "southbound"}:
        return "net_flow_sum"
    if key == "margin":
        return "balance_delta"
    if key == "etf":
        return "estimated_net_flow" if _coerce_bool(payload.get("is_estimated")) else "net_flow_sum"  # noqa: E501
    return "net_flow_sum"


FUND_FLOW_TIER1_DOMAINS = (
    "hkex.com.hk",
    "sse.com.cn",
    "szse.cn",
)
FUND_FLOW_TIER2_STRUCTURED_PATHS = {
    "data.eastmoney.com": (
        "/hsgt",
        "/etf",
        "/fund",
        "/rzrq",
    ),
    "tushare.pro": ("/document",),
}
FUND_FLOW_TIER3_DOMAINS = (
    "finance.sina.com.cn",
    "sina.com.cn",
    "stcn.com",
    "cs.com.cn",
    "cls.cn",
    "10jqka.com.cn",
)
FUND_FLOW_DIRECT_WINDOW_EVIDENCE = {
    "direct_window",
    "direct_daily_series",
    "direct_balance_delta",
}
FUND_FLOW_WEAK_WINDOW_EVIDENCE = {
    "news_summary",
    "derived",
    "unknown",
}
FUND_FLOW_ESTIMATED_METRIC_BASIS = {
    "news_net_flow",
    "estimated_net_flow",
}


def _normalize_source_tier(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if text in {"tier1", "tier2", "tier3", "unknown"}:
        return text
    return None


def _normalize_window_evidence(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    allowed = FUND_FLOW_DIRECT_WINDOW_EVIDENCE | FUND_FLOW_WEAK_WINDOW_EVIDENCE
    if text in allowed:
        return text
    return None


def _domain_matches(domain: str, suffixes: Any) -> bool:
    return bool(domain) and any(domain == suffix or domain.endswith(f".{suffix}") for suffix in suffixes)  # noqa: E501


def _parse_url_domain_path(value: Optional[str]) -> Tuple[str, str]:
    if not value:
        return "", ""
    text = str(value).strip().strip("<>()[]{}\"'")
    if not text:
        return "", ""
    parsed = urlparse(text)
    if not parsed.hostname and "://" not in text and not text.startswith("//"):
        parsed = urlparse(f"//{text}")
    try:
        parsed.port
    except ValueError:
        return "", ""
    return (parsed.hostname or "").lower().strip(), parsed.path or "/"


def _path_matches_prefix(path: str, prefixes: Any) -> bool:
    normalized = path or "/"
    return any(
        prefix == "/"
        or normalized == prefix
        or normalized.startswith(f"{prefix}/")
        for prefix in prefixes
    )


def _is_fund_flow_tier2_structured_source(url: Optional[str]) -> bool:
    domain, path = _parse_url_domain_path(url)
    prefixes = FUND_FLOW_TIER2_STRUCTURED_PATHS.get(domain)
    if not prefixes:
        return False
    return _path_matches_prefix(path, prefixes)


def _infer_fund_flow_source_tier(payload: Dict[str, Any]) -> str:
    url = _extract_source_url(payload)
    domain = _extract_domain(url)
    if _domain_matches(domain, FUND_FLOW_TIER1_DOMAINS):
        return "tier1"
    if _is_fund_flow_tier2_structured_source(url):
        return "tier2"
    if _domain_matches(domain, FUND_FLOW_TIER3_DOMAINS):
        return "tier3"
    return "unknown"


def _infer_fund_flow_window_evidence(key: str, payload: Dict[str, Any], metric_basis: str) -> str:  # noqa: E501
    metric = str(metric_basis or "").strip().lower()
    if metric == "estimated_net_flow":
        return "derived"
    if metric == "news_net_flow":
        return "news_summary"

    explicit = _normalize_window_evidence(payload.get("window_evidence"))
    field_retry_evidence = payload.get("field_retry_evidence")
    if isinstance(field_retry_evidence, dict):
        recent = field_retry_evidence.get("recent_5d")
        total = field_retry_evidence.get("total_120d")
        if isinstance(recent, dict) and isinstance(total, dict):
            recent_trusted = _fund_flow_has_trusted_window(
                _infer_fund_flow_source_tier(recent),
                str(recent.get("window_evidence") or "unknown"),
                str(recent.get("metric_basis") or metric_basis),
            )
            total_trusted = _fund_flow_has_trusted_window(
                _infer_fund_flow_source_tier(total),
                str(total.get("window_evidence") or "unknown"),
                str(total.get("metric_basis") or metric_basis),
            )
            if recent_trusted and total_trusted:
                if explicit in FUND_FLOW_DIRECT_WINDOW_EVIDENCE:
                    return explicit
                return "direct_window"
        return "unknown"

    if explicit:
        return explicit

    text = " ".join(
        str(payload.get(field) or "")
        for field in ("source", "note", "estimation_method", "description")
    ).lower()
    if any(token in text for token in ("季度", "q1", "q2", "q3", "q4", "年内", "年度", "单日", "外推")):  # noqa: E501
        return "news_summary"
    if key == "margin" and metric == "balance_delta" and any(token in text for token in ("余额", "balance")):  # noqa: E501
        return "direct_balance_delta"
    if "recent_5d_field_retry" in text and "total_120d_field_retry" in text:
        return "unknown"
    if ("近5日" in text or "5日" in text or "5-day" in text) and ("120" in text or "一百二十" in text):  # noqa: E501
        return "direct_window"
    return "unknown"


def _fund_flow_has_trusted_window(source_tier: str, window_evidence: str, metric_basis: str) -> bool:  # noqa: E501
    metric = str(metric_basis or "").strip().lower()
    if metric in FUND_FLOW_ESTIMATED_METRIC_BASIS:
        return False
    if source_tier not in {"tier1", "tier2"}:
        return False
    return window_evidence in FUND_FLOW_DIRECT_WINDOW_EVIDENCE


def _normalize_fund_flow_estimation(entry: Dict[str, Any], payload: Dict[str, Any]) -> None:  # noqa: E501
    source_tier = str(entry.get("source_tier") or "unknown")
    window_evidence = str(entry.get("window_evidence") or "unknown")
    metric_basis = str(entry.get("metric_basis") or "")
    trusted = _fund_flow_has_trusted_window(source_tier, window_evidence, metric_basis)  # noqa: E501

    if trusted:
        entry["is_estimated"] = False
        return

    entry["is_estimated"] = True
    entry.setdefault("estimation_method", "fund_flow_manual_window_not_direct")
    note_addition = (
        "fund_flow_estimated_gate:"
        f"source_tier={source_tier},"
        f"window_evidence={window_evidence},"
        f"metric_basis={metric_basis or 'unknown'}"
    )
    entry["note"] = _append_note_once(str(entry.get("note") or ""), note_addition)  # noqa: E501
