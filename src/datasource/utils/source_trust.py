"""Official source trust checks for Stage2 writeback."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse, urlunparse


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


@dataclass(frozen=True)
class OfficialSourceDecision:
    allowed: bool
    reason: str


def _hostname(url: Any) -> str:
    if not isinstance(url, str) or not url.strip():
        return ""
    text = url.strip()
    parsed = urlparse(text)
    if not parsed.netloc and not parsed.scheme:
        parsed = urlparse("https://" + text)
    return (parsed.hostname or "").lower().rstrip(".")


def is_official_source_url(url: Any) -> bool:
    host = _hostname(url)
    if not host:
        return False
    for domain in OFFICIAL_SOURCE_DOMAINS:
        domain_norm = domain.lower().rstrip(".")
        if host == domain_norm or host.endswith("." + domain_norm):
            return True
    return False


def _normalize_url_for_match(url: Any) -> Optional[str]:
    if not isinstance(url, str) or not url.strip():
        return None
    text = url.strip()
    parsed = urlparse(text)
    if not parsed.netloc and not parsed.scheme:
        parsed = urlparse("https://" + text)
    if not parsed.scheme or not parsed.netloc:
        return None
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = (parsed.path or "").rstrip("/")
    return urlunparse((scheme, netloc, path, "", "", ""))


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
    return [
        value
        for value in (task.get("expected_period"), task.get("expected_date"), task.get("ref_date"))
        if value not in (None, "")
    ]


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


def _unit_matches(unit_hint: Any, extraction_unit: Any) -> bool:
    hint = str(unit_hint or "").strip().lower().replace("％", "%")
    unit = str(extraction_unit or "").strip().lower().replace("％", "%")
    if not hint:
        return True
    if not unit:
        return False
    point_units = {"点", "point", "points"}
    if hint in point_units:
        return any(token in unit for token in point_units)
    return hint in unit or unit in hint


def should_mark_official_non_estimated(
    task: Dict[str, Any],
    extraction: Dict[str, Any],
    snippets: Iterable[Any],
) -> OfficialSourceDecision:
    if str(task.get("category") or "").strip().lower() == "fund_flow":
        return OfficialSourceDecision(False, "fund_flow_requires_window_gate")

    source_url = extraction.get("source_url")
    if not is_official_source_url(source_url):
        return OfficialSourceDecision(False, "source_url_not_official")

    if not source_url_in_snippets(source_url, snippets):
        return OfficialSourceDecision(False, "source_url_not_in_snippets")

    if extraction.get("value") in (None, ""):
        return OfficialSourceDecision(False, "missing_value")

    expected_values = _expected_period_values(task)
    if expected_values:
        extraction_values = _extraction_period_values(extraction)
        if not any(_period_matches(expected, candidate) for expected in expected_values for candidate in extraction_values):
            return OfficialSourceDecision(False, "period_mismatch")

    if not _unit_matches(task.get("unit"), extraction.get("unit")):
        return OfficialSourceDecision(False, "unit_mismatch")

    return OfficialSourceDecision(True, "official_source_period_unit_match")
