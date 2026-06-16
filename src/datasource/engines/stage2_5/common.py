import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from datasource.utils.coercion import (
    is_legacy_713_placeholder,
    is_stage2_number_placeholder,
)
from datasource.utils.pipeline_quality_state import (
    build_pipeline_quality_state,
)
from datasource.utils.policy_rules import (
    is_estimated_allowlisted,
    load_policy_rules,
)


OFFICIAL_MANUAL_TEXT_FIELDS = ("source", "note", "name", "policy_name", "indicator_name")  # noqa: E501
EXPLICIT_URL_FIELDS = ("source_url", "sourceUrl", "url")
URL_EVIDENCE_TERMINATORS = set(" \t\r\n,;|)]}<>\x22'") | set("，；）】》、」』”’｝］〉")  # noqa: E501
HTTP_LIKE_START_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:https?://|https?(?![A-Za-z0-9]))"
)
BARE_DOMAIN_START_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9./:-])(?:www\.)?(?:[A-Za-z0-9-]+\.)+[A-Za-z0-9-]*[A-Za-z][A-Za-z0-9-]*(?=[:/]|$|[\s,;|)\]}<>\"'，；）】》、」』”’｝］〉])"  # noqa: E501
)
_POLICY_RULES_CACHE: Optional[Dict[str, Any]] = None
DEFAULT_SOURCE_LABEL = "websearch_manual"
SOURCE_ANOMALY_LABEL = "异常零值-需核查"


def _policy_rules() -> Dict[str, Any]:
    global _POLICY_RULES_CACHE
    if _POLICY_RULES_CACHE is None:
        _POLICY_RULES_CACHE = load_policy_rules()
    return _POLICY_RULES_CACHE


def _is_estimated_allowlisted_entry(category: str, key: str, entry: Optional[Dict[str, Any]]) -> bool:  # noqa: E501
    if not isinstance(entry, dict):
        return False
    allowed, _ = is_estimated_allowlisted(category, key, entry, rules=_policy_rules())  # noqa: E501
    return allowed


def _apply_pipeline_quality_state(
    market_data: Dict[str, Any],
    *,
    allow_estimated: bool = False,
) -> Dict[str, Any]:
    state = build_pipeline_quality_state(
        market_data,
        policy_rules=_policy_rules(),
        stage="stage2_5",
        allow_estimated=allow_estimated,
    )
    metadata = market_data.setdefault("metadata", {})
    metadata["missing_items"] = state["missing_items"] or {}
    metadata["quality_blockers"] = state["quality_blockers"]
    metadata["source_url_issues"] = state["source_url_issues"]
    metadata["window_metric_issues"] = state["window_metric_issues"]
    metadata["manual_required"] = state["manual_required"]
    market_data["missing_items"] = list(state.get("gap_monitor_view", {}).get("manual_required", []))  # noqa: E501
    if not market_data["missing_items"]:
        market_data["missing_items"] = []
    return state


def _issue_signature(issue: Dict[str, Any]) -> Tuple[Any, Any, Any, Any]:
    return (issue.get("category"), issue.get("key"), issue.get("field"), issue.get("reason"))  # noqa: E501


