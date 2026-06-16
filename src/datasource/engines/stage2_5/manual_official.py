from typing import Any, Dict, List, Optional, Tuple

from datasource.engines.stage2_5.common import (
    EXPLICIT_URL_FIELDS,
    OFFICIAL_MANUAL_TEXT_FIELDS,
    _coerce_bool,
    _coerce_float,
    _extract_domain,
    _extract_source_url,
    _is_https_url_evidence,
    _iter_http_like_evidence,
    _iter_url_like_evidence,
)
from datasource.utils.key_aliases import canonical_monetary_key
from datasource.utils.note_utils import append_note_to_entry as _append_note
from datasource.utils.source_trust import is_official_source_url


__all__ = [
    "OFFICIAL_MANUAL_NOTE",
    "OFFICIAL_MANUAL_SOURCES",
    "TRUSTED_MONETARY_MANUAL_QUALITY_DOMAINS",
    "_should_preserve_existing_official_source",
    "_normalize_manual_official_key",
    "_iter_url_like_evidence",
    "_iter_explicit_url_evidence",
    "_has_multi_value_explicit_url_evidence",
    "_has_invalid_explicit_url_evidence",
    "_single_trusted_explicit_https_url",
    "_official_domain_matches",
    "_is_manual_official_value",
    "_apply_manual_official_estimation_rule",
    "_is_trusted_monetary_manual_quality_override",
]


OFFICIAL_MANUAL_NOTE = "manual_official_not_estimated"
OFFICIAL_MANUAL_SOURCES = {
    "monetary_policy": {
        "mlf": {
            "trusted_domains": ("pbc.gov.cn", "chinamoney.com.cn"),
        },
    },
    "forex": {
        "usdcny": {
            "trusted_domains": (
                "chinamoney.com.cn",
                "cfets.com.cn",
                "pbc.gov.cn",
            ),
        },
    },
    "commodities": {
        "bcom": {
            "trusted_domains": ("bloomberg.com", "bloombergindices.com"),
        },
    },
    "bonds": {},
}
TRUSTED_MONETARY_MANUAL_QUALITY_DOMAINS = {
    "reserve_ratio": ("pbc.gov.cn",),
}


def _should_preserve_existing_official_source(
    target: Dict[str, Any],
    payload: Dict[str, Any],
) -> bool:
    existing_url = _extract_source_url(target)
    if not existing_url or not is_official_source_url(existing_url):
        return False
    incoming_url = _extract_source_url(payload)
    return not (incoming_url and is_official_source_url(incoming_url))


def _normalize_manual_official_key(category: str, key: str) -> str:
    if category == "monetary_policy":
        return canonical_monetary_key(str(key)).lower()
    return str(key).lower()


def _iter_explicit_url_evidence(payload: Dict[str, Any]) -> List[str]:
    evidence: List[str] = []
    for field in EXPLICIT_URL_FIELDS:
        evidence.extend(
            _iter_http_like_evidence(payload.get(field), fallback_raw=True)
        )
    return evidence


def _has_multi_value_explicit_url_evidence(payload: Dict[str, Any]) -> bool:
    for field in EXPLICIT_URL_FIELDS:
        if (
            len(
                _iter_http_like_evidence(
                    payload.get(field),
                    fallback_raw=True,
                )
            ) > 1
        ):
            return True
    return False


def _has_invalid_explicit_url_evidence(payload: Dict[str, Any]) -> bool:
    for field in EXPLICIT_URL_FIELDS:
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            return True
        if isinstance(value, str):
            text = value.strip()
            if not text:
                continue
            tokens = _iter_http_like_evidence(text)
            if len(tokens) != 1 or tokens[0] != text:
                return True
    return False


