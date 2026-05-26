"""Official source trust checks for Stage2 writeback."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


OFFICIAL_SOURCE_DOMAINS = {
    "stats.gov.cn",
    "data.stats.gov.cn",
    "pbc.gov.cn",
    "chinamoney.com.cn",
    "cfets.com.cn",
    "hkex.com.hk",
    "sse.com.cn",
    "szse.cn",
}

MACRO_OFFICIAL_SOURCE_DOMAINS = {
    "stats.gov.cn",
    "data.stats.gov.cn",
}

MONETARY_OFFICIAL_SOURCE_DOMAINS = {
    "pbc.gov.cn",
    "chinamoney.com.cn",
    "cfets.com.cn",
}

TRACKING_QUERY_PARAMS = {
    "from",
    "source",
    "spm",
    "tavily",
    "utm",
}


@dataclass(frozen=True)
class OfficialSourceDecision:
    allowed: bool
    reason: str


def _parsed_url(url: Any):
    if not isinstance(url, str) or not url.strip():
        return None
    text = url.strip()
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return None
    return parsed


def _hostname(url: Any) -> str:
    parsed = _parsed_url(url)
    if parsed is None:
        return ""
    return (parsed.hostname or "").lower().rstrip(".")


def is_official_source_url(url: Any) -> bool:
    parsed = _parsed_url(url)
    if parsed is None or parsed.scheme.lower() != "https":
        return False
    host = _hostname(url)
    if not host:
        return False
    return _host_matches_any(host, OFFICIAL_SOURCE_DOMAINS)


def _host_matches_any(host: str, domains: Iterable[str]) -> bool:
    for domain in domains:
        domain_norm = domain.lower().rstrip(".")
        if host == domain_norm or host.endswith("." + domain_norm):
            return True
    return False


def _source_allowed_for_category(source_url: Any, category: Any) -> bool:
    parsed = _parsed_url(source_url)
    if parsed is None or parsed.scheme.lower() != "https":
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    category_norm = str(category or "").strip().lower()
    if category_norm in {"macro", "macro_indicators"}:
        return _host_matches_any(host, MACRO_OFFICIAL_SOURCE_DOMAINS)
    if category_norm in {"monetary", "monetary_policy"}:
        return _host_matches_any(host, MONETARY_OFFICIAL_SOURCE_DOMAINS)
    return _host_matches_any(host, OFFICIAL_SOURCE_DOMAINS)


def _normalize_url_for_match(url: Any) -> Optional[str]:
    parsed = _parsed_url(url)
    if parsed is None:
        return None
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return None
    port = parsed.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"
    else:
        netloc = host
    path = (parsed.path or "").rstrip("/")
    query_parts = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        key_norm = key.lower()
        if key_norm.startswith("utm_") or key_norm in TRACKING_QUERY_PARAMS:
            continue
        query_parts.append((key, value))
    query = urlencode(sorted(query_parts))
    return urlunparse((scheme, netloc, path, "", query, ""))


def _snippet_urls(snippets: Iterable[Any]) -> List[str]:
    urls: List[str] = []
    for item in snippets or []:
        if isinstance(item, str):
            urls.extend(re.findall(r"https?://[^\s，,;|]+", item))
            continue
        if not isinstance(item, dict):
            continue
        for field in ("url", "source_url", "link", "href"):
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                urls.append(value.strip())
    return urls


def source_url_in_snippets(source_url: Any, snippets: Iterable[Any]) -> bool:
    expected = _normalize_url_for_match(source_url)
    if expected is None:
        return False
    return any(_normalize_url_for_match(url) == expected for url in _snippet_urls(snippets))


def _date_parts(value: Any) -> Optional[tuple]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    match = re.search(r"(20\d{2})\s*[-/.年]\s*(\d{1,2})(?:\s*[-/.月]\s*(\d{1,2}))?", text)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3)) if match.group(3) else None
    return year, month, day


def _period_matches(expected: Any, candidate: Any) -> bool:
    expected_parts = _date_parts(expected)
    candidate_parts = _date_parts(candidate)
    if expected_parts is None or candidate_parts is None:
        return False
    if expected_parts[:2] != candidate_parts[:2]:
        return False
    expected_day = expected_parts[2]
    candidate_day = candidate_parts[2]
    if expected_day is not None:
        return candidate_day == expected_day
    return True


def _expected_period_values(task: Dict[str, Any]) -> List[Any]:
    values = [
        value
        for value in (task.get("expected_period"), task.get("expected_date"), task.get("ref_date"))
        if value not in (None, "")
    ]
    for token in task.get("expected_period_tokens") or []:
        if _date_parts(token) is not None:
            values.append(token)
    return values


def _extraction_period_values(extraction: Dict[str, Any]) -> List[Any]:
    return [
        value
        for value in (
            extraction.get("report_period"),
            extraction.get("as_of_date"),
            extraction.get("date"),
            extraction.get("ref_date"),
        )
        if value not in (None, "")
    ]


def units_compatible(unit_hint: Any, extraction_unit: Any) -> bool:
    hint = str(unit_hint or "").strip().lower().replace("％", "%")
    unit = str(extraction_unit or "").strip().lower().replace("％", "%")
    if not hint:
        return True
    if not unit:
        return False
    hint_class = _canonical_unit_class(hint)
    unit_class = _canonical_unit_class(unit)
    if hint_class or unit_class:
        return hint_class == unit_class
    return hint in unit or unit in hint


def _canonical_unit_class(value: str) -> Optional[str]:
    text = re.sub(r"\s+", " ", value.strip().lower().replace("％", "%"))
    if not text:
        return None
    if (
        "百分点" in text
        or "percentage point" in text
        or "pct point" in text
        or re.search(r"\bpp\b", text)
    ):
        return "percentage_point"
    if "%" in text or "percent" in text or "百分比" in text or "百分数" in text:
        return "percent"
    if "指数点" in text or text == "点" or re.search(r"\bpoints?\b", text):
        return "point"
    return None


def should_mark_official_non_estimated(
    task: Dict[str, Any],
    extraction: Dict[str, Any],
    snippets: Iterable[Any],
) -> OfficialSourceDecision:
    if str(task.get("category") or "").strip().lower() == "fund_flow":
        return OfficialSourceDecision(False, "fund_flow_requires_window_gate")

    source_url = extraction.get("source_url")
    if not is_official_source_url(source_url) or not _source_allowed_for_category(source_url, task.get("category")):
        return OfficialSourceDecision(False, "source_url_not_official")

    if not source_url_in_snippets(source_url, snippets):
        return OfficialSourceDecision(False, "source_url_not_in_snippets")

    if extraction.get("value") in (None, ""):
        return OfficialSourceDecision(False, "missing_value")

    expected_values = _expected_period_values(task)
    if not expected_values:
        return OfficialSourceDecision(False, "missing_expected_period")
    extraction_values = _extraction_period_values(extraction)
    if not any(_period_matches(expected, candidate) for expected in expected_values for candidate in extraction_values):
        return OfficialSourceDecision(False, "period_mismatch")

    if not units_compatible(task.get("unit"), extraction.get("unit")):
        return OfficialSourceDecision(False, "unit_mismatch")

    return OfficialSourceDecision(True, "official_source_period_unit_match")
