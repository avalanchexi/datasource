#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Policy-as-code evaluation for Stage2/Stage3 gating."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

DEFAULT_RULES = {
    "extract_422_threshold": 3,
    "extract_422_cooldown_sec": 300,
    "low_score_threshold": 0.2,
    "critical_missing_keys": ["dxy", "bdi", "rrr", "mlf"],
    "block_on_stale": True,
    "critical_stale_keys": ["cpi", "ppi", "pmi", "m1", "m2", "tsf"],
    "min_trading_days": 100,
    "estimated_allowlist_keys": ["CN10Y_CDB", "bdi"],
    "bdi_estimated_allow_conditions": {
        "trusted_domains": [
            "balticexchange.com",
            "tradingeconomics.com",
            "investing.com",
            "eastmoney.com",
        ],
        "max_age_days": 2,
        "weekend_grace": True,
        "value_range": [200.0, 10000.0],
        "unit_keywords": ["点", "point", "points"],
    },
    "non_blocking_warning": {
        "gc_f_risk_domains": ["guba.eastmoney.com"],
        "gc_f_anomaly_threshold_pct": 8.0,
    },
}


def _simple_yaml_load(path: Path) -> Dict[str, Any]:
    """Minimal YAML loader (supports simple key: value and top-level lists)."""
    data: Dict[str, Any] = {}
    if not path.exists():
        return data
    current_key: Optional[str] = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line and not line.startswith("-"):
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value == "":
                data[key] = []
                current_key = key
            else:
                if value.startswith("{") or value.startswith("["):
                    try:
                        data[key] = json.loads(value)
                        current_key = None
                        continue
                    except Exception:
                        pass
                # cast int if possible
                try:
                    data[key] = int(value)
                except Exception:
                    # cast float / bool if possible
                    lowered = value.lower()
                    if lowered in {"true", "false"}:
                        data[key] = lowered == "true"
                    else:
                        try:
                            data[key] = float(value)
                        except Exception:
                            data[key] = value
                current_key = None
        elif line.startswith("-") and current_key:
            item = line.lstrip("-").strip()
            data.setdefault(current_key, []).append(item)
    return data


def load_policy_rules(path: Optional[Path] = None) -> Dict[str, Any]:
    path = path or Path("config/policy_rules.yaml")
    rules = dict(DEFAULT_RULES)
    overrides = _simple_yaml_load(path)
    rules.update(overrides)
    return rules