def _single_trusted_explicit_https_url(
    payload: Dict[str, Any],
    trusted_domains: Tuple[str, ...],
) -> Optional[str]:
    if _has_invalid_explicit_url_evidence(payload):
        return None
    if _has_multi_value_explicit_url_evidence(payload):
        return None
    url_like_evidence = _iter_explicit_url_evidence(payload)
    if len(url_like_evidence) != 1:
        return None
    source_url = url_like_evidence[0]
    if not _is_https_url_evidence(source_url):
        return None
    domain = _extract_domain(source_url)
    if not domain:
        return None
    if not any(
        _official_domain_matches(domain, trusted_domain)
        for trusted_domain in trusted_domains
    ):
        return None
    text_url_evidence: List[str] = []
    for field in OFFICIAL_MANUAL_TEXT_FIELDS:
        text_url_evidence.extend(_iter_http_like_evidence(payload.get(field)))
    if len(text_url_evidence) > 1:
        return None
    for value in text_url_evidence:
        if not _is_https_url_evidence(value):
            return None
        text_domain = _extract_domain(value)
        if not text_domain:
            return None
        if not any(
            _official_domain_matches(text_domain, trusted_domain)
            for trusted_domain in trusted_domains
        ):
            return None
    return source_url


def _official_domain_matches(domain: str, trusted_domain: str) -> bool:
    domain = domain.lower().strip()
    trusted_domain = trusted_domain.lower().strip()
    return domain == trusted_domain or domain.endswith(f".{trusted_domain}")


def _is_manual_official_value(
    category: str,
    key: str,
    payload: Dict[str, Any],
) -> bool:
    if not isinstance(payload, dict):
        return False
    category_rules = OFFICIAL_MANUAL_SOURCES.get(category) or {}
    rule = category_rules.get(_normalize_manual_official_key(category, key))
    if not rule:
        return False

    trusted_domains = tuple(
        str(item).lower()
        for item in rule.get("trusted_domains", ())
        if str(item).strip()
    )
    if _has_invalid_explicit_url_evidence(payload):
        return False
    if _has_multi_value_explicit_url_evidence(payload):
        return False
    if not trusted_domains:
        return False
    return (
        _single_trusted_explicit_https_url(
            payload,
            trusted_domains,
        )
        is not None
    )


def _apply_manual_official_estimation_rule(
    category: str,
    key: str,
    payload: Dict[str, Any],
    entry: Dict[str, Any],
) -> None:
    if not _is_manual_official_value(category, key, payload):
        return
    entry["is_estimated"] = False
    if OFFICIAL_MANUAL_NOTE not in str(entry.get("note") or ""):
        _append_note(entry, OFFICIAL_MANUAL_NOTE)


def _is_trusted_monetary_manual_quality_override(
    indicator_key: str,
    entry: Dict[str, Any],
    payload: Dict[str, Any],
    incoming_current_value: Optional[float],
    *,
    is_manual: bool,
) -> bool:
    key = (
        "reserve_ratio"
        if indicator_key in {"rrr", "reserve_ratio"}
        else indicator_key
    )
    if not is_manual or key not in TRUSTED_MONETARY_MANUAL_QUALITY_DOMAINS:
        return False
    if _has_rrr_type_conflict(entry, payload):
        return False
    if incoming_current_value is None:
        return False
    if not bool(entry.get("is_estimated")):
        existing_source_url = _extract_source_url(entry)
        existing_official = bool(
            existing_source_url
            and is_official_source_url(existing_source_url)
        )
        existing_compare_gap = (
            _coerce_float(entry.get("change_from_120d")) is None
        )
        note_text = str(entry.get("note") or "")
        if (
            existing_official
            or not existing_compare_gap
            or "缺少发布机构" not in note_text
        ):
            return False
    if (
        "is_estimated" not in payload
        or _coerce_bool(payload.get("is_estimated")) is not False
    ):
        return False
    source_url = _single_trusted_explicit_https_url(
        payload,
        TRUSTED_MONETARY_MANUAL_QUALITY_DOMAINS[key],
    )
    if not source_url:
        return False
    return True


def _has_rrr_type_conflict(
    entry: Dict[str, Any],
    payload: Dict[str, Any],
) -> bool:
    existing_rrr_type = _normalize_rrr_type(entry.get("rrr_type"))
    incoming_rrr_type = _normalize_rrr_type(
        payload.get("rrr_type") or payload.get("value_type")
    )
    return bool(
        existing_rrr_type
        and incoming_rrr_type
        and incoming_rrr_type != existing_rrr_type
        and entry.get("current_value") is not None
    )


def _normalize_rrr_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip().lower()
    if "加权" in text or "weighted" in text:
        return "weighted"
    if "法定" in text or "statutory" in text:
        return "statutory"
    if "平均" in text:
        # 无明确口径时保守归类为法定平均
        return "statutory"
    return None