def _merge_quality_issues(base_issues: List[Dict[str, Any]], extra_issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:  # noqa: E501
    merged: List[Dict[str, Any]] = []
    seen = set()
    for item in list(base_issues or []) + list(extra_issues or []):
        if not isinstance(item, dict):
            continue
        sig = _issue_signature(item)
        if sig in seen:
            continue
        seen.add(sig)
        merged.append(item)
    return merged


def _extract_domain(value: Optional[str]) -> str:
    if not value:
        return ""
    text = str(value).strip().strip("<>()[]{}\"'")
    if not text:
        return ""
    parsed = urlparse(text)
    if not parsed.hostname and "://" not in text and not text.startswith("//"):
        parsed = urlparse(f"//{text}")
    try:
        parsed.port
    except ValueError:
        return ""
    hostname = parsed.hostname or ""
    return hostname.lower().strip()


def _normalize_parseable_http_url(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip().strip("<>()[]{}\"'")
    if not text or any(char.isspace() for char in text):
        return None
    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    try:
        parsed.port
    except ValueError:
        return None
    hostname = (parsed.hostname or "").strip()
    if not hostname or any(char.isspace() for char in hostname):
        return None
    return text


def _is_url_evidence_terminator(char: str) -> bool:
    return char in URL_EVIDENCE_TERMINATORS


def _collect_http_like_evidence(value: Any) -> List[str]:
    if not isinstance(value, str):
        return []
    text = value.strip()
    if not text:
        return []
    evidence: List[str] = []
    for match in HTTP_LIKE_START_RE.finditer(text):
        end = match.end()
        while end < len(text) and not _is_url_evidence_terminator(text[end]):
            end += 1
        token = text[match.start() : end].strip()  # noqa: E203
        if token:
            evidence.append(token)
    for match in BARE_DOMAIN_START_RE.finditer(text):
        end = match.end()
        while end < len(text) and not _is_url_evidence_terminator(text[end]):
            end += 1
        token = text[match.start() : end].strip()  # noqa: E203
        if token:
            evidence.append(token)
    return evidence


def _extract_embedded_http_url(value: Any) -> Optional[str]:
    for token in _collect_http_like_evidence(value):
        url = _normalize_parseable_http_url(token)
        if url:
            return url
    return None


def _iter_http_like_evidence(value: Any, *, fallback_raw: bool = False) -> List[str]:  # noqa: E501
    if not isinstance(value, str):
        return []
    text = value.strip()
    if not text:
        return []
    matches = _collect_http_like_evidence(text)
    if matches:
        return matches
    if fallback_raw:
        return [text]
    return []


def _extract_source_url(payload: Dict[str, Any]) -> Optional[str]:
    for key in EXPLICIT_URL_FIELDS:
        url = _extract_embedded_http_url(payload.get(key))
        if url:
            return url
    for key in ("source", "note"):
        url = _extract_embedded_http_url(payload.get(key))
        if url:
            return url
    return None


def _attach_source_url(payload: Dict[str, Any]) -> None:
    url = _normalize_parseable_http_url(payload.get("source_url"))
    if not url:
        return
    if _extract_source_url(payload):
        return
    source = payload.get("source")
    if isinstance(source, str) and source.strip():
        payload["source"] = f"{source} | {url}"
    else:
        payload["source"] = url


def _iter_url_like_evidence(payload: Dict[str, Any]) -> List[str]:
    evidence: List[str] = []
    for field in EXPLICIT_URL_FIELDS:
        evidence.extend(_iter_http_like_evidence(payload.get(field), fallback_raw=True))  # noqa: E501
    for field in OFFICIAL_MANUAL_TEXT_FIELDS:
        evidence.extend(_iter_http_like_evidence(payload.get(field)))
    return evidence


def _is_https_url_evidence(value: str) -> bool:
    return urlparse(value).scheme.lower() == "https"


def _extract_domains_from_payload(payload: Dict[str, Any]) -> List[str]:
    domains: List[str] = []
    for value in _iter_url_like_evidence(payload):
        domain = _extract_domain(value)
        if domain:
            domains.append(domain)
    return domains


def _extract_domains_from_evidence(url_like_evidence: List[str]) -> List[str]:
    domains: List[str] = []
    for value in url_like_evidence:
        domain = _extract_domain(value)
        if domain:
            domains.append(domain)
    return domains


def _is_placeholder_numeric(value: Any) -> bool:
    return is_stage2_number_placeholder(value) or is_legacy_713_placeholder(value)  # noqa: E501


def _has_valid_value(value: Any) -> bool:
    return not _is_placeholder_numeric(value)


def _coerce_float(value: Any) -> Optional[float]:
    if value in (None, '', 'N/A'):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(',', '')
        if not text:
            return None
        text = text.replace('%', '')
        match = re.search(r'[-+]?\d+(?:\.\d+)?', text)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return None
    return None


def _pct_change(current: Any, previous: Any) -> Optional[float]:
    current_value = _coerce_float(current)
    previous_value = _coerce_float(previous)
    if current_value is None or previous_value is None:
        return None
    if abs(previous_value) < 1e-9:
        return None
    return round((current_value - previous_value) / abs(previous_value) * 100.0, 4)  # noqa: E501


def _same_numeric_value(left: Any, right: Any) -> bool:
    left_value = _coerce_float(left)
    right_value = _coerce_float(right)
    if left_value is None or right_value is None:
        return False
    return abs(left_value - right_value) < 1e-9


def _calc_change_rate_pct(current_value: Optional[float], previous_value: Optional[float]) -> Optional[float]:  # noqa: E501
    """按百分比口径计算变化率：(current - previous) / abs(previous) * 100。"""
    if current_value is None or previous_value is None:
        return None
    try:
        current = float(current_value)
        previous = float(previous_value)
        denominator = abs(previous)
        if denominator < 1e-9:
            return None
        return round((current - previous) / denominator * 100.0, 4)
    except Exception:
        return None


def _calc_previous_from_change_rate_pct(
    current_value: Optional[float], change_rate_pct: Optional[float]
) -> Optional[float]:
    """按百分比口径反推前值：previous = current / (1 + change_rate/100)。"""
    if current_value is None or change_rate_pct is None:
        return None
    try:
        denominator = 1.0 + float(change_rate_pct) / 100.0
        if abs(denominator) < 1e-9:
            return None
        return round(float(current_value) / denominator, 4)
    except Exception:
        return None


def _coerce_percent(value: Any) -> Optional[float]:
    if value in (None, '', 'N/A'):
        return None
    try:
        return float(str(value).replace('%', '').strip())
    except Exception:
        return None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {'true', '1', 'yes', 'y', '是'}
    return False


def _format_source_label(raw_source: Optional[str]) -> str:
    source_text = str(raw_source or "").strip()
    if not source_text:
        return DEFAULT_SOURCE_LABEL
    if source_text == SOURCE_ANOMALY_LABEL:
        return source_text
    if source_text == DEFAULT_SOURCE_LABEL or source_text.startswith(
        f"{DEFAULT_SOURCE_LABEL}("
    ):
        return source_text
    lower_source = source_text.lower()
    if "manual_required" in lower_source or "websearch_manual" in lower_source:
        return DEFAULT_SOURCE_LABEL
    if (
        "tavily" in lower_source
        or "deepseek" in lower_source
        or source_text == DEFAULT_SOURCE_LABEL
    ):
        return source_text
    if source_text.startswith("http"):
        return f"{DEFAULT_SOURCE_LABEL}({source_text})"
    return f"{DEFAULT_SOURCE_LABEL}({source_text})"


def _update_metadata_only(
    entry: Dict[str, Any],
    payload: Dict[str, Any],
) -> bool:
    from datasource.engines.stage2_5.manual_official import (
        _should_preserve_existing_official_source,
    )

    changed = False
    preserve_existing_official_source = (
        _should_preserve_existing_official_source(entry, payload)
    )

    def set_if_changed(field: str, value: Any) -> None:
        nonlocal changed
        if value is None:
            return
        if entry.get(field) != value:
            entry[field] = value
            changed = True

    incoming_date = (
        payload.get("date")
        or payload.get("as_of_date")
        or payload.get("report_period")
    )
    if incoming_date:
        set_if_changed("date", incoming_date)
    if payload.get("as_of_date") or payload.get("report_period"):
        set_if_changed(
            "as_of_date",
            payload.get("as_of_date") or payload.get("report_period"),
        )
    if "report_period" in payload:
        set_if_changed("report_period", payload.get("report_period"))
    if "source" in payload and not preserve_existing_official_source:
        set_if_changed("source", _format_source_label(payload.get("source")))
    source_url = _extract_source_url(payload)
    if source_url and not preserve_existing_official_source:
        set_if_changed("source_url", source_url)
    if "note" in payload and not preserve_existing_official_source:
        note_val = payload.get("note")
        set_if_changed("note", note_val if isinstance(note_val, str) else "")
    for field_name in ("confidence", "estimation_method"):
        if field_name in payload:
            set_if_changed(field_name, payload.get(field_name))
    if "is_estimated" in payload:
        incoming_estimated = _coerce_bool(payload.get("is_estimated"))
        if not (
            preserve_existing_official_source
            and entry.get("is_estimated") is False
            and incoming_estimated is True
        ):
            set_if_changed("is_estimated", incoming_estimated)
    return changed


def _merge_same_value_report_fields(
    entry: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    category: str,
    key: str,
    is_manual: bool = False,
    override_stale: bool = True,
) -> bool:
    from datasource.engines.stage2_5.manual_official import (
        _apply_manual_official_estimation_rule,
        _has_rrr_type_conflict,
        _is_trusted_monetary_manual_quality_override,
        _normalize_rrr_type,
    )

    metadata_payload = payload
    if category == "monetary_policy" and "is_estimated" in payload:
        metadata_payload = dict(payload)
        metadata_payload.pop("is_estimated", None)
    changed = _update_metadata_only(entry, metadata_payload)

    def set_if_changed(field: str, value: Any) -> None:
        nonlocal changed
        if value is None:
            return
        if entry.get(field) != value:
            entry[field] = value
            changed = True

    if category == "macro_indicators":
        for field in ("previous_value", "change_rate", "yoy_month", "yoy_ytd"):
            if field in payload:
                set_if_changed(field, _coerce_float(payload.get(field)))
        for field in ("value_type", "report_period"):
            if field in payload:
                set_if_changed(field, payload.get(field))
    elif category == "monetary_policy":
        if "change_from_120d" in payload:
            change_value = payload.get("change_from_120d")
        else:
            change_value = payload.get("change_rate")
        set_if_changed("change_from_120d", _coerce_float(change_value))

        rrr_type_conflict = (
            _has_rrr_type_conflict(entry, payload)
            if key in {"rrr", "reserve_ratio"}
            else False
        )
        incoming_rrr_type = _normalize_rrr_type(
            payload.get("rrr_type") or payload.get("value_type")
        )
        if not rrr_type_conflict:
            set_if_changed("rrr_type", incoming_rrr_type)

        if is_manual:
            before_estimated = entry.get("is_estimated")
            before_note = entry.get("note")
            _apply_manual_official_estimation_rule(
                category,
                key,
                payload,
                entry,
            )
            if _is_trusted_monetary_manual_quality_override(
                key,
                entry,
                payload,
                _coerce_float(payload.get("current_value")),
                is_manual=is_manual,
            ):
                entry["is_estimated"] = False
            changed = (
                changed
                or before_estimated != entry.get("is_estimated")
                or before_note != entry.get("note")
            )

    if changed and entry.get("current_value") is not None:
        if override_stale or not bool(entry.get("is_stale")):
            entry["is_stale"] = False
            entry["stale_reason"] = None
    return changed