def get_estimated_allowlist_keys(rules: Optional[Dict[str, Any]] = None) -> List[str]:
    resolved = rules or load_policy_rules()
    raw = resolved.get("estimated_allowlist_keys") or []
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def get_bdi_estimated_allow_conditions(rules: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    resolved = rules or load_policy_rules()
    base = dict(DEFAULT_RULES.get("bdi_estimated_allow_conditions", {}))
    raw = resolved.get("bdi_estimated_allow_conditions") or {}
    if isinstance(raw, dict):
        base.update(raw)
    return base


def get_non_blocking_warning_rules(rules: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    resolved = rules or load_policy_rules()
    base = dict(DEFAULT_RULES.get("non_blocking_warning", {}))
    raw = resolved.get("non_blocking_warning") or {}
    if isinstance(raw, dict):
        base.update(raw)
    return base


def _normalize_key(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def _extract_domain(url_or_text: str) -> str:
    try:
        return (urlparse(url_or_text).netloc or "").lower()
    except Exception:
        return ""


def _extract_domain_candidates(entry: Dict[str, Any]) -> List[str]:
    candidates: List[str] = []
    for field in ("source_url", "url"):
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    for field in ("source", "note"):
        value = entry.get(field)
        if not isinstance(value, str) or "http" not in value:
            continue
        candidates.extend(re.findall(r"https?://[^\s|;，,]+", value))
    return candidates


def _parse_date(value: Any) -> Optional[datetime]:
    if value in (None, "", "N/A"):
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m", "%Y/%m"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt in ("%Y-%m", "%Y/%m"):
                dt = dt.replace(day=1)
            return dt
        except Exception:
            continue
    m = re.search(r"(20\d{2})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?", text)
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2))
    day = int(m.group(3) or 1)
    try:
        return datetime(year, month, day)
    except Exception:
        return None


def check_bdi_estimated_allow(
    entry: Dict[str, Any],
    rules: Optional[Dict[str, Any]] = None,
    *,
    report_date: Any = None,
) -> Tuple[bool, List[str]]:
    cfg = get_bdi_estimated_allow_conditions(rules)
    reasons: List[str] = []

    value = entry.get("current_value")
    try:
        numeric_value = float(value)
    except Exception:
        numeric_value = None
    if numeric_value is None:
        reasons.append("bdi_value_missing")
    else:
        bounds = cfg.get("value_range") or [200.0, 10000.0]
        if isinstance(bounds, list) and len(bounds) == 2:
            low, high = float(bounds[0]), float(bounds[1])
            if numeric_value < low or numeric_value > high:
                reasons.append(f"bdi_value_out_of_range:{numeric_value}")

    unit = str(entry.get("unit") or "")
    unit_keywords = cfg.get("unit_keywords") or ["点", "point", "points"]
    if not any(str(marker).lower() in unit.lower() for marker in unit_keywords):
        reasons.append(f"bdi_unit_mismatch:{unit}")

    trusted_domains = [str(d).lower() for d in (cfg.get("trusted_domains") or []) if str(d).strip()]
    domains = [_extract_domain(item) for item in _extract_domain_candidates(entry)]
    domains = [d for d in domains if d]
    if trusted_domains:
        if not any(any(domain.endswith(td) for td in trusted_domains) for domain in domains):
            reasons.append("bdi_untrusted_domain")
    else:
        reasons.append("bdi_trusted_domains_empty")

    max_age_days = int(cfg.get("max_age_days") or 2)
    weekend_grace = bool(cfg.get("weekend_grace", False))
    dt = _parse_date(entry.get("as_of_date") or entry.get("date") or entry.get("report_period"))
    if dt is None:
        reasons.append("bdi_date_missing")
    else:
        reference_dt = _parse_date(report_date) if report_date not in (None, "") else None
        reference_dt = reference_dt or datetime.now()
        age = (reference_dt.date() - dt.date()).days
        monday_after_friday = reference_dt.weekday() == 0 and dt.weekday() == 4 and age == 3
        if age < 0:
            reasons.append(f"bdi_date_in_future:{age}d")
        elif age > max_age_days and not (weekend_grace and monday_after_friday):
            reasons.append(f"bdi_date_stale:{age}d")

    return len(reasons) == 0, reasons


def is_estimated_allowlisted(
    category: str,
    key: str,
    entry: Optional[Dict[str, Any]] = None,
    *,
    rules: Optional[Dict[str, Any]] = None,
    report_date: Any = None,
) -> Tuple[bool, List[str]]:
    allowlist = {_normalize_key(item) for item in get_estimated_allowlist_keys(rules)}
    key_norm = _normalize_key(key)
    if key_norm not in allowlist:
        return False, ["not_in_allowlist"]

    if key_norm == "bdi":
        if not isinstance(entry, dict):
            return False, ["bdi_entry_missing"]
        ok, reasons = check_bdi_estimated_allow(entry, rules, report_date=report_date)
        return ok, reasons
    return True, []


def evaluate_policy(
    market_payload: Dict[str, Any],
    *,
    stage2_summary: Optional[Dict[str, Any]] = None,
    rules_path: Optional[Path] = None,
) -> Dict[str, Any]:
    rules = load_policy_rules(rules_path)
    metadata = market_payload.get("metadata", {}) if isinstance(market_payload, dict) else {}
    missing = metadata.get("missing_items", {}) if isinstance(metadata.get("missing_items", {}), dict) else {}

    critical_keys = set(k.lower() for k in rules.get("critical_missing_keys", []))
    critical_stale_keys = set(k.lower() for k in rules.get("critical_stale_keys", []))
    redlist = []
    for category, items in missing.items():
        for item in items:
            key = item.get("key") if isinstance(item, dict) else item
            if key and key.lower() in critical_keys:
                redlist.append({"key": key, "category": category})

    stale_redlist = []
    block_on_stale = bool(rules.get("block_on_stale", True))
    for category in ("macro_indicators", "monetary_policy"):
        section = market_payload.get(category, {})
        if not isinstance(section, dict):
            continue
        for key, payload in section.items():
            if not isinstance(payload, dict):
                continue
            if not payload.get("is_stale"):
                continue
            if key.lower() not in critical_stale_keys:
                continue
            stale_redlist.append(
                {
                    "key": key,
                    "category": category,
                    "date": payload.get("date"),
                    "expected_period": payload.get("expected_period"),
                    "reason": payload.get("stale_reason"),
                }
            )

    block_stage3 = bool(redlist) or (block_on_stale and bool(stale_redlist))

    extract_422_threshold = rules.get("extract_422_threshold", 3)
    extract_422_count = 0
    if stage2_summary:
        extract_422_count = stage2_summary.get("tavily_extract_422_count", 0) or 0

    return {
        "generated_at": datetime.now().isoformat(),
        "date": metadata.get("date") or metadata.get("end_date") or metadata.get("start_date"),
        "redlist": redlist,
        "stale_redlist": stale_redlist,
        "block_on_stale": block_on_stale,
        "block_stage3": block_stage3,
        "extract_422_count": extract_422_count,
        "extract_422_threshold": extract_422_threshold,
        "recommend_disable_extract": extract_422_count >= extract_422_threshold,
    }


def write_policy_evaluation(payload: Dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
