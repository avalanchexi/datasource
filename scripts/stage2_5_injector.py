#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI WebSearch 数据注入脚本。

将 websearch_results 注入到 market_data 文件中，作为 Stage2.5 主入口。
"""

import argparse
import json
from functools import partial
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple

from datasource.models.market_data_contract import FundFlowData
from datasource.utils.trend_history_store import (
    write_from_market_data,
    write_trend_history_gap_snapshot,
    DEFAULT_BASE_DIR,
    SERIES_WINDOWS,
)
from datasource.utils.fund_flow_series import apply_override, compute_rollup, load_daily_series
from datasource.utils.quality_metrics import build_quality_metrics
from datasource.utils.key_aliases import (
    MONETARY_KEY_ALIASES,
    normalize_monetary_section,
)
from datasource.utils.policy_rules import (
    get_non_blocking_warning_rules,
)
from datasource.utils.run_lock import DailyRunLock, run_dir_from_artifact
from datasource.utils.run_paths import build_run_paths_from_reference
from datasource.utils.text_markers import contains_ytd_marker
from datasource.utils.forex_evidence import (
    FOREX_DAILY_CHANGE_EVIDENCE_KEYS,
    FOREX_120D_CHANGE_EVIDENCE_KEYS,
    STAGE25_FOREX_DAILY_CHANGE_SOURCE_MARKERS as FOREX_DAILY_CHANGE_SOURCE_MARKERS,
    STAGE25_FOREX_120D_CHANGE_SOURCE_MARKERS as FOREX_120D_CHANGE_SOURCE_MARKERS,
    copy_valid_stage25_forex_120d_change_evidence,
    copy_valid_stage25_forex_daily_change_evidence,
    has_forex_computed_marker,
    has_stage25_forex_120d_change_evidence,
    has_stage25_forex_daily_change_evidence,
    is_stage25_forex_daily_change_absence_text,
    is_valid_forex_base_date,
    is_valid_forex_base_price,
    is_valid_forex_source_url,
)
from datasource.utils.note_utils import (
    append_note_once as _append_note_once,
    append_note_to_entry as _append_note,
)
from datasource.engines.stage2_5.common import (  # noqa: F401 (C4 re-export)
    BARE_DOMAIN_START_RE,
    EXPLICIT_URL_FIELDS,
    HTTP_LIKE_START_RE,
    OFFICIAL_MANUAL_TEXT_FIELDS,
    URL_EVIDENCE_TERMINATORS,
    _apply_pipeline_quality_state,
    _attach_source_url,
    _calc_change_rate_pct,
    _calc_previous_from_change_rate_pct,
    _coerce_bool,
    _coerce_float,
    _coerce_percent,
    _collect_http_like_evidence,
    _extract_domain,
    _extract_domains_from_evidence,
    _extract_domains_from_payload,
    _extract_embedded_http_url,
    _extract_source_url,
    _has_valid_value,
    _is_estimated_allowlisted_entry,
    _is_https_url_evidence,
    _is_placeholder_numeric,
    _is_url_evidence_terminator,
    _iter_http_like_evidence,
    _iter_url_like_evidence,
    _issue_signature,
    _merge_quality_issues,
    _normalize_parseable_http_url,
    _pct_change,
    _policy_rules,
    _same_numeric_value,
)
from datasource.engines.stage2_5.manual_official import (  # noqa: F401 (C4 re-export)
    OFFICIAL_MANUAL_NOTE,
    OFFICIAL_MANUAL_SOURCES,
    TRUSTED_MONETARY_MANUAL_QUALITY_DOMAINS,
    _apply_manual_official_estimation_rule,
    _has_invalid_explicit_url_evidence,
    _has_multi_value_explicit_url_evidence,
    _has_rrr_type_conflict,
    _is_manual_official_value,
    _is_trusted_monetary_manual_quality_override,
    _iter_explicit_url_evidence,
    _normalize_manual_official_key,
    _normalize_rrr_type,
    _official_domain_matches,
    _should_preserve_existing_official_source,
    _single_trusted_explicit_https_url,
)
from datasource.engines.stage2_5.fund_flow import (  # noqa: F401 (C4 re-export)
    FUND_FLOW_DIRECT_WINDOW_EVIDENCE,
    FUND_FLOW_ESTIMATED_METRIC_BASIS,
    FUND_FLOW_TIER1_DOMAINS,
    FUND_FLOW_TIER2_STRUCTURED_PATHS,
    FUND_FLOW_TIER3_DOMAINS,
    FUND_FLOW_WEAK_WINDOW_EVIDENCE,
    _default_fund_flow_metric_basis,
    _domain_matches,
    _fund_flow_has_trusted_window,
    _infer_fund_flow_source_tier,
    _infer_fund_flow_window_evidence,
    _is_fund_flow_tier2_structured_source,
    _normalize_fund_flow_estimation,
    _normalize_fund_flow_payload,
    _normalize_source_tier,
    _normalize_window_evidence,
    _parse_url_domain_path,
    _path_matches_prefix,
)
from datasource.engines.stage2_5.schema_coercion import (  # noqa: F401 (C4 re-export)
    _coerce_stage2_results_to_schema,
    _copy_payload_metadata_fields,
    _copy_source_url,
    _normalize_keyed_list,
    _normalize_monetary_payload,
)
from datasource.engines.stage2_5.gap_sync import (  # noqa: F401 (C4 re-export)
    _append_missing_item,
    _cleanup_metadata_missing,
    _collect_missing_source_urls,
    _collect_unresolved_gap_items,
    _is_missing_item_filled,
    _refresh_stage2_gap_monitor,
    _refresh_stage2_notes,
    _remove_missing_item,
    _remove_top_missing,
    _remove_top_missing_on_skip,
    _rewrite_gap_monitor_after_injection,
)

FUND_FLOW_KEY_MAP = {
    "etf_flow": "etf",
    "margin_trading": "margin",
}

MONETARY_KEY_MAP = MONETARY_KEY_ALIASES

# 宏观指标键名映射：注入脚本键名 → Stage2/market_data 规范键名
MACRO_KEY_MAP = {
    "industrial_production": "industrial",  # 常见混淆
    "industrial_output": "industrial",
}

DEFAULT_SOURCE_LABEL = "websearch_manual"
SOURCE_ANOMALY_LABEL = "异常零值-需核查"

@dataclass
class InjectionSummary:
    injected_items: List[Dict[str, Any]] = field(default_factory=list)
    metadata_updated_items: List[Dict[str, Any]] = field(default_factory=list)
    skipped_existing_items: List[Dict[str, Any]] = field(default_factory=list)
    skipped_no_parseable_value_items: List[Dict[str, Any]] = field(default_factory=list)
    forced_override_items: List[Dict[str, Any]] = field(default_factory=list)
    fund_flow_forced_estimated_items: List[Dict[str, Any]] = field(default_factory=list)

    def _record(self, bucket: List[Dict[str, Any]], category: str, key: str, **details: Any) -> None:
        item = {"category": category, "key": str(key)}
        item.update({k: v for k, v in details.items() if v is not None})
        bucket.append(item)

    def injected(self, category: str, key: str, **details: Any) -> None:
        self._record(self.injected_items, category, key, **details)

    def metadata_updated(
        self, category: str, key: str, reason: str, existing: Any, incoming: Any
    ) -> None:
        self._record(
            self.metadata_updated_items,
            category,
            key,
            reason=reason,
            existing_value=existing,
            incoming_value=incoming,
        )

    def skipped_existing(
        self, category: str, key: str, reason: str, existing: Any, incoming: Any
    ) -> None:
        self._record(
            self.skipped_existing_items,
            category,
            key,
            reason=reason,
            existing_value=existing,
            incoming_value=incoming,
        )

    def skipped_no_parseable_value(self, category: str, key: str, **details: Any) -> None:
        self._record(self.skipped_no_parseable_value_items, category, key, **details)

    def forced_override(self, category: str, key: str, existing: Any, incoming: Any) -> None:
        self._record(
            self.forced_override_items,
            category,
            key,
            reason="force_override",
            existing_value=existing,
            incoming_value=incoming,
        )

    def fund_flow_forced_estimated(self, category: str, key: str, **details: Any) -> None:
        self._record(self.fund_flow_forced_estimated_items, category, key, **details)

    def to_dict(self) -> Dict[str, Any]:
        buckets = {
            "injected": self.injected_items,
            "metadata_updated": self.metadata_updated_items,
            "skipped_existing": self.skipped_existing_items,
            "skipped_no_parseable_value": self.skipped_no_parseable_value_items,
            "forced_override": self.forced_override_items,
            "fund_flow_forced_estimated": self.fund_flow_forced_estimated_items,
        }
        return {
            "counts": {name: len(items) for name, items in buckets.items()},
            **{name: list(items) for name, items in buckets.items()},
        }


def _append_non_blocking_warning(market_data: Dict[str, Any], warning: Dict[str, Any]) -> None:
    metadata = market_data.setdefault("metadata", {})
    warnings = metadata.setdefault("non_blocking_warnings", [])
    if not isinstance(warnings, list):
        warnings = []
        metadata["non_blocking_warnings"] = warnings
    signature = (
        warning.get("code"),
        warning.get("key"),
        warning.get("source_url"),
        warning.get("message"),
    )
    for existing in warnings:
        if not isinstance(existing, dict):
            continue
        if (
            existing.get("code"),
            existing.get("key"),
            existing.get("source_url"),
            existing.get("message"),
        ) == signature:
            return
    warnings.append(warning)


def _collect_gc_non_blocking_warnings(
    market_data: Dict[str, Any],
    websearch_raw: Dict[str, Any],
) -> List[Dict[str, Any]]:
    warning_rules = get_non_blocking_warning_rules(_policy_rules())
    risk_domains = [str(d).lower() for d in (warning_rules.get("gc_f_risk_domains") or []) if str(d).strip()]
    anomaly_threshold = float(warning_rules.get("gc_f_anomaly_threshold_pct") or 8.0)
    warnings: List[Dict[str, Any]] = []

    for item in websearch_raw.get("results", []) if isinstance(websearch_raw, dict) else []:
        task = item.get("task", {}) if isinstance(item, dict) else {}
        if task.get("indicator_key") != "GC=F":
            continue
        extraction = item.get("extraction", {}) if isinstance(item, dict) else {}
        source_url = extraction.get("source_url")
        if not source_url:
            raw_results = item.get("raw_results") or []
            if raw_results and isinstance(raw_results[0], dict):
                source_url = raw_results[0].get("url")

        domain = _extract_domain(source_url)
        if domain and any(domain.endswith(d) for d in risk_domains):
            warnings.append(
                {
                    "level": "warning",
                    "code": "gc_f_source_risk",
                    "key": "GC=F",
                    "source_url": source_url,
                    "message": f"GC=F 来源域名风险: {domain}",
                }
            )

        value = _coerce_float(extraction.get("value"))
        if value is None:
            continue
        for comm in market_data.get("commodities", []) or []:
            if not isinstance(comm, dict) or comm.get("symbol") != "GC=F":
                continue
            prev_price = _coerce_float(comm.get("current_price"))
            if prev_price is None or abs(prev_price) < 1e-9:
                continue
            pct = (value - prev_price) / abs(prev_price) * 100.0
            if abs(pct) >= anomaly_threshold:
                warnings.append(
                    {
                        "level": "warning",
                        "code": "gc_f_price_anomaly",
                        "key": "GC=F",
                        "source_url": source_url,
                        "message": f"GC=F 价格变动 {pct:.2f}% 超过阈值 {anomaly_threshold:.1f}%",
                    }
                )
            break

    return warnings


def _derive_date_compact(payload: Dict[str, Any], override: Optional[str] = None) -> str:
    """从元数据推导 YYYYMMDD 字符串，支持外部覆盖。"""
    if override:
        return str(override).replace("-", "")
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    date_val = metadata.get("date") or metadata.get("end_date") or metadata.get("start_date")
    if date_val:
        return str(date_val).replace("-", "")
    return datetime.now().strftime("%Y%m%d")


def _enforce_quality_blockers(market_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    严格质量门禁：
    1) 当前值已填但对比值缺失（macro previous/change；monetary 120d change）；
    2) 当前值为估算值（is_estimated=True，白名单除外）；
    3) ETF 资金流窗口值缺失（recent_5d/total_120d 任一缺失）。
    """
    blockers: List[Dict[str, str]] = []

    def _add(category: str, key: str, reason: str) -> None:
        record = {"category": category, "key": key, "reason": reason}
        if record in blockers:
            return
        blockers.append(record)
        _append_missing_item(market_data, category, key, reason)

    for key, entry in (market_data.get("macro_indicators", {}) or {}).items():
        if not isinstance(entry, dict):
            continue
        if _has_valid_value(entry.get("current_value")):
            if entry.get("is_estimated") and not _is_estimated_allowlisted_entry("macro_indicators", str(key), entry):
                _add("macro_indicators", key, "estimated_not_allowed")
            if entry.get("previous_value") is None or entry.get("change_rate") is None:
                _add("macro_indicators", key, "missing_compare_values")

    for key, entry in (market_data.get("monetary_policy", {}) or {}).items():
        if not isinstance(entry, dict):
            continue
        if _has_valid_value(entry.get("current_value")):
            if entry.get("is_estimated") and not _is_estimated_allowlisted_entry("monetary_policy", str(key), entry):
                _add("monetary_policy", key, "estimated_not_allowed")
            if entry.get("change_from_120d") is None:
                _add("monetary_policy", key, "missing_compare_values")

    for bond in market_data.get("bonds", []) or []:
        if not isinstance(bond, dict):
            continue
        symbol = bond.get("symbol")
        if (
            symbol
            and _has_valid_value(bond.get("current_yield"))
            and bond.get("is_estimated")
            and not _is_estimated_allowlisted_entry("bonds", str(symbol), bond)
        ):
            _add("bonds", str(symbol), "estimated_not_allowed")

    for fx in market_data.get("forex", []) or []:
        if not isinstance(fx, dict):
            continue
        pair = fx.get("pair")
        if (
            pair
            and _has_valid_value(fx.get("current_rate"))
            and fx.get("is_estimated")
            and not _is_estimated_allowlisted_entry("forex", str(pair), fx)
        ):
            _add("forex", str(pair), "estimated_not_allowed")

    for comm in market_data.get("commodities", []) or []:
        if not isinstance(comm, dict):
            continue
        symbol = comm.get("symbol")
        if (
            symbol
            and _has_valid_value(comm.get("current_price"))
            and comm.get("is_estimated")
            and not _is_estimated_allowlisted_entry("commodities", str(symbol), comm)
        ):
            _add("commodities", str(symbol), "estimated_not_allowed")

    for idx in market_data.get("stock_indices", []) or []:
        if not isinstance(idx, dict):
            continue
        symbol = idx.get("symbol")
        if (
            symbol
            and _has_valid_value(idx.get("current_price"))
            and idx.get("is_estimated")
            and not _is_estimated_allowlisted_entry("stock_indices", str(symbol), idx)
        ):
            _add("stock_indices", str(symbol), "estimated_not_allowed")

    for flow_key, flow in (market_data.get("fund_flow", {}) or {}).items():
        if not isinstance(flow, dict):
            continue
        if str(flow_key) != "etf":
            continue
        if not (_has_valid_value(flow.get("recent_5d")) and _has_valid_value(flow.get("total_120d"))):
            _add("fund_flow", str(flow_key), "fund_flow_window_missing")

    market_data.setdefault("metadata", {})["quality_blockers"] = blockers
    return blockers


def _write_unified_quality_artifacts(
    market_data: Dict[str, Any],
    state: Dict[str, Any],
    *,
    quality_metrics_path: Path,
    policy_evaluation_path: Path,
    gap_monitor_path: Optional[Path],
) -> None:
    gap_view = state.get("gap_monitor_view", {}) if isinstance(state, dict) else {}
    gap_payload = {
        "generated_at": datetime.now().isoformat(),
        "manual_required": list(gap_view.get("manual_required") or []),
        "pending_tasks": list(gap_view.get("pending_tasks") or []),
        "data_quality_issues": list(state.get("quality_blockers") or []),
        "quality_blockers": list(state.get("quality_blockers") or []),
    }
    if gap_monitor_path is not None:
        gap_monitor_path.parent.mkdir(parents=True, exist_ok=True)
        gap_monitor_path.write_text(json.dumps(gap_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    quality_payload = build_quality_metrics(market_data)
    quality_payload.update(
        {
            "missing_items": state.get("missing_items") or {},
            "quality_blockers": state.get("quality_blockers") or [],
            "source_url_issues": state.get("source_url_issues") or [],
            "window_metric_issues": state.get("window_metric_issues") or [],
            "manual_required": state.get("manual_required") or [],
            "policy_evaluation": state.get("policy_evaluation") or {},
        }
    )
    quality_metrics_path.parent.mkdir(parents=True, exist_ok=True)
    quality_metrics_path.write_text(json.dumps(quality_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    policy_evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    policy_evaluation_path.write_text(
        json.dumps(state.get("policy_evaluation") or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _cleanup_monetary_aliases(market_data: Dict[str, Any], metadata: Dict[str, Any]) -> None:
    """清理货币政策别名重复项（canonical 有值、alias 仍为占位时删除 alias）。"""
    section = market_data.get('monetary_policy', {}) if isinstance(market_data, dict) else {}
    if not isinstance(section, dict):
        return
    for alias, canonical in MONETARY_KEY_MAP.items():
        if alias == canonical:
            continue
        if alias not in section or canonical not in section:
            continue
        alias_entry = section.get(alias) or {}
        canonical_entry = section.get(canonical) or {}
        if _has_valid_value(canonical_entry.get('current_value')) and not _has_valid_value(alias_entry.get('current_value')):
            section.pop(alias, None)
            _remove_missing_item(metadata, 'monetary_policy', alias)
            _remove_top_missing(market_data, alias)



def inject_websearch_data(
    market_data_path,
    websearch_path,
    output_path,
    *,
    backfill_trend: bool = True,
    date_override: Optional[str] = None,
    gap_monitor_path: Optional[Path] = None,
    override_stale: bool = True,
    force_override: bool = False,
    trend_history_base_dir: Optional[Path] = None,
    disable_trend_history_write: bool = False,
):
    """
    将WebSearch结果注入到市场数据JSON中

    Args:
        market_data_path: 市场数据JSON路径
        websearch_path: WebSearch结果JSON路径
        output_path: 输出路径
    """

    # 读取市场数据
    print(f"[INFO] 读取市场数据: {market_data_path}")
    with open(market_data_path, 'r', encoding='utf-8') as f:
        market_data = json.load(f)
    metadata = market_data.setdefault('metadata', {})
    if isinstance(market_data.get("monetary_policy"), dict):
        market_data["monetary_policy"] = normalize_monetary_section(market_data.get("monetary_policy"))
    run_paths = build_run_paths_from_reference(
        date=date_override,
        payload=market_data,
        path=market_data_path,
        fallback_to_today=True,
    )
    trend_base_dir = trend_history_base_dir or (None if disable_trend_history_write else DEFAULT_BASE_DIR)

    # 读取WebSearch结果
    print(f"[INFO] 读取WebSearch结果: {websearch_path}")
    with open(websearch_path, 'r', encoding='utf-8') as f:
        websearch_raw = json.load(f)
    is_stage2_results = isinstance(websearch_raw, dict) and isinstance(websearch_raw.get("results"), list)
    # 若为 Stage2 results 结构，先转换为 schema
    websearch_data = _coerce_stage2_results_to_schema(websearch_raw)
    # 统一结构，容忍 {symbol: {...}} / list / None
    websearch_data['forex'] = _normalize_keyed_list(websearch_data.get('forex'), 'pair')
    websearch_data['bonds'] = _normalize_keyed_list(websearch_data.get('bonds'), 'symbol')
    websearch_data['commodities'] = _normalize_keyed_list(websearch_data.get('commodities'), 'symbol')
    websearch_data['stock_indices'] = _normalize_keyed_list(websearch_data.get('stock_indices'), 'symbol')
    websearch_data['monetary_policy'] = _normalize_monetary_payload(websearch_data.get('monetary_policy'))

    gc_warnings: List[Dict[str, Any]] = []
    if is_stage2_results:
        gc_warnings = _collect_gc_non_blocking_warnings(market_data, websearch_raw)
        for warning in gc_warnings:
            _append_non_blocking_warning(market_data, warning)
    is_manual = "manual" in Path(websearch_path).name.lower() and not is_stage2_results
    if is_manual:
        missing_urls = _collect_missing_source_urls(websearch_data)
        if missing_urls:
            raise ValueError(
                "manual.json 缺少 WebSearch 来源 URL: "
                + ", ".join(missing_urls)
                + "。请为每个已填写数值的条目补充 source_url 或在 source/note 中提供 URL。"
            )
        # 将 source_url 绑定到 source，便于审计
        for entry in websearch_data.get("commodities", []) or []:
            _attach_source_url(entry)
        for entry in websearch_data.get("forex", []) or []:
            _attach_source_url(entry)
        for entry in websearch_data.get("bonds", []) or []:
            _attach_source_url(entry)
        for entry in websearch_data.get("stock_indices", []) or []:
            _attach_source_url(entry)
        for payload in (websearch_data.get("macro_indicators") or {}).values():
            _attach_source_url(payload)
        for payload in (websearch_data.get("monetary_policy") or {}).values():
            _attach_source_url(payload)
        for payload in (websearch_data.get("fund_flow") or {}).values():
            _attach_source_url(payload)

    inject_count = 0
    summary = InjectionSummary()

    # 1. 注入宏观指标
    print("\n[STEP 1] 注入宏观指标数据...")
    macro_section = market_data.setdefault('macro_indicators', {})
    for raw_key, payload in websearch_data.get('macro_indicators', {}).items():
        key = MACRO_KEY_MAP.get(raw_key, raw_key)  # 键名规范化
        if key not in macro_section:
            # 缺失即创建占位，避免 industrial_sales 等被跳过
            macro_section[key] = _create_macro_placeholder(key, payload, metadata)
        metadata_updated_before = len(summary.metadata_updated_items)
        updated = _apply_macro_entry(
            key,
            macro_section[key],
            payload,
            metadata.get('date'),
            is_manual=is_manual,
            override_stale=override_stale,
            force_override=force_override,
            trend_history_base_dir=trend_base_dir,
            summary=summary,
        )
        if updated:
            if len(summary.metadata_updated_items) == metadata_updated_before:
                inject_count += 1
            print(f"  [OK] {payload.get('indicator_name', key)}: {payload.get('current_value')} {payload.get('unit', '')}".strip())
            _remove_missing_item(metadata, 'macro_indicators', key)
            _remove_top_missing(market_data, key)
        else:
            _remove_top_missing_on_skip(market_data, key, macro_section.get(key))

    # 2. 注入货币政策
    print("\n[STEP 2] 注入货币政策数据...")
    monetary_section = market_data.setdefault('monetary_policy', {})
    for raw_key, payload in websearch_data.get('monetary_policy', {}).items():
        key = MONETARY_KEY_MAP.get(raw_key, raw_key)
        if key not in monetary_section:
            monetary_section[key] = _create_monetary_placeholder(key, payload, metadata)
        metadata_updated_before = len(summary.metadata_updated_items)
        updated = _apply_monetary_entry(
            key,
            monetary_section[key],
            payload,
            metadata.get('date'),
            is_manual=is_manual,
            override_stale=override_stale,
            force_override=force_override,
            trend_history_base_dir=trend_base_dir,
            summary=summary,
        )
        if updated:
            if len(summary.metadata_updated_items) == metadata_updated_before:
                inject_count += 1
            print(f"  [OK] {payload.get('policy_name', key)}: {payload.get('current_value')} {payload.get('unit', '')}".strip())
            _remove_missing_item(metadata, 'monetary_policy', key)
            _remove_top_missing(market_data, key)
        else:
            _remove_top_missing_on_skip(market_data, key, monetary_section.get(key))
    _cleanup_monetary_aliases(market_data, metadata)
    market_data["monetary_policy"] = normalize_monetary_section(market_data.get("monetary_policy"))

    # 3. 注入资金流向（标准化为浮点+统一来源）
    print("\n[STEP 3] 注入资金流向数据...")
    for raw_key, payload in websearch_data.get('fund_flow', {}).items():
        key = FUND_FLOW_KEY_MAP.get(raw_key, raw_key)
        if key not in market_data.get('fund_flow', {}):
            continue
        normalized_payload = _normalize_fund_flow_payload(raw_key, payload)
        if _apply_fund_flow_entry(market_data['fund_flow'][key], key, normalized_payload, summary=summary):
            inject_count += 1
            summary.injected("fund_flow", key)
            print(
                f"  [OK] {key}: recent_5d={market_data['fund_flow'][key]['recent_5d']} "
                f"total_120d={market_data['fund_flow'][key]['total_120d']} source={market_data['fund_flow'][key]['source']}"
            )
            _remove_missing_item(metadata, 'fund_flow', key)
            _remove_top_missing(market_data, key)
        else:
            summary.skipped_no_parseable_value("fund_flow", key)

    # 4. 注入外汇数据
    print("\n[STEP 4] 注入外汇数据...")
    forex_iterable = websearch_data.get('forex') or []

    market_forex = market_data.setdefault('forex', [])
    for fx in forex_iterable:
        pair = fx.get('pair') or fx.get('symbol')
        if not pair:
            continue
        updated = False
        for i, item in enumerate(market_forex):
            if item.get('pair') == pair:
                market_forex[i] = _merge_forex_entry(
                    item,
                    fx,
                    is_manual=is_manual,
                    trend_history_base_dir=trend_base_dir,
                )
                updated = True
                break
        if not updated:
            market_forex.append(_build_forex_entry(fx, is_manual=is_manual, trend_history_base_dir=trend_base_dir))
        inject_count += 1
        summary.injected("forex", pair)
        print(f"  [OK] {fx.get('name', pair)}: {fx.get('current_rate')} (source={fx.get('source')})")
        _remove_missing_item(metadata, 'forex', pair)
        _remove_top_missing(market_data, pair)

    # 5. 注入股票指数（含 000016 等补全）
    print("\n[STEP 5] 注入股票指数数据...")
    stock_indices_iterable = websearch_data.get('stock_indices') or []
    stock_indices_section = market_data.setdefault('stock_indices', [])
    for idx_payload in stock_indices_iterable:
        symbol = idx_payload.get('symbol')
        if not symbol:
            print("  [WARN] stock_index 缺少 symbol，已跳过")
            continue
        price = _coerce_float(idx_payload.get('current_price') or idx_payload.get('close') or idx_payload.get('price'))
        if price is None:
            print(f"  [WARN] {symbol} 缺少可解析价格，跳过注入")
            summary.skipped_no_parseable_value("stock_indices", symbol)
            continue
        merged = False
        for i, existing in enumerate(stock_indices_section):
            if existing.get('symbol') == symbol:
                stock_indices_section[i] = _merge_stock_index_entry(existing, idx_payload)
                merged = True
                break
        if not merged:
            stock_indices_section.append(_build_stock_index_entry(symbol, idx_payload))
        inject_count += 1
        summary.injected("stock_indices", symbol)
        print(f"  [OK] {idx_payload.get('name', symbol)}: {price}")
        _remove_missing_item(metadata, 'stock_indices', symbol)
        _remove_top_missing(market_data, symbol)

    # 6. 注入债券收益率
    print("\n[STEP 6] 注入债券收益率数据...")
    bond_iterable = websearch_data.get('bonds') or []

    for bond_data in bond_iterable:
        symbol = bond_data.get('symbol')
        if not symbol:
            print("  [WARN] bond 缺少 symbol，已跳过")
            continue
        bond_data.setdefault('name', symbol)
        bond_data['current_yield'] = _coerce_float(bond_data.get('current_yield'))
        if bond_data['current_yield'] is None:
            print(f"  [WARN] {symbol} 缺少 current_yield，跳过注入")
            summary.skipped_no_parseable_value("bonds", symbol)
            continue
        # 在bonds列表中找到对应项并更新
        updated = False
        for i, bond in enumerate(market_data['bonds']):
            if bond.get('symbol') == symbol:
                market_data['bonds'][i] = _merge_bond_entry(
                    bond,
                    bond_data,
                    is_manual=is_manual,
                    trend_history_base_dir=trend_base_dir,
                )
                inject_count += 1
                summary.injected("bonds", symbol)
                print(f"  [OK] {bond_data['name']}: {bond_data['current_yield']}%")
                _remove_missing_item(metadata, 'bonds', symbol)
                _remove_top_missing(market_data, symbol)
                updated = True
                break
        if not updated:
            merged_entry = _merge_bond_entry(
                {},
                bond_data,
                is_manual=is_manual,
                trend_history_base_dir=trend_base_dir,
            )
            market_data.setdefault('bonds', []).append(merged_entry)
            inject_count += 1
            summary.injected("bonds", symbol)
            _remove_missing_item(metadata, 'bonds', symbol)
            _remove_top_missing(market_data, symbol)

    # 7. 注入商品价格
    print("\n[STEP 7] 注入商品价格数据...")
    commodity_iterable = websearch_data.get('commodities') or []

    for commodity_data in commodity_iterable:
        symbol = commodity_data.get('symbol')
        if not symbol:
            print("  [WARN] commodity 缺少 symbol，已跳过")
            continue
        commodity_data.setdefault('name', symbol)
        commodity_data['current_price'] = _coerce_float(commodity_data.get('current_price'))
        if commodity_data['current_price'] is None:
            print(f"  [WARN] {symbol} 缺少 current_price，跳过注入")
            summary.skipped_no_parseable_value("commodities", symbol)
            continue
        # 在commodities列表中找到对应项并更新
        updated = False
        for i, commodity in enumerate(market_data['commodities']):
            if commodity.get('symbol') == symbol:
                market_data['commodities'][i] = _merge_commodity_entry(
                    commodity,
                    commodity_data,
                    is_manual=is_manual,
                    trend_history_base_dir=trend_base_dir,
                )
                updated = True
                break
        if not updated:
            market_data.setdefault('commodities', []).append(
                _merge_commodity_entry(
                    {},
                    commodity_data,
                    is_manual=is_manual,
                    trend_history_base_dir=trend_base_dir,
                )
            )
        inject_count += 1
        summary.injected("commodities", symbol)
        price_val = commodity_data.get('current_price') or 0.0
        ytd_val = commodity_data.get('ytd_change') or 0.0
        print(f"  [OK] {commodity_data['name']}: {commodity_data.get('unit','')}{price_val:.2f} (YTD {ytd_val:+.2f}%)")
        _remove_missing_item(metadata, 'commodities', symbol)
        _remove_top_missing(market_data, symbol)

    # 注入完成后回读 trend_history 补齐缺失变化值（默认开启）
    if backfill_trend and trend_base_dir is not None:
        try:
            backfill_stats = _backfill_trend_changes(market_data, base_dir=trend_base_dir)
            total_backfilled = sum(backfill_stats.values())
            if total_backfilled:
                print(f"  - trend_history backfill: {backfill_stats}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] trend_history backfill failed: {exc}")

    # 更新元数据
    metadata_section = websearch_data.get('metadata', {})
    # 按实际数据重新计算完整度：非占位/非零的数据占比
    def _is_filled(val: Any) -> bool:
        if val in (None, "", "N/A"):
            return False
        try:
            if isinstance(val, (int, float)):
                return abs(val) > 1e-9
        except Exception:
            pass
        return True

    filled = 0
    total = 0
    # commodities
    for item in market_data.get('commodities', []):
        total += 1
        filled += 1 if _is_filled(item.get('current_price')) else 0
    # forex
    for item in market_data.get('forex', []):
        total += 1
        filled += 1 if _is_filled(item.get('current_rate')) else 0
    # bonds
    for item in market_data.get('bonds', []):
        total += 1
        filled += 1 if _is_filled(item.get('current_yield')) else 0
    # stock indices
    for item in market_data.get('stock_indices', []):
        total += 1
        filled += 1 if _is_filled(item.get('current_price')) else 0
    # fund flow
    for item in market_data.get('fund_flow', {}).values():
        total += 1
        filled += 1 if _is_filled(item.get('recent_5d')) and _is_filled(item.get('total_120d')) else 0
    # macro & monetary
    for section in ('macro_indicators', 'monetary_policy'):
        for entry in market_data.get(section, {}).values():
            total += 1
            filled += 1 if _is_filled(entry.get('current_value')) else 0

    metadata['data_completeness'] = round(filled / total, 3) if total else 1.0
    metadata['ai_websearch_enhanced'] = True
    collection_time = websearch_data.get('collection_time') or metadata_section.get('collection_time')
    if collection_time:
        metadata['websearch_timestamp'] = collection_time

    # 根据已有数据再清理一次顶层 missing_items，避免遗留占位符
    for key in list(market_data.get('missing_items', [])):
        if isinstance(key, dict):
            key_val = key.get('key') or key.get('indicator_key')
        else:
            key_val = key
        if not key_val:
            continue
        _remove_top_missing(market_data, key_val)
    # 同步根据已填充的 stock_indices 清理缺口
    for idx in market_data.get('stock_indices', []):
        _remove_top_missing(market_data, idx.get('symbol'))
    _cleanup_metadata_missing(metadata, market_data)
    quality_state = _apply_pipeline_quality_state(market_data)
    quality_blockers = quality_state.get("quality_blockers") or []

    gap_summary = _refresh_stage2_gap_monitor(market_data)
    _refresh_stage2_notes(metadata, gap_summary)
    quality_state = _apply_pipeline_quality_state(market_data)
    quality_blockers = quality_state.get("quality_blockers") or []

    metadata["injection_summary"] = summary.to_dict()

    # 保存到输出文件
    print(f"\n[INFO] 保存完整数据到: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(market_data, f, ensure_ascii=False, indent=2)

    summary_counts = metadata["injection_summary"]["counts"]
    print(f"\n[SUCCESS] 数据注入完成！")
    print(f"  - 注入数据项: {inject_count}")
    print(f"  - 元数据更新项: {summary_counts.get('metadata_updated', 0)}")
    print(f"  - 已有值跳过项: {summary_counts.get('skipped_existing', 0)}")
    print(f"  - 资金流强制估算项: {summary_counts.get('fund_flow_forced_estimated', 0)}")
    print(f"  - 数据完整性: {market_data['metadata']['data_completeness']:.1%}")
    print(f"  - 输出文件: {output_path}")
    if quality_blockers:
        print(f"  [WARN] 质量阻断项: {len(quality_blockers)}（需通过 Stage2/Stage2.5 补齐真实值/对比值）")
        for blocker in quality_blockers:
            print(f"    - {blocker.get('category')}.{blocker.get('key')}: {blocker.get('reason')}")

    if gc_warnings:
        print(f"  [WARN] 非阻断告警: {len(gc_warnings)}")
        for warning in gc_warnings:
            print(f"    - {warning.get('code')}: {warning.get('message')}")
    # Final write to trend_history (post Stage2.5)
    if disable_trend_history_write:
        print("  - trend_history final write: disabled")
    else:
        try:
            write_count = write_from_market_data(
                market_data,
                is_partial=False,
                source_path=output_path,
                base_dir=trend_base_dir,
            )
            print(f"  - trend_history final write: {write_count} items")
            try:
                write_trend_history_gap_snapshot(
                    run_paths.date,
                    run_paths.trend_history_gap,
                    base_dir=trend_base_dir,
                )
                print(f"  - trend_history gap snapshot refreshed: {run_paths.trend_history_gap}")
            except Exception as exc:  # noqa: BLE001
                print(f"  [WARN] trend_history gap snapshot refresh failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"  - trend_history final write failed: {exc}")

    # Post-write backfill: use freshly written trend_history details to recompute change fields.
    if backfill_trend and trend_base_dir is not None:
        try:
            post_stats = _run_post_write_trend_backfill(
                market_data,
                Path(output_path),
                base_dir=trend_base_dir,
            )
            post_total = sum(post_stats.values())
            if post_total:
                print(f"  - trend_history post-write backfill: {post_stats}")
            else:
                print("  - trend_history post-write backfill: no updates")
            quality_state = _apply_pipeline_quality_state(market_data)
            quality_blockers = quality_state.get("quality_blockers") or []
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(market_data, f, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] trend_history post-write backfill failed: {exc}")

    # Refresh unified quality artifacts after manual injection
    try:
        quality_path = run_paths.quality_metrics
        policy_path = run_paths.policy_evaluation
        target_gap_path = gap_monitor_path or run_paths.gap_monitor
        _write_unified_quality_artifacts(
            market_data,
            quality_state,
            quality_metrics_path=quality_path,
            policy_evaluation_path=policy_path,
            gap_monitor_path=target_gap_path,
        )
        print(f"  - quality_metrics refreshed: {quality_path}")
        print(f"  - policy_evaluation refreshed: {policy_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"  - unified quality artifacts refresh failed: {exc}")

    # Post-injection validation: check for remaining estimated values
    _post_injection_validation(market_data)
    _sync_backfill_issues_to_logs(
        market_data,
        date_override=date_override,
        gap_monitor_path=gap_monitor_path,
    )

    return output_path


def inject_websearch_results(*args, **kwargs):
    return inject_websearch_data(*args, **kwargs)


def _post_injection_validation(market_data: Dict[str, Any]) -> None:
    """注入后校验，打印仍为估计值的字段。

    检查 bonds, macro_indicators, monetary_policy 中 is_estimated=True 的条目，
    作为 CI 检查点警示数据质量问题。
    """
    estimated_fields: List[str] = []

    # Check bonds
    for bond in market_data.get('bonds', []) or []:
        if bond.get('is_estimated'):
            name = bond.get('name') or bond.get('symbol') or 'unknown'
            estimated_fields.append(f"bonds.{name}")

    # Check macro_indicators
    for key, entry in (market_data.get('macro_indicators', {}) or {}).items():
        if isinstance(entry, dict) and entry.get('is_estimated'):
            name = entry.get('indicator_name') or key
            estimated_fields.append(f"macro_indicators.{name}")

    # Check monetary_policy
    for key, entry in (market_data.get('monetary_policy', {}) or {}).items():
        if isinstance(entry, dict) and entry.get('is_estimated'):
            name = entry.get('policy_name') or key
            estimated_fields.append(f"monetary_policy.{name}")

    # Check commodities
    for comm in market_data.get('commodities', []) or []:
        if comm.get('is_estimated'):
            name = comm.get('name') or comm.get('symbol') or 'unknown'
            estimated_fields.append(f"commodities.{name}")

    # Check forex
    for fx in market_data.get('forex', []) or []:
        if fx.get('is_estimated'):
            name = fx.get('name') or fx.get('pair') or 'unknown'
            estimated_fields.append(f"forex.{name}")

    # Print validation result
    print("\n[VALIDATION] 估计值校验:")
    if estimated_fields:
        print(f"  [WARN] 仍有 {len(estimated_fields)} 个估计值字段:")
        for field in estimated_fields:
            print(f"    - {field}")
    else:
        print("  [OK] 所有字段已去除估计值标记")


def _format_source_label(raw_source: Optional[str]) -> str:
    source_text = str(raw_source or "").strip()
    if not source_text:
        return DEFAULT_SOURCE_LABEL
    if source_text == SOURCE_ANOMALY_LABEL:
        return source_text
    if source_text == DEFAULT_SOURCE_LABEL or source_text.startswith(f"{DEFAULT_SOURCE_LABEL}("):
        return source_text
    lower_source = source_text.lower()
    if "manual_required" in lower_source or "websearch_manual" in lower_source:
        return DEFAULT_SOURCE_LABEL
    if "tavily" in lower_source or "deepseek" in lower_source or source_text == DEFAULT_SOURCE_LABEL:
        return source_text
    if source_text.startswith("http"):
        return f"{DEFAULT_SOURCE_LABEL}({source_text})"
    return f"{DEFAULT_SOURCE_LABEL}({source_text})"


def _update_metadata_only(entry: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    changed = False
    preserve_existing_official_source = _should_preserve_existing_official_source(entry, payload)

    def set_if_changed(field: str, value: Any) -> None:
        nonlocal changed
        if value is None:
            return
        if entry.get(field) != value:
            entry[field] = value
            changed = True

    incoming_date = payload.get("date") or payload.get("as_of_date") or payload.get("report_period")
    if incoming_date:
        set_if_changed("date", incoming_date)
    if payload.get("as_of_date") or payload.get("report_period"):
        set_if_changed("as_of_date", payload.get("as_of_date") or payload.get("report_period"))
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

        rrr_type_conflict = _has_rrr_type_conflict(entry, payload) if key in {"rrr", "reserve_ratio"} else False
        incoming_rrr_type = _normalize_rrr_type(payload.get("rrr_type") or payload.get("value_type"))
        if not rrr_type_conflict:
            set_if_changed("rrr_type", incoming_rrr_type)

        if is_manual:
            before_estimated = entry.get("is_estimated")
            before_note = entry.get("note")
            _apply_manual_official_estimation_rule(category, key, payload, entry)
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


_contains_ytd_marker = contains_ytd_marker


def _apply_macro_entry(
    indicator_key: str,
    entry: Dict[str, Any],
    payload: Dict[str, Any],
    reference_date: Optional[str],
    *,
    is_manual: bool = False,
    override_stale: bool = True,
    force_override: bool = False,
    trend_history_base_dir: Optional[Path] = DEFAULT_BASE_DIR,
    summary: Optional[InjectionSummary] = None,
) -> bool:
    if not isinstance(entry, dict):
        return False
    original_current_value = entry.get("current_value")
    incoming_current_value = _coerce_float(payload.get("current_value"))
    existing_placeholder = _is_placeholder_numeric(entry.get("current_value"))
    existing_stale = bool(entry.get("is_stale"))
    if not force_override and not existing_placeholder and not (override_stale and existing_stale):
        if _same_numeric_value(original_current_value, incoming_current_value):
            if _merge_same_value_report_fields(
                entry,
                payload,
                category="macro_indicators",
                key=indicator_key,
                is_manual=is_manual,
                override_stale=override_stale,
            ):
                if summary is not None:
                    summary.metadata_updated(
                        "macro_indicators",
                        indicator_key,
                        "same_numeric_value_report_fields_merged",
                        original_current_value,
                        incoming_current_value,
                    )
                return True
        if summary is not None:
            if incoming_current_value is None:
                summary.skipped_no_parseable_value("macro_indicators", indicator_key)
            else:
                summary.skipped_existing(
                    "macro_indicators",
                    indicator_key,
                    "existing_value_present",
                    original_current_value,
                    incoming_current_value,
                )
        return False
    entry['indicator_name'] = payload.get('indicator_name', entry.get('indicator_name'))
    entry['unit'] = payload.get('unit', entry.get('unit', ''))
    incoming_date = payload.get('date') or payload.get('as_of_date') or payload.get('report_period')
    if incoming_date:
        entry['date'] = incoming_date
    if payload.get("expected_period"):
        entry["expected_period"] = payload.get("expected_period")
    entry['as_of_date'] = payload.get('as_of_date') or payload.get('report_period') or entry.get('as_of_date')
    entry['source'] = _format_source_label(payload.get('source'))
    _copy_source_url(entry, payload)
    _copy_payload_metadata_fields(entry, payload, ("estimation_method", "metric_basis", "confidence"))
    # 确保 note 为字符串，避免 None 参与字符串拼接时报错
    note_val = payload.get('note', entry.get('note'))
    if is_manual and 'note' not in payload:
        note_val = ""
    entry['note'] = note_val if isinstance(note_val, str) else ''
    fallback_reason = None

    if indicator_key == "industrial":
        raw_current = _coerce_float(payload.get('current_value'))
        yoy_month = _coerce_float(payload.get('yoy_month'))
        yoy_ytd = _coerce_float(payload.get('yoy_ytd'))
        raw_type = payload.get('value_type')
        value_type = None
        if isinstance(raw_type, str) and raw_type.strip():
            raw_lower = raw_type.lower()
            if "month" in raw_lower or "当月" in raw_type:
                value_type = "yoy_month"
            elif "ytd" in raw_lower or "累计" in raw_type:
                value_type = "yoy_ytd"
        if value_type == "yoy_month":
            if yoy_month is None:
                yoy_month = raw_current
        elif value_type == "yoy_ytd":
            if yoy_ytd is None:
                yoy_ytd = raw_current
        elif raw_current is not None and yoy_month is None and yoy_ytd is None:
            hint_text = " ".join(
                str(payload.get(k) or "") for k in ("note", "source", "indicator_name", "report_period")
            )
            if _contains_ytd_marker(hint_text):
                yoy_ytd = raw_current
                value_type = "yoy_ytd"
            else:
                yoy_month = raw_current
                value_type = "yoy_month"

        entry['yoy_month'] = yoy_month
        entry['yoy_ytd'] = yoy_ytd
        entry['value_type'] = value_type or entry.get('value_type')
        entry['current_value'] = yoy_month
        entry['previous_value'] = _coerce_float(payload.get('previous_value')) if yoy_month is not None else None
        entry['change_rate'] = _coerce_float(payload.get('change_rate')) if yoy_month is not None else None

        if yoy_month is not None and yoy_ytd is not None and abs(yoy_month - yoy_ytd) < 1e-6:
            _append_note(entry, "口径疑似混淆(yoy_month≈yoy_ytd)")
        if yoy_month is None and yoy_ytd is not None:
            _append_note(entry, "only_yoy_ytd_provided")
            fallback_reason = fallback_reason or "manual_incomplete"
    else:
        entry['current_value'] = _coerce_float(payload.get('current_value'))
        entry['previous_value'] = _coerce_float(payload.get('previous_value'))
        entry['change_rate'] = _coerce_float(payload.get('change_rate'))
        entry['value_type'] = payload.get('value_type', entry.get('value_type'))

    # is_estimated 规则：手工注入默认不估算；regex_only/明确标注才估算
    if 'is_estimated' in payload:
        entry['is_estimated'] = _coerce_bool(payload.get('is_estimated'))
    else:
        source_text = str(payload.get('source') or entry.get('source') or "")
        note_text = str(entry.get('note') or "")
        estimated_markers = ("regex_only", "regex_fallback", "bond_etf_proxy", "ETF代理", "估", "estimated")
        if any(m in source_text or m in note_text for m in estimated_markers):
            entry['is_estimated'] = True
        else:
            entry['is_estimated'] = False if entry.get('current_value') is not None else bool(entry.get('is_estimated'))

    # 先尝试事件序列回填 previous_value / change_rate（工业增加值仅在当月同比可用时回填）
    if (
        entry['previous_value'] is None
        and entry['current_value'] is not None
        and trend_history_base_dir is not None
    ):
        hist_prev = _calc_prev_from_event_history(
            indicator_key,
            entry['current_value'],
            reference_date,
            base_dir=trend_history_base_dir,
        )
        if hist_prev.get("previous_value") is not None:
            entry['previous_value'] = hist_prev.get("previous_value")
            if entry['change_rate'] is None and hist_prev.get("change_rate") is not None:
                entry['change_rate'] = hist_prev.get("change_rate")
        else:
            fallback_reason = hist_prev.get("reason")

    # 兜底回填变化率：若有 current_value + previous_value 且 change_rate 缺失，自动按百分比补齐
    if (
        entry['change_rate'] is None
        and entry['current_value'] is not None
        and entry['previous_value'] is not None
    ):
        change_rate_pct = _calc_change_rate_pct(entry['current_value'], entry['previous_value'])
        if change_rate_pct is not None:
            entry['change_rate'] = change_rate_pct
            if not entry.get('note'):
                entry['note'] = ''
            if entry['note']:
                entry['note'] += '；'
            entry['note'] += 'auto-backfilled change_rate% via (current-previous)/abs(previous)*100'
        else:
            fallback_reason = fallback_reason or "change_rate_pct_div_by_zero"

    # 兜底回填前值：若有 current_value + change_rate(%) 但前值缺失，按百分比反推
    if entry['previous_value'] is None and entry['current_value'] is not None:
        if not entry.get('note'):
            entry['note'] = ''
        if entry['change_rate'] is not None:
            previous_value = _calc_previous_from_change_rate_pct(entry['current_value'], entry['change_rate'])
            if previous_value is not None:
                entry['previous_value'] = previous_value
                if entry['note']:
                    entry['note'] += '；'
                entry['note'] += 'auto-backfilled previous_value via current/(1+change_rate/100)'
                fallback_reason = fallback_reason or "no_previous_value"
            else:
                fallback_reason = fallback_reason or "change_rate_pct_invalid_denominator"
        else:
            fallback_reason = fallback_reason or "manual_incomplete"

    if fallback_reason:
        if entry['note']:
            entry['note'] += '；'
        entry['note'] += f"reason={fallback_reason}"
    # 若仍无有效 current_value，则视为缺失，抛出异常阻断流程，避免 Stage3 出现 N/A
    if entry['current_value'] is None:
        raise ValueError(f"macro_indicators.{entry.get('indicator_name', 'unknown')} current_value is missing after injection")
    entry["is_stale"] = False
    entry["stale_reason"] = None
    if summary is not None:
        if (
            force_override
            and _coerce_float(original_current_value) is not None
            and not _same_numeric_value(original_current_value, entry.get("current_value"))
        ):
            summary.forced_override(
                "macro_indicators",
                indicator_key,
                original_current_value,
                incoming_current_value,
            )
        summary.injected("macro_indicators", indicator_key)
    return True


def _create_monetary_placeholder(key: str, payload: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    """当原始市场数据缺少某个货币政策字段时，动态创建占位符"""
    default_date = payload.get('date') or payload.get('as_of_date') or payload.get('report_period') or ""
    return {
        "policy_name": payload.get('policy_name', key.upper()),
        "current_value": None,
        "change_from_120d": None,
        "unit": payload.get('unit', '%'),
        "date": default_date,
        "as_of_date": payload.get('as_of_date'),
        "rrr_type": payload.get('rrr_type'),
        "source": "待WebSearch补充(websearch导入)",
        "note": payload.get('note'),
        "is_estimated": True,
        "is_stale": False,
        "expected_period": payload.get("expected_period"),
        "stale_reason": None,
    }


def _create_macro_placeholder(key: str, payload: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    """缺失宏观指标时创建占位，便于后续注入而不跳过"""
    default_date = payload.get('date') or payload.get('as_of_date') or payload.get('report_period') or ""
    return {
        "indicator_name": payload.get('indicator_name', key),
        "current_value": None,
        "yoy_month": None,
        "yoy_ytd": None,
        "previous_value": None,
        "change_rate": None,
        "unit": payload.get('unit', payload.get('unit', '%')),
        "date": default_date,
        "as_of_date": payload.get('as_of_date'),
        "value_type": payload.get('value_type'),
        "source": "待WebSearch补充",
        "note": payload.get('note'),
        "is_estimated": True,
        "is_stale": False,
        "expected_period": payload.get("expected_period"),
        "stale_reason": None,
    }


def _apply_monetary_entry(
    indicator_key: str,
    entry: Dict[str, Any],
    payload: Dict[str, Any],
    reference_date: Optional[str],
    *,
    is_manual: bool = False,
    override_stale: bool = True,
    force_override: bool = False,
    trend_history_base_dir: Optional[Path] = DEFAULT_BASE_DIR,
    summary: Optional[InjectionSummary] = None,
) -> bool:
    if not isinstance(entry, dict):
        return False
    original_current_value = entry.get("current_value")
    incoming_current_value = _coerce_float(payload.get("current_value"))
    existing_placeholder = _is_placeholder_numeric(entry.get("current_value"))
    existing_stale = bool(entry.get("is_stale"))
    preserve_stale = existing_stale and not override_stale
    original_stale_reason = entry.get("stale_reason")
    rrr_type_conflict = (
        indicator_key in {"rrr", "reserve_ratio"} and _has_rrr_type_conflict(entry, payload)
    )
    if rrr_type_conflict:
        if summary is not None:
            summary.skipped_existing(
                "monetary_policy",
                indicator_key,
                "rrr_type_conflict",
                original_current_value,
                incoming_current_value,
            )
        return False
    trusted_quality_override = _is_trusted_monetary_manual_quality_override(
        indicator_key,
        entry,
        payload,
        incoming_current_value,
        is_manual=is_manual,
    )
    preserve_existing_official_source = _should_preserve_existing_official_source(entry, payload)
    if (
        not force_override
        and not existing_placeholder
        and not (override_stale and existing_stale)
    ):
        if _same_numeric_value(original_current_value, incoming_current_value):
            if _merge_same_value_report_fields(
                entry,
                payload,
                category="monetary_policy",
                key=indicator_key,
                is_manual=is_manual,
                override_stale=override_stale,
            ):
                if summary is not None:
                    summary.metadata_updated(
                        "monetary_policy",
                        indicator_key,
                        "same_numeric_value_report_fields_merged",
                        original_current_value,
                        incoming_current_value,
                    )
                return True
        if not trusted_quality_override:
            if summary is not None:
                if incoming_current_value is None:
                    summary.skipped_no_parseable_value("monetary_policy", indicator_key)
                else:
                    summary.skipped_existing(
                        "monetary_policy",
                        indicator_key,
                        "existing_value_present",
                        original_current_value,
                        incoming_current_value,
                    )
            return False
    entry['policy_name'] = payload.get('policy_name', entry.get('policy_name'))
    incoming_value = _coerce_float(payload.get('current_value'))
    change_value = payload.get('change_from_120d', payload.get('change_rate'))
    entry['change_from_120d'] = _coerce_float(change_value)
    entry['unit'] = payload.get('unit', entry.get('unit', ''))
    incoming_date = payload.get('date') or payload.get('as_of_date') or payload.get('report_period')
    if incoming_date:
        entry['date'] = incoming_date
    if payload.get("expected_period"):
        entry["expected_period"] = payload.get("expected_period")
    entry['as_of_date'] = payload.get('as_of_date') or entry.get('as_of_date')
    if not preserve_existing_official_source:
        entry['source'] = _format_source_label(payload.get('source'))
        _copy_source_url(entry, payload)
    _copy_payload_metadata_fields(entry, payload, ("estimation_method", "metric_basis", "confidence"))
    note_val = payload.get('note', entry.get('note'))
    if is_manual and 'note' not in payload:
        note_val = ""
    if not preserve_existing_official_source:
        entry['note'] = note_val
    incoming_rrr_type = _normalize_rrr_type(payload.get('rrr_type') or payload.get('value_type'))
    if indicator_key in {"rrr", "reserve_ratio"}:
        existing_rrr_type = _normalize_rrr_type(entry.get('rrr_type'))
        if incoming_rrr_type:
            if existing_rrr_type and incoming_rrr_type != existing_rrr_type and entry.get('current_value') is not None:
                _append_note(entry, f"rrr_type_conflict:{existing_rrr_type}->{incoming_rrr_type}")
                incoming_value = None
            else:
                entry['rrr_type'] = incoming_rrr_type

    if incoming_value is not None:
        entry['current_value'] = incoming_value

    # is_estimated 规则：手工注入默认不估算；regex_only/明确标注才估算
    if 'is_estimated' in payload:
        incoming_estimated = _coerce_bool(payload.get('is_estimated'))
        if not (
            preserve_existing_official_source
            and entry.get('is_estimated') is False
            and incoming_estimated is True
        ):
            entry['is_estimated'] = incoming_estimated
    else:
        if not preserve_existing_official_source:
            source_text = str(payload.get('source') or entry.get('source') or "")
            note_text = str(entry.get('note') or "")
            estimated_markers = ("regex_only", "regex_fallback", "bond_etf_proxy", "ETF代理", "估", "estimated")
            if any(m in source_text or m in note_text for m in estimated_markers):
                entry['is_estimated'] = True
            else:
                entry['is_estimated'] = False if entry.get('current_value') is not None else bool(entry.get('is_estimated'))
    if is_manual:
        _apply_manual_official_estimation_rule("monetary_policy", indicator_key, payload, entry)

    fallback_reason = None
    if (
        entry['change_from_120d'] is None
        and entry['current_value'] is not None
        and trend_history_base_dir is not None
    ):
        hist = _calc_change_from_event_history(
            indicator_key,
            entry['current_value'],
            reference_date,
            base_dir=trend_history_base_dir,
        )
        if hist.get("change_from_120d") is not None:
            entry['change_from_120d'] = hist.get("change_from_120d")
        else:
            entry['change_from_120d'] = None
        fallback_reason = hist.get("reason")

    if fallback_reason:
        note_val = entry.get('note')
        if not isinstance(note_val, str):
            note_val = ''
        if note_val:
            note_val += '；'
        note_val += f"reason={fallback_reason}"
        entry['note'] = note_val
    if entry.get("current_value") is not None:
        if preserve_stale:
            entry["is_stale"] = True
            entry["stale_reason"] = original_stale_reason
        else:
            entry["is_stale"] = False
            entry["stale_reason"] = None
    if summary is not None:
        if (
            force_override
            and _coerce_float(original_current_value) is not None
            and not _same_numeric_value(original_current_value, entry.get("current_value"))
        ):
            summary.forced_override(
                "monetary_policy",
                indicator_key,
                original_current_value,
                incoming_current_value,
            )
        summary.injected("monetary_policy", indicator_key)
    return True


def _apply_fund_flow_entry(
    entry: Dict[str, Any],
    key: str,
    payload: Dict[str, Any],
    *,
    summary: Optional[InjectionSummary] = None,
) -> bool:
    existing_recent = _coerce_float(entry.get("recent_5d"))
    existing_total = _coerce_float(entry.get("total_120d"))
    existing_suspicious = _is_suspicious_fund_flow_pair(key, existing_recent, existing_total)
    payload_requested_estimated = _coerce_bool(payload.get("is_estimated"))
    recent_value = FundFlowData._parse_amount(payload.get('recent_5d'))
    total_value = FundFlowData._parse_amount(payload.get('total_120d'))
    current_value = FundFlowData._parse_amount(
        payload.get('current_value') or payload.get('daily_value') or payload.get('today_value')
    )
    if recent_value is None and total_value is None and current_value is None:
        print(f"  [WARN] {key} 缺少可解析的金额，跳过注入")
        return False

    entry['type'] = key
    updated = False
    if recent_value is not None:
        entry['recent_5d'] = recent_value
        updated = True
    if total_value is not None:
        entry['total_120d'] = total_value
        updated = True
    if current_value is not None:
        entry['current_value'] = current_value
        entry['current_date'] = payload.get('date') or entry.get('current_date')
        updated = True
    if not updated:
        return False

    trend_base = recent_value if recent_value is not None else current_value
    entry['trend'] = _infer_trend(payload.get('trend'), trend_base)

    anomaly = any(value == 0 for value in (recent_value, total_value, current_value) if value is not None)
    anomaly = anomaly or _is_suspicious_fund_flow_pair(key, recent_value, total_value)
    entry['source'] = SOURCE_ANOMALY_LABEL if anomaly else DEFAULT_SOURCE_LABEL
    entry['note'] = _build_fund_flow_note(payload, anomaly)
    _copy_source_url(entry, payload)
    _copy_payload_metadata_fields(
        entry,
        payload,
        ("is_estimated", "estimation_method", "confidence"),
    )
    claimed_source_tier = _normalize_source_tier(payload.get("source_tier"))
    if claimed_source_tier:
        entry["claimed_source_tier"] = claimed_source_tier
    else:
        entry.pop("claimed_source_tier", None)
    entry["metric_basis"] = _default_fund_flow_metric_basis(key, payload)
    entry["source_tier"] = _infer_fund_flow_source_tier(payload)
    entry["window_evidence"] = _infer_fund_flow_window_evidence(
        key,
        payload,
        entry["metric_basis"],
    )
    _normalize_fund_flow_estimation(entry, payload)
    if summary is not None and not payload_requested_estimated and entry.get("is_estimated") is True:
        summary.fund_flow_forced_estimated(
            "fund_flow",
            key,
            source_tier=entry.get("source_tier"),
            window_evidence=entry.get("window_evidence"),
            metric_basis=entry.get("metric_basis") or "unknown",
            reason="fund_flow_estimated_gate",
        )
    if existing_suspicious:
        entry['note'] = (
            f"覆盖Stage2可疑占位值；{entry['note']}" if entry.get('note') else "覆盖Stage2可疑占位值"
        )
    return True


def _infer_trend(raw_trend: Optional[str], recent_value: Optional[float]) -> str:
    if isinstance(recent_value, (int, float)):
        if recent_value > 0:
            return '流入'
        if recent_value < 0:
            return '流出'
    return raw_trend or '未知'


def _is_suspicious_fund_flow_pair(
    key: str, recent_value: Optional[float], total_value: Optional[float]
) -> bool:
    if recent_value is None or total_value is None:
        return False
    if key in {"northbound", "southbound"} and abs(recent_value - total_value) < 1e-9:
        if abs(recent_value - 100.0) < 1e-9:
            return True
        if abs(recent_value) <= 150.0:
            return True
    return False


def _infer_asset_trend(
    raw_trend: Optional[str],
    daily_change: Optional[float],
    ytd_change: Optional[float],
    asset_type: str = "commodity"
) -> str:
    """根据涨跌幅自动推断资产趋势方向。

    Args:
        raw_trend: 手工指定的趋势
        daily_change: 日涨跌幅(%)
        ytd_change: 年内/120日涨跌幅(%)
        asset_type: 资产类型 (commodity/bond/forex)

    Returns:
        趋势描述字符串
    """
    if raw_trend and raw_trend not in ('未知', '待WebSearch补充', '待 WebSearch'):
        return raw_trend

    # 债券特殊处理：收益率上行=熊市，下行=牛市
    if asset_type == "bond":
        if isinstance(daily_change, (int, float)):
            if daily_change > 5:  # >5bp
                return "上行"
            elif daily_change < -5:  # <-5bp
                return "下行"
            else:
                return "平稳"
        return "未知"

    # 商品和外汇：基于涨跌幅判断
    if isinstance(ytd_change, (int, float)):
        if ytd_change > 10:
            return "强势上涨"
        elif ytd_change > 3:
            return "温和上涨"
        elif ytd_change < -10:
            return "强势下跌"
        elif ytd_change < -3:
            return "温和下跌"
        else:
            return "横盘震荡"
    elif isinstance(daily_change, (int, float)):
        if daily_change > 2:
            return "上涨"
        elif daily_change < -2:
            return "下跌"
        else:
            return "平稳"

    return "未知"


def _build_fund_flow_note(payload: Dict[str, Any], anomaly: bool) -> str:
    parts = []
    raw_source = payload.get('source')
    if raw_source:
        parts.append(f"来源:{raw_source}")
    if payload.get('date'):
        parts.append(f"日期:{payload.get('date')}")
    if payload.get('unit'):
        parts.append(f"单位:{payload['unit']}")
    if payload.get('note'):
        parts.append(payload['note'])
    if payload.get('current_value') or payload.get('daily_value') or payload.get('today_value'):
        raw_daily = payload.get('current_value') or payload.get('daily_value') or payload.get('today_value')
        parts.append(f"原始当日:{raw_daily}")
    if payload.get('recent_5d'):
        parts.append(f"原始5日:{payload['recent_5d']}")
    if payload.get('total_120d'):
        parts.append(f"原始120日:{payload['total_120d']}")
    if anomaly:
        parts.append("异常: 零值待WebSearch复核")
    return '；'.join(parts)


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value)[:10]
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m", "%Y%m"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt in ("%Y-%m", "%Y%m"):
                return datetime(dt.year, dt.month, 1)
            return dt
        except Exception:
            continue
    return None


def _load_series_records(
    category: str,
    symbol: str,
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
    reference_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    series_path = base_dir / "series" / category / f"{symbol}.json"
    if not series_path.exists():
        return []
    try:
        payload = json.loads(series_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    values = payload.get("values") if isinstance(payload.get("values"), list) else []
    ref_dt = _parse_date(reference_date) if reference_date else None
    records: List[Dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        dt = _parse_date(item.get("date"))
        if dt is None:
            continue
        if ref_dt and dt > ref_dt:
            continue
        val = _coerce_float(item.get("value"))
        if val is None:
            continue
        records.append(
            {
                "date": dt,
                "value": float(val),
                "is_estimated": bool(item.get("is_estimated", False)),
            }
        )
    records.sort(key=lambda x: x["date"])
    return records


def _calc_change_from_trend_history(
    category: str,
    symbol: str,
    current_value: float,
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
    reference_date: Optional[str] = None,
) -> Dict[str, Optional[float]]:
    """从 trend_history 计算 change_5d 和 change_120d 百分比变化（带原因信息）。"""
    result: Dict[str, Optional[float]] = {
        "change_5d": None,
        "change_120d": None,
        "change_5d_bp": None,
        "change_120d_bp": None,
        "reason_5d": None,
        "reason_120d": None,
        "base_5d_estimated": None,
        "base_120d_estimated": None,
        "base_5d_date": None,
        "base_120d_date": None,
        "latest_date": None,
    }
    if current_value is None or current_value == 0:
        result["reason_5d"] = "manual_incomplete"
        result["reason_120d"] = "manual_incomplete"
        return result

    records = _load_series_records(category, symbol, base_dir=base_dir, reference_date=reference_date)
    if not records:
        result["reason_5d"] = "trend_history_missing"
        result["reason_120d"] = "trend_history_missing"
        return result

    ref_dt = _parse_date(reference_date) if reference_date else None
    latest = records[-1]
    result["latest_date"] = latest["date"].strftime("%Y-%m-%d")

    anchor_records = records
    # 有 reference_date 时，剔除同日记录，避免“当日写入”影响基准
    if ref_dt:
        anchor_records = [r for r in records if r["date"].date() < ref_dt.date()]

    if not anchor_records:
        result["reason_5d"] = "trend_history_insufficient"
        result["reason_120d"] = "trend_history_insufficient"
        return result

    required_5d = 5
    # 有 reference_date 表示当前值来自当日，需回看 120 交易日基准（不含当日）
    required_120d = 120 if ref_dt else min(121, SERIES_WINDOWS.get(category, 121))

    # change_5d
    if len(anchor_records) >= required_5d:
        base_5d = anchor_records[-required_5d]
        base_5d_val = base_5d["value"]
        result["base_5d_date"] = base_5d["date"].strftime("%Y-%m-%d")
        result["base_5d_estimated"] = bool(base_5d.get("is_estimated"))
        if category == "bonds" and base_5d_val > 10:
            result["reason_5d"] = "unit_mismatch"
        elif base_5d_val != 0:
            if category == "bonds":
                result["change_5d_bp"] = (current_value - base_5d_val) * 100
            else:
                result["change_5d"] = ((current_value - base_5d_val) / base_5d_val) * 100
    else:
        result["reason_5d"] = "trend_history_insufficient"

    # change_120d
    if len(anchor_records) >= required_120d:
        base_120d = anchor_records[-required_120d]
        base_120d_val = base_120d["value"]
        result["base_120d_date"] = base_120d["date"].strftime("%Y-%m-%d")
        result["base_120d_estimated"] = bool(base_120d.get("is_estimated"))
        if category == "bonds" and base_120d_val > 10:
            result["reason_120d"] = "unit_mismatch"
        elif base_120d_val != 0:
            if category == "bonds":
                result["change_120d_bp"] = (current_value - base_120d_val) * 100
            else:
                result["change_120d"] = ((current_value - base_120d_val) / base_120d_val) * 100
    else:
        result["reason_120d"] = "trend_history_insufficient"

    return result


def _calc_daily_change_from_trend_history(
    category: str,
    symbol: str,
    current_value: float,
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
    reference_date: Optional[str] = None,
) -> Dict[str, Optional[float]]:
    """从 trend_history 计算前一交易日变化（百分比变化）。"""
    result: Dict[str, Optional[float]] = {
        "change_1d": None,
        "reason_1d": None,
        "base_1d_estimated": None,
        "base_1d_date": None,
    }
    if current_value is None or current_value == 0:
        result["reason_1d"] = "manual_incomplete"
        return result

    records = _load_series_records(category, symbol, base_dir=base_dir, reference_date=reference_date)
    if not records:
        result["reason_1d"] = "trend_history_missing"
        return result

    ref_dt = _parse_date(reference_date) if reference_date else None
    if ref_dt:
        anchor_records = [r for r in records if r["date"].date() < ref_dt.date()]
    else:
        anchor_records = list(records)
        # 避免同日重复写入后出现“前一日变化=0”。
        if anchor_records and abs(anchor_records[-1]["value"] - float(current_value)) < 1e-9:
            anchor_records = anchor_records[:-1]

    if not anchor_records:
        result["reason_1d"] = "trend_history_insufficient"
        return result

    base = anchor_records[-1]
    base_val = base["value"]
    result["base_1d_date"] = base["date"].strftime("%Y-%m-%d")
    result["base_1d_estimated"] = bool(base.get("is_estimated"))
    if base_val == 0:
        result["reason_1d"] = "trend_history_insufficient"
        return result

    result["change_1d"] = ((float(current_value) - float(base_val)) / float(base_val)) * 100
    return result


def _load_event_history(indicator: str, *, base_dir: Path = DEFAULT_BASE_DIR) -> List[Dict[str, Any]]:
    path = base_dir / "events" / f"{indicator}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    events = payload.get("events")
    return events if isinstance(events, list) else []


def _calc_change_from_event_history(
    indicator: str,
    current_value: Optional[float],
    reference_date: Optional[str],
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> Dict[str, Optional[float]]:
    """基于事件序列估算 120 日变化，返回 change_from_120d 与原因。"""
    result = {
        "change_from_120d": None,
        "reason": None,
        "base_date": None,
        "base_estimated": None,
    }
    if current_value is None:
        return result
    events = _load_event_history(indicator, base_dir=base_dir)
    if not events:
        result["reason"] = "trend_history_missing"
        return result

    ref_dt = _parse_date(reference_date) or datetime.now()
    parsed = []
    for event in events:
        if not isinstance(event, dict):
            continue
        dt = _parse_date(event.get("release_date") or event.get("date"))
        if dt is None or dt > ref_dt:
            continue
        val = _coerce_float(event.get("value"))
        if val is None:
            continue
        parsed.append((dt, val, bool(event.get("is_estimated", False))))

    if not parsed:
        result["reason"] = "trend_history_missing"
        return result

    parsed.sort(key=lambda x: x[0])
    target_dt = ref_dt - timedelta(days=120)

    base_val = None
    base_estimated = None
    base_date = None
    for dt, val, is_est in reversed(parsed):
        if dt <= target_dt:
            base_val = val
            base_estimated = is_est
            base_date = dt
            break

    if base_val is None:
        result["reason"] = "no_previous_value"
        return result

    result["change_from_120d"] = float(current_value) - float(base_val)
    result["base_date"] = base_date.strftime("%Y-%m-%d") if base_date else None
    result["base_estimated"] = base_estimated
    return result


def _calc_prev_from_event_history(
    indicator: str,
    current_value: Optional[float],
    reference_date: Optional[str],
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> Dict[str, Optional[float]]:
    """为宏观指标从事件序列回推 previous_value 与 change_rate。"""
    result = {"previous_value": None, "change_rate": None, "reason": None}
    if current_value is None:
        return result
    events = _load_event_history(indicator, base_dir=base_dir)
    if not events:
        result["reason"] = "trend_history_missing"
        return result

    def _parse_date(date_text: Optional[str]) -> Optional[datetime]:
        if not date_text:
            return None
        text = str(date_text)[:10]
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y%m%d", "%Y%m"):
            try:
                dt = datetime.strptime(text, fmt)
                if fmt == "%Y-%m":
                    return datetime(dt.year, dt.month, 1)
                if fmt == "%Y%m":
                    return datetime(dt.year, dt.month, 1)
                return dt
            except Exception:
                continue
        return None

    ref_dt = _parse_date(reference_date) or datetime.now()
    parsed = []
    if indicator in {"industrial", "industrial_sales"}:
        for event in events:
            if not isinstance(event, dict):
                continue
            period = event.get("report_period")
            if not isinstance(period, str) or not re.match(r"20\\d{2}-\\d{2}$", period):
                continue
            dt = _parse_date(period)
            if dt is None or dt > ref_dt:
                continue
            val = _coerce_float(event.get("value"))
            if val is None:
                continue
            parsed.append((dt, val))
        if len(parsed) < 2:
            result["reason"] = "no_previous_value"
            return result
        parsed.sort(key=lambda x: x[0])
        latest_val = parsed[-1][1]
        prev_val = parsed[-2][1] if abs(latest_val - float(current_value)) < 1e-6 else latest_val
        result["previous_value"] = prev_val
        change_rate_pct = _calc_change_rate_pct(float(current_value), float(prev_val))
        if change_rate_pct is None:
            result["reason"] = "change_rate_pct_div_by_zero"
        else:
            result["change_rate"] = change_rate_pct
        return result
    for event in events:
        if not isinstance(event, dict):
            continue
        dt = _parse_date(event.get("release_date") or event.get("date"))
        if dt is None or dt > ref_dt:
            continue
        val = _coerce_float(event.get("value"))
        if val is None:
            continue
        parsed.append((dt, val))

    if len(parsed) < 2:
        result["reason"] = "no_previous_value"
        return result

    parsed.sort(key=lambda x: x[0])
    latest_val = parsed[-1][1]
    prev_val = parsed[-2][1] if abs(latest_val - float(current_value)) < 1e-6 else latest_val

    result["previous_value"] = prev_val
    change_rate_pct = _calc_change_rate_pct(float(current_value), float(prev_val))
    if change_rate_pct is None:
        result["reason"] = "change_rate_pct_div_by_zero"
    else:
        result["change_rate"] = change_rate_pct
    return result


def _should_backfill_numeric(value: Any) -> bool:
    if value in (None, "", "N/A"):
        return True
    try:
        return abs(float(value)) < 1e-9
    except Exception:
        return True


_is_forex_daily_change_absence_text = is_stage25_forex_daily_change_absence_text
_is_valid_forex_daily_change_base_date = partial(
    is_valid_forex_base_date,
    is_absence=_is_forex_daily_change_absence_text,
)
_is_valid_forex_daily_change_source_url = partial(
    is_valid_forex_source_url,
    is_absence=_is_forex_daily_change_absence_text,
)
_is_valid_forex_change_base_price = partial(
    is_valid_forex_base_price,
    is_absence=_is_forex_daily_change_absence_text,
    coerce=_coerce_float,
)
_has_forex_daily_change_computed_marker = partial(
    has_forex_computed_marker,
    markers=FOREX_DAILY_CHANGE_SOURCE_MARKERS,
    is_absence=_is_forex_daily_change_absence_text,
)
_has_forex_120d_change_computed_marker = partial(
    has_forex_computed_marker,
    markers=FOREX_120D_CHANGE_SOURCE_MARKERS,
    is_absence=_is_forex_daily_change_absence_text,
    reject_daily_prefix=True,
)
_has_forex_daily_change_evidence = partial(
    has_stage25_forex_daily_change_evidence,
    coerce=_coerce_float,
)
_copy_valid_forex_daily_change_evidence = partial(
    copy_valid_stage25_forex_daily_change_evidence,
    coerce=_coerce_float,
)
_copy_valid_forex_120d_change_evidence = partial(
    copy_valid_stage25_forex_120d_change_evidence,
    coerce=_coerce_float,
)
_has_forex_120d_change_evidence = partial(
    has_stage25_forex_120d_change_evidence,
    coerce=_coerce_float,
)


def _is_zero_change_value(value: Any) -> bool:
    numeric = _coerce_float(value)
    return numeric is not None and abs(numeric) < 1e-12


def _should_backfill_forex_daily_change(entry: Dict[str, Any]) -> bool:
    value = _coerce_float(entry.get("daily_change"))
    if value is None:
        return True
    if abs(value) >= 1e-9:
        return False
    return not _has_forex_daily_change_evidence(entry)


def _should_backfill_forex_120d_change(entry: Dict[str, Any]) -> bool:
    value = _coerce_float(entry.get("change_120d"))
    if value is None:
        return True
    if abs(value) >= 1e-9:
        return False
    return not _has_forex_120d_change_evidence(entry)


def _usable_forex_change_value(entry: Dict[str, Any], field: str) -> Optional[float]:
    value = _coerce_float(entry.get(field))
    if value is None:
        return None
    if field == "daily_change" and _should_backfill_forex_daily_change(entry):
        return None
    if field == "change_120d" and _should_backfill_forex_120d_change(entry):
        return None
    return value


def _is_zero_derived_forex_trend(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return text in {
        "flat",
        "sideways",
        "平稳",
        "横盘震荡",
        "骞崇ǔ",
        "妯洏闇囪崱",
    }


def _usable_forex_raw_trend(raw_trend: Any, daily_change: Optional[float], change_120d: Optional[float]) -> Any:
    if (daily_change is None or change_120d is None) and _is_zero_derived_forex_trend(raw_trend):
        return None
    return raw_trend


def _backfill_cdb_proxy_changes_from_cn10y(market_data: Dict[str, Any]) -> int:
    bonds = market_data.get("bonds", []) or []
    cn10y = next((item for item in bonds if isinstance(item, dict) and item.get("symbol") == "CN10Y"), None)
    cdb = next((item for item in bonds if isinstance(item, dict) and item.get("symbol") == "CN10Y_CDB"), None)
    if not isinstance(cn10y, dict) or not isinstance(cdb, dict):
        return 0
    if not _has_valid_value(cdb.get("current_yield")) or not bool(cdb.get("is_estimated")):
        return 0
    basis_text = " ".join(
        str(cdb.get(field) or "")
        for field in ("source", "note", "estimation_method", "metric_basis")
    ).lower()
    if "cn10y" not in basis_text and "国债" not in basis_text:
        return 0

    changed = 0
    for field in ("change_5d_bp", "change_120d_bp"):
        if not _should_backfill_numeric(cdb.get(field)):
            continue
        proxy_value = _coerce_float(cn10y.get(field))
        if proxy_value is None:
            continue
        cdb[field] = proxy_value
        changed += 1

    if changed:
        cdb["trend"] = _infer_asset_trend(
            cdb.get("trend"),
            cdb.get("change_5d_bp"),
            cdb.get("change_120d_bp"),
            "bond",
        )
        cdb["note"] = _append_note_once(
            str(cdb.get("note") or ""),
            "cn10y_proxy_change_basis",
        )
    return changed


def _remove_note_markers(entry: Dict[str, Any], markers: Tuple[str, ...]) -> None:
    """从 note 中移除已过期的原因标记（如 no_previous_value）。"""
    note = entry.get("note")
    if not isinstance(note, str) or not note:
        return
    parts = [part for part in note.split("；") if part]
    filtered = [part for part in parts if not any(marker in part for marker in markers)]
    entry["note"] = "；".join(filtered)


def _record_backfill_issue(
    metadata: Dict[str, Any],
    category: str,
    key: str,
    field: str,
    reason: str,
) -> None:
    issues = metadata.setdefault("trend_backfill_issues", [])
    issue = {"category": category, "key": key, "field": field, "reason": reason}
    if issue not in issues:
        issues.append(issue)


_TREND_CONF_RANK = {
    "low": 0,
    "medium": 1,
    "high": 2,
}


def _merge_trend_confidence(entry: Dict[str, Any], level: str) -> None:
    normalized = str(level or "").strip().lower()
    if normalized not in _TREND_CONF_RANK:
        return
    existing = str(entry.get("trend_history_confidence") or "").strip().lower()
    if existing not in _TREND_CONF_RANK or _TREND_CONF_RANK[normalized] < _TREND_CONF_RANK[existing]:
        entry["trend_history_confidence"] = normalized


def _derive_trend_confidence(
    hist: Dict[str, Any],
    *,
    used_5d: bool,
    used_120d: bool,
) -> Tuple[Optional[str], Optional[str]]:
    if not used_5d and not used_120d:
        return None, None
    reasons: List[str] = []
    if used_5d and hist.get("reason_5d"):
        reasons.append(str(hist.get("reason_5d")))
    if used_120d and hist.get("reason_120d"):
        reasons.append(str(hist.get("reason_120d")))
    if reasons:
        reason = "trend_history_reason:" + ",".join(sorted(set(reasons)))
        return "low", reason
    if (used_5d and hist.get("base_5d_estimated")) or (used_120d and hist.get("base_120d_estimated")):
        return "low", "trend_history_base_estimated"
    if used_5d and used_120d:
        return "high", None
    return "medium", "trend_history_partial_window"


def _backfill_trend_changes(
    market_data: Dict[str, Any],
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> Dict[str, int]:
    """对全量指标回读 trend_history，补齐缺失的变化值。"""
    stats = {
        "bonds": 0,
        "forex": 0,
        "commodities": 0,
        "stock_indices": 0,
        "fund_flow": 0,
        "macro_indicators": 0,
        "monetary_policy": 0,
    }
    metadata = market_data.get("metadata", {}) if isinstance(market_data, dict) else {}
    reference_date = (
        market_data.get("metadata", {}).get("date")
        or market_data.get("metadata", {}).get("end_date")
        or market_data.get("metadata", {}).get("start_date")
    )

    for bond in market_data.get("bonds", []) or []:
        symbol = bond.get("symbol")
        current = _coerce_float(bond.get("current_yield"))
        if not symbol or current is None:
            continue
        hist = _calc_change_from_trend_history("bonds", symbol, current, base_dir=base_dir, reference_date=reference_date)
        used_hist_120d = False
        used_hist_5d = False
        if _should_backfill_numeric(bond.get("change_120d_bp")):
            if hist.get("change_120d_bp") is not None:
                bond["change_120d_bp"] = round(float(hist["change_120d_bp"]), 2)
                stats["bonds"] += 1
                used_hist_120d = True
            else:
                bond["change_120d_bp"] = None
                reason = hist.get("reason_120d") or "trend_history_missing"
                _record_backfill_issue(metadata, "bonds", symbol, "change_120d_bp", reason)
                _append_note(bond, f"reason={reason}")
        if bond.get("change_5d_bp") is None:
            if hist.get("change_5d_bp") is not None:
                bond["change_5d_bp"] = round(float(hist["change_5d_bp"]), 2)
                stats["bonds"] += 1
                used_hist_5d = True
            else:
                bond["change_5d_bp"] = None
                reason = hist.get("reason_5d") or "trend_history_missing"
                _record_backfill_issue(metadata, "bonds", symbol, "change_5d_bp", reason)
                _append_note(bond, f"reason={reason}")
        if (used_hist_120d and hist.get("base_120d_estimated")) or (used_hist_5d and hist.get("base_5d_estimated")):
            _append_note(bond, "trend_history_base_estimated")
        confidence, confidence_reason = _derive_trend_confidence(
            hist,
            used_5d=used_hist_5d,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(bond, confidence)
        if confidence_reason:
            _append_note(bond, confidence_reason)
        if bond.get("trend") in (None, "未知", "待WebSearch补充", "待 WebSearch"):
            bond["trend"] = _infer_asset_trend(
                None,
                bond.get("change_5d_bp"),
                bond.get("change_120d_bp"),
                "bond",
            )
    stats["bonds"] += _backfill_cdb_proxy_changes_from_cn10y(market_data)

    for fx in market_data.get("forex", []) or []:
        symbol = fx.get("pair")
        current = _coerce_float(fx.get("current_rate"))
        if not symbol or current is None:
            continue
        hist = _calc_change_from_trend_history("forex", symbol, current, base_dir=base_dir, reference_date=reference_date)
        daily_hist = _calc_daily_change_from_trend_history("forex", symbol, current, base_dir=base_dir, reference_date=reference_date)
        used_hist_120d = False
        used_hist_1d = False
        existing_fx_evidence = dict(fx)
        _copy_valid_forex_daily_change_evidence(fx, existing_fx_evidence)
        _copy_valid_forex_120d_change_evidence(fx, existing_fx_evidence)
        should_backfill_daily = _should_backfill_forex_daily_change(fx)
        should_backfill_120d = _should_backfill_forex_120d_change(fx)
        if should_backfill_120d:
            if hist.get("change_120d") is not None:
                fx["change_120d"] = round(float(hist["change_120d"]), 2)
                _copy_valid_forex_120d_change_evidence(
                    fx,
                    {
                        "change_120d_basis": "trend_history",
                        "change_120d_base_date": hist.get("base_120d_date"),
                    },
                )
                stats["forex"] += 1
                used_hist_120d = True
            else:
                fx["change_120d"] = None
                _copy_valid_forex_120d_change_evidence(fx, {})
                reason = hist.get("reason_120d") or "trend_history_missing"
                _record_backfill_issue(metadata, "forex", symbol, "change_120d", reason)
                _append_note(fx, f"reason={reason}")
        if should_backfill_daily:
            if daily_hist.get("change_1d") is not None:
                fx["daily_change"] = round(float(daily_hist["change_1d"]), 2)
                _copy_valid_forex_daily_change_evidence(
                    fx,
                    {
                        "daily_change_basis": "trend_history",
                        "daily_change_base_date": daily_hist.get("base_1d_date"),
                    },
                )
                stats["forex"] += 1
                used_hist_1d = True
            else:
                fx["daily_change"] = None
                _copy_valid_forex_daily_change_evidence(fx, {})
                reason = daily_hist.get("reason_1d") or "trend_history_missing"
                _record_backfill_issue(metadata, "forex", symbol, "daily_change", reason)
                _append_note(fx, f"reason={reason}")
        if (used_hist_120d and hist.get("base_120d_estimated")) or (used_hist_1d and daily_hist.get("base_1d_estimated")):
            _append_note(fx, "trend_history_base_estimated")
        confidence, confidence_reason = _derive_trend_confidence(
            hist,
            used_5d=used_hist_1d,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(fx, confidence)
        if confidence_reason:
            _append_note(fx, confidence_reason)
        raw_trend = fx.get("trend")
        trend_daily_change = _usable_forex_change_value(fx, "daily_change")
        trend_120d_change = _usable_forex_change_value(fx, "change_120d")
        usable_raw_trend = _usable_forex_raw_trend(raw_trend, trend_daily_change, trend_120d_change)
        if usable_raw_trend in (None, "未知", "待WebSearch补充", "待 WebSearch"):
            fx["trend"] = _infer_asset_trend(
                None,
                trend_daily_change,
                trend_120d_change,
                "forex",
            )
        else:
            fx["trend"] = usable_raw_trend

    for comm in market_data.get("commodities", []) or []:
        symbol = comm.get("symbol")
        current = _coerce_float(comm.get("current_price"))
        if not symbol or current is None:
            continue
        hist = _calc_change_from_trend_history("commodities", symbol, current, base_dir=base_dir, reference_date=reference_date)
        daily_hist = _calc_daily_change_from_trend_history("commodities", symbol, current, base_dir=base_dir, reference_date=reference_date)
        used_hist_120d = False
        used_hist_1d = False
        if _should_backfill_numeric(comm.get("change_120d")):
            if hist.get("change_120d") is not None:
                comm["change_120d"] = round(float(hist["change_120d"]), 2)
                comm["change_120d_basis"] = "trend_history"
                stats["commodities"] += 1
                used_hist_120d = True
            else:
                comm["change_120d"] = None
                reason = hist.get("reason_120d") or "trend_history_missing"
                _record_backfill_issue(metadata, "commodities", symbol, "change_120d", reason)
                _append_note(comm, f"reason={reason}")
        if comm.get("daily_change") is None:
            if daily_hist.get("change_1d") is not None:
                comm["daily_change"] = round(float(daily_hist["change_1d"]), 2)
                comm["daily_change_basis"] = "change_1d"
                stats["commodities"] += 1
                used_hist_1d = True
            else:
                comm["daily_change"] = None
                reason = daily_hist.get("reason_1d") or "trend_history_missing"
                _record_backfill_issue(metadata, "commodities", symbol, "daily_change", reason)
                _append_note(comm, f"reason={reason}")
        if (used_hist_120d and hist.get("base_120d_estimated")) or (used_hist_1d and daily_hist.get("base_1d_estimated")):
            _append_note(comm, "trend_history_base_estimated")
        confidence, confidence_reason = _derive_trend_confidence(
            hist,
            used_5d=used_hist_1d,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(comm, confidence)
        if confidence_reason:
            _append_note(comm, confidence_reason)
        if comm.get("trend") in (None, "未知", "待WebSearch补充", "待 WebSearch"):
            comm["trend"] = _infer_asset_trend(
                None,
                comm.get("daily_change"),
                comm.get("ytd_change") if comm.get("ytd_change") is not None else comm.get("change_120d"),
                "commodity",
            )

    for idx in market_data.get("stock_indices", []) or []:
        symbol = idx.get("symbol")
        current = _coerce_float(idx.get("current_price"))
        if not symbol or current is None:
            continue
        hist = _calc_change_from_trend_history("stock_indices", symbol, current, base_dir=base_dir, reference_date=reference_date)
        used_hist_120d = False
        used_hist_5d = False
        if _should_backfill_numeric(idx.get("change_120d")):
            if hist.get("change_120d") is not None:
                idx["change_120d"] = round(float(hist["change_120d"]), 2)
                stats["stock_indices"] += 1
                used_hist_120d = True
            else:
                idx["change_120d"] = None
                reason = hist.get("reason_120d") or "trend_history_missing"
                _record_backfill_issue(metadata, "stock_indices", symbol, "change_120d", reason)
                _append_note(idx, f"reason={reason}")
        if idx.get("change_5d") is None:
            if hist.get("change_5d") is not None:
                idx["change_5d"] = round(float(hist["change_5d"]), 2)
                stats["stock_indices"] += 1
                used_hist_5d = True
            else:
                idx["change_5d"] = None
                reason = hist.get("reason_5d") or "trend_history_missing"
                _record_backfill_issue(metadata, "stock_indices", symbol, "change_5d", reason)
                _append_note(idx, f"reason={reason}")
        if (used_hist_120d and hist.get("base_120d_estimated")) or (used_hist_5d and hist.get("base_5d_estimated")):
            _append_note(idx, "trend_history_base_estimated")
        confidence, confidence_reason = _derive_trend_confidence(
            hist,
            used_5d=used_hist_5d,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(idx, confidence)
        if confidence_reason:
            _append_note(idx, confidence_reason)

    # fund_flow rollups from daily series
    for key, flow in (market_data.get("fund_flow", {}) or {}).items():
        if not isinstance(flow, dict):
            continue
        if not (_should_backfill_numeric(flow.get("recent_5d")) or _should_backfill_numeric(flow.get("total_120d"))):
            continue
        daily_series = load_daily_series(key, base_dir=base_dir)
        if not daily_series:
            continue

        override_value = _coerce_float(flow.get("current_value"))
        override_date = flow.get("current_date") or flow.get("date") or reference_date
        if override_value is not None:
            daily_series = apply_override(daily_series, override_value, override_date)

        recent_5d, full5, used_date, _ = compute_rollup(daily_series, end_date=reference_date, window=5)
        total_120d, full120, used_date_120, _ = compute_rollup(daily_series, end_date=reference_date, window=120)
        if recent_5d is not None and _should_backfill_numeric(flow.get("recent_5d")):
            flow["recent_5d"] = round(float(recent_5d), 2)
            stats["fund_flow"] += 1
        if total_120d is not None and _should_backfill_numeric(flow.get("total_120d")):
            flow["total_120d"] = round(float(total_120d), 2)
            stats["fund_flow"] += 1

        trend_base = flow.get("recent_5d")
        if flow.get("trend") in (None, "未知", "待获取", "待WebSearch补充", "待 WebSearch"):
            flow["trend"] = _infer_trend(flow.get("trend"), trend_base)

        anomaly = any(
            value == 0 for value in (flow.get("recent_5d"), flow.get("total_120d")) if value is not None
        )
        flow["source"] = SOURCE_ANOMALY_LABEL if anomaly else DEFAULT_SOURCE_LABEL
        note_parts: List[str] = []
        existing_note = flow.get("note")
        if isinstance(existing_note, str) and existing_note:
            note_parts.append(existing_note)
        note_parts.append(f"日度序列回算:截至{used_date_120 or used_date}")
        if override_value is not None:
            note_parts.append("当日值参考新闻")
        if not full5 or not full120:
            note_parts.append("window不足已估计")
        flow["note"] = "；".join(note_parts)

    # macro indicators previous_value / change_rate
    for key, indicator in (market_data.get("macro_indicators", {}) or {}).items():
        if not isinstance(indicator, dict):
            continue
        current = _coerce_float(indicator.get("current_value"))
        if current is None:
            continue
        prev_missing = indicator.get("previous_value") is None
        change_missing = indicator.get("change_rate") is None
        if prev_missing or change_missing:
            hist_prev = _calc_prev_from_event_history(key, current, reference_date, base_dir=base_dir)
            if prev_missing and hist_prev.get("previous_value") is not None:
                indicator["previous_value"] = hist_prev.get("previous_value")
            if change_missing and hist_prev.get("change_rate") is not None:
                indicator["change_rate"] = hist_prev.get("change_rate")
            reason = hist_prev.get("reason") or "manual_incomplete"
            if indicator.get("previous_value") is None:
                _append_note(indicator, f"reason={reason}")
                _record_backfill_issue(metadata, "macro_indicators", key, "previous_value", reason)
            if indicator.get("change_rate") is None:
                reason = hist_prev.get("reason") or "manual_incomplete"
                _append_note(indicator, f"reason={reason}")
                _record_backfill_issue(metadata, "macro_indicators", key, "change_rate", reason)
            if (
                indicator.get("previous_value") is not None
                and indicator.get("change_rate") is not None
            ):
                _remove_note_markers(indicator, ("reason=no_previous_value", "无前值可比"))
            stats["macro_indicators"] += 1

    # monetary policy change_from_120d
    for key, policy in (market_data.get("monetary_policy", {}) or {}).items():
        if not isinstance(policy, dict):
            continue
        current = _coerce_float(policy.get("current_value"))
        if current is None:
            continue
        if policy.get("change_from_120d") is None:
            hist = _calc_change_from_event_history(key, current, reference_date, base_dir=base_dir)
            used_hist_120d = False
            if hist.get("change_from_120d") is not None:
                policy["change_from_120d"] = hist.get("change_from_120d")
                used_hist_120d = True
            reason = hist.get("reason")
            if reason:
                if reason == "no_previous_value":
                    _append_note(policy, "无前值可比")
                _append_note(policy, f"reason={reason}")
                _record_backfill_issue(metadata, "monetary_policy", key, "change_from_120d", reason)
            elif used_hist_120d:
                _remove_note_markers(policy, ("reason=no_previous_value", "无前值可比"))
            if hist.get("base_estimated"):
                policy["is_estimated"] = True
                _append_note(policy, "trend_history_base_estimated")
                if used_hist_120d:
                    _merge_trend_confidence(policy, "low")
            elif used_hist_120d:
                _merge_trend_confidence(policy, "high")
            stats["monetary_policy"] += 1

    return stats


def _run_post_write_trend_backfill(
    market_data: Dict[str, Any],
    output_path: Path,
    *,
    base_dir: Optional[Path] = None,
) -> Dict[str, int]:
    """在 trend_history 最终写入后，基于最新明细再回填一轮变化值。"""
    metadata = market_data.setdefault("metadata", {})
    metadata["trend_backfill_issues"] = []

    if base_dir is None:
        stats = _backfill_trend_changes(market_data)
    else:
        stats = _backfill_trend_changes(market_data, base_dir=base_dir)
    gap_summary = _refresh_stage2_gap_monitor(market_data)
    _refresh_stage2_notes(metadata, gap_summary)
    _cleanup_metadata_missing(metadata, market_data)
    _apply_pipeline_quality_state(market_data)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(market_data, f, ensure_ascii=False, indent=2)
    return stats


def _sync_backfill_issues_to_logs(
    market_data: Dict[str, Any],
    *,
    date_override: Optional[str] = None,
    gap_monitor_path: Optional[Path] = None,
) -> None:
    """将趋势派生失败原因和非阻断告警写入 observability，并按当前状态重写当日 gap_monitor。"""
    metadata = market_data.get("metadata", {}) if isinstance(market_data, dict) else {}
    issues = metadata.get("trend_backfill_issues") or []
    non_blocking_warnings = metadata.get("non_blocking_warnings") or []
    run_paths = build_run_paths_from_reference(
        date=date_override,
        payload=market_data,
        fallback_to_today=True,
    )

    _rewrite_gap_monitor_after_injection(
        market_data,
        date_override=date_override,
        gap_monitor_path=gap_monitor_path,
        extra_issues=issues,
    )

    if not issues and not non_blocking_warnings:
        return

    observability_path = run_paths.observability
    payload: Dict[str, Any] = {}
    if observability_path.exists():
        try:
            payload = json.loads(observability_path.read_text(encoding="utf-8")) or {}
        except Exception:
            payload = {}
    payload.setdefault("generated_at", datetime.now().isoformat())
    payload["data_quality_issues"] = _merge_quality_issues(payload.get("data_quality_issues", []), issues)

    existing_warnings = payload.get("non_blocking_warnings", [])
    if not isinstance(existing_warnings, list):
        existing_warnings = []
    merged_warnings: List[Dict[str, Any]] = []
    seen = set()
    for row in list(existing_warnings) + list(non_blocking_warnings or []):
        if not isinstance(row, dict):
            continue
        sig = (row.get("code"), row.get("key"), row.get("source_url"), row.get("message"))
        if sig in seen:
            continue
        seen.add(sig)
        merged_warnings.append(row)
    if merged_warnings:
        payload["non_blocking_warnings"] = merged_warnings

    observability_path.parent.mkdir(parents=True, exist_ok=True)
    observability_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def _merge_stock_index_entry(orig: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """更新已存在的股票指数条目，缺失字段用原值或默认值兜底。"""
    merged = dict(orig)
    merged['symbol'] = payload.get('symbol', orig.get('symbol'))
    merged['name'] = payload.get('name', orig.get('name', merged['symbol']))
    merged['current_price'] = _coerce_float(payload.get('current_price') or payload.get('close') or payload.get('price')) or orig.get('current_price', 0.0)
    merged['change_5d'] = _coerce_float(payload.get('change_5d') or payload.get('change_5d_pct') or payload.get('weekly_change')) or orig.get('change_5d', 0.0)
    merged['change_120d'] = _coerce_float(
        payload.get('change_120d') or payload.get('change_120d_pct') or payload.get('ytd_change') or payload.get('change_ytd')
    ) or orig.get('change_120d', 0.0)
    merged['above_ma50'] = _coerce_bool(payload.get('above_ma50') if 'above_ma50' in payload else orig.get('above_ma50', False))
    merged['above_ma200'] = _coerce_bool(payload.get('above_ma200') if 'above_ma200' in payload else orig.get('above_ma200', False))
    merged['ma50_slope'] = _coerce_float(payload.get('ma50_slope')) or orig.get('ma50_slope', 0.0)
    merged['volatility_30d'] = _coerce_float(payload.get('volatility_30d') or payload.get('volatility')) or orig.get('volatility_30d', 0.0)
    merged['trend_score'] = int(payload.get('trend_score', orig.get('trend_score', 0)))
    merged['trend_label'] = payload.get('trend_label', orig.get('trend_label', '中性'))
    merged['source'] = _format_source_label(payload.get('source') or orig.get('source'))
    _copy_source_url(merged, payload)
    _copy_payload_metadata_fields(
        merged,
        payload,
        ("is_estimated", "estimation_method", "metric_basis", "confidence"),
    )
    return merged


def _build_stock_index_entry(symbol: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """为缺失的指数（如000016）构造完整条目，确保 Pydantic 校验通过。"""
    entry = {
        "symbol": symbol,
        "name": payload.get('name', symbol),
        "current_price": _coerce_float(payload.get('current_price') or payload.get('close') or payload.get('price')) or 0.0,
        "change_5d": _coerce_float(payload.get('change_5d') or payload.get('change_5d_pct') or payload.get('weekly_change')) or 0.0,
        "change_120d": _coerce_float(
            payload.get('change_120d') or payload.get('change_120d_pct') or payload.get('ytd_change') or payload.get('change_ytd')
        ) or 0.0,
        "above_ma50": _coerce_bool(payload.get('above_ma50')),
        "above_ma200": _coerce_bool(payload.get('above_ma200')),
        "ma50_slope": _coerce_float(payload.get('ma50_slope')) or 0.0,
        "volatility_30d": _coerce_float(payload.get('volatility_30d') or payload.get('volatility')) or 0.0,
        "trend_score": int(payload.get('trend_score', 0)),
        "trend_label": payload.get('trend_label', '中性'),
        "source": _format_source_label(payload.get('source')),
    }
    _copy_source_url(entry, payload)
    _copy_payload_metadata_fields(
        entry,
        payload,
        ("is_estimated", "estimation_method", "metric_basis", "confidence"),
    )
    return entry


def _merge_bond_entry(
    existing: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    is_manual: bool = False,
    trend_history_base_dir: Optional[Path] = DEFAULT_BASE_DIR,
) -> Dict[str, Any]:
    merged = dict(existing)
    merged['symbol'] = payload.get('symbol', existing.get('symbol'))
    merged['name'] = payload.get('name', existing.get('name', merged['symbol']))
    merged['current_yield'] = _coerce_float(payload.get('current_yield')) or existing.get('current_yield')
    # 保留债券日期字段，供报告侧“当日数据”校验与展示
    if payload.get('date'):
        merged['date'] = payload.get('date')
    if payload.get('as_of_date'):
        merged['as_of_date'] = payload.get('as_of_date')
    if payload.get('report_period'):
        merged.setdefault('as_of_date', payload.get('report_period'))
        merged.setdefault('date', payload.get('report_period'))

    # 从 trend_history 计算 bp 变化值
    current_yield = merged.get('current_yield')
    symbol = merged.get('symbol')
    used_hist_5d = False
    used_hist_120d = False
    if current_yield and symbol and trend_history_base_dir is not None:
        hist_changes = _calc_change_from_trend_history(
            "bonds",
            symbol,
            current_yield,
            base_dir=trend_history_base_dir,
        )
        merged['change_5d_bp'] = _coerce_float(payload.get('change_5d_bp'))
        if merged['change_5d_bp'] is None:
            hist_5d = _coerce_float(hist_changes.get('change_5d_bp'))
            if hist_5d is not None:
                merged['change_5d_bp'] = hist_5d
                used_hist_5d = True
            else:
                merged['change_5d_bp'] = existing.get('change_5d_bp', 0.0)
        merged['change_120d_bp'] = _coerce_float(payload.get('change_120d_bp'))
        if merged['change_120d_bp'] is None:
            hist_120d = _coerce_float(hist_changes.get('change_120d_bp'))
            if hist_120d is not None:
                merged['change_120d_bp'] = hist_120d
                used_hist_120d = True
            else:
                merged['change_120d_bp'] = existing.get('change_120d_bp', 0.0)
        confidence, confidence_reason = _derive_trend_confidence(
            hist_changes,
            used_5d=used_hist_5d,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(merged, confidence)
        if confidence_reason:
            _append_note(merged, confidence_reason)
    else:
        merged['change_5d_bp'] = _coerce_float(payload.get('change_5d_bp')) or existing.get('change_5d_bp', 0.0)
        merged['change_120d_bp'] = _coerce_float(payload.get('change_120d_bp')) or existing.get('change_120d_bp', 0.0)
    _copy_source_url(merged, payload)
    _copy_payload_metadata_fields(merged, payload, ("estimation_method", "metric_basis", "confidence"))

    # 自动推断债券趋势（基于bp变化）
    raw_trend = payload.get('trend', existing.get('trend'))
    merged['trend'] = _infer_asset_trend(raw_trend, merged.get('change_5d_bp'), merged.get('change_120d_bp'), "bond")
    merged['source'] = _format_source_label(payload.get('source') or existing.get('source'))
    payload_estimated = payload.get('is_estimated')
    if payload_estimated is not None:
        merged['is_estimated'] = bool(payload_estimated)
    else:
        merged['is_estimated'] = bool(existing.get('is_estimated', False))
        if is_manual and _has_valid_value(merged.get('current_yield')):
            merged['is_estimated'] = False
    merged['note'] = payload.get('note', existing.get('note'))
    if is_manual:
        _apply_manual_official_estimation_rule("bonds", str(merged.get("symbol") or ""), payload, merged)
    return merged


def _merge_commodity_entry(
    existing: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    is_manual: bool = False,
    trend_history_base_dir: Optional[Path] = DEFAULT_BASE_DIR,
) -> Dict[str, Any]:
    merged = dict(existing)
    merged['symbol'] = payload.get('symbol', existing.get('symbol'))
    merged['name'] = payload.get('name', existing.get('name', merged['symbol']))
    payload_current_price = _coerce_float(payload.get('current_price'))
    if payload_current_price is not None:
        merged['current_price'] = payload_current_price
    else:
        merged['current_price'] = existing.get('current_price')
    merged['unit'] = payload.get('unit', existing.get('unit', ''))

    # 从 trend_history 计算变化值
    current_price = merged.get('current_price')
    symbol = merged.get('symbol')
    explicit_daily_change = _coerce_percent(payload.get('daily_change'))
    daily_change_base_price = _coerce_float(payload.get('previous_price'))
    daily_change_basis_field = "previous_price"
    if (
        daily_change_base_price is None
        and explicit_daily_change is None
        and payload.get('previous_value') is not None
    ):
        daily_change_base_price = _coerce_float(payload.get('previous_value'))
        daily_change_basis_field = "previous_value"
    payload_daily_change = _pct_change(current_price, daily_change_base_price)
    used_hist_120d = False
    payload_120d = _coerce_percent(payload.get('change_120d'))
    if payload_120d is None:
        payload_120d = _coerce_percent(payload.get('change_120d_pct'))
    if payload_120d is not None:
        merged['change_120d'] = payload_120d
        merged['change_120d_basis'] = payload.get('change_120d_basis') or ('websearch_manual' if is_manual else 'payload')
    if current_price and symbol and trend_history_base_dir is not None:
        hist_changes = _calc_change_from_trend_history(
            "commodities",
            symbol,
            current_price,
            base_dir=trend_history_base_dir,
        )
        merged['daily_change'] = explicit_daily_change
        if merged['daily_change'] is None:
            merged['daily_change'] = existing.get('daily_change')
        merged['ytd_change'] = _coerce_percent(payload.get('ytd_change'))
        if merged['ytd_change'] is None:
            merged['ytd_change'] = existing.get('ytd_change')
        elif payload.get('ytd_change_basis') or 'ytd_change_basis' not in merged:
            merged['ytd_change_basis'] = payload.get('ytd_change_basis') or 'year_to_date'
        hist_120d = _coerce_float(hist_changes.get('change_120d'))
        if payload_120d is None and hist_120d is not None:
            merged['change_120d'] = hist_120d
            merged['change_120d_basis'] = 'trend_history'
            used_hist_120d = True
        confidence, confidence_reason = _derive_trend_confidence(
            hist_changes,
            used_5d=False,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(merged, confidence)
        if confidence_reason:
            _append_note(merged, confidence_reason)
    else:
        merged['daily_change'] = explicit_daily_change
        if merged['daily_change'] is None:
            merged['daily_change'] = existing.get('daily_change')
        merged['ytd_change'] = _coerce_percent(payload.get('ytd_change'))
        if merged['ytd_change'] is None:
            merged['ytd_change'] = existing.get('ytd_change')
        elif payload.get('ytd_change_basis') or 'ytd_change_basis' not in merged:
            merged['ytd_change_basis'] = payload.get('ytd_change_basis') or 'year_to_date'
        if payload_120d is None:
            merged['change_120d'] = existing.get('change_120d')
    if payload_daily_change is not None:
        merged['daily_change'] = payload_daily_change
        merged['daily_change_base_price'] = daily_change_base_price
        if payload.get('previous_date'):
            merged['daily_change_base_date'] = payload.get('previous_date')
        basis_prefix = "manual" if is_manual else "payload"
        merged['daily_change_basis'] = f"{basis_prefix}_{daily_change_basis_field}"
    _copy_source_url(merged, payload)
    _copy_payload_metadata_fields(
        merged,
        payload,
        ("is_estimated", "estimation_method", "metric_basis", "confidence"),
    )

    # 自动推断商品趋势（基于涨跌幅）
    raw_trend = payload.get('trend', existing.get('trend'))
    merged['trend'] = _infer_asset_trend(
        raw_trend,
        merged.get('daily_change'),
        merged.get('ytd_change') if merged.get('ytd_change') is not None else merged.get('change_120d'),
        "commodity",
    )
    merged['source'] = _format_source_label(payload.get('source') or existing.get('source'))
    merged['timestamp'] = payload.get('timestamp') or existing.get('timestamp') or datetime.now().strftime("%Y-%m-%d")
    merged['note'] = payload.get('note', existing.get('note'))
    if is_manual and 'is_estimated' not in payload and _has_valid_value(merged.get('current_price')):
        if 'is_estimated' in merged:
            merged['is_estimated'] = False
    if is_manual:
        _apply_manual_official_estimation_rule("commodities", str(merged.get("symbol") or ""), payload, merged)
    return merged


def _merge_forex_entry(
    orig: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    is_manual: bool = False,
    trend_history_base_dir: Optional[Path] = DEFAULT_BASE_DIR,
) -> Dict[str, Any]:
    merged = dict(orig)
    merged['pair'] = payload.get('pair', orig.get('pair'))
    merged['name'] = payload.get('name', orig.get('name', merged['pair']))
    merged['current_rate'] = _coerce_float(payload.get('current_rate')) or merged.get('current_rate')

    # 从 trend_history 计算变化值（daily_change 取前一交易日变化）
    current_rate = merged.get('current_rate')
    symbol = merged.get('pair')
    payload_has_daily_change = "daily_change" in payload
    payload_daily_change = _coerce_percent(payload.get('daily_change'))
    payload_has_120d_change = "change_120d" in payload
    payload_120d_change = _coerce_percent(payload.get('change_120d'))
    used_hist_1d = False
    used_hist_120d = False
    if current_rate and symbol and trend_history_base_dir is not None:
        hist_changes = _calc_change_from_trend_history(
            "forex",
            symbol,
            current_rate,
            base_dir=trend_history_base_dir,
        )
        daily_hist = _calc_daily_change_from_trend_history(
            "forex",
            symbol,
            current_rate,
            base_dir=trend_history_base_dir,
        )
        merged['daily_change'] = payload_daily_change
        if merged['daily_change'] is None:
            hist_1d = _coerce_float(daily_hist.get('change_1d'))
            if hist_1d is not None:
                merged['daily_change'] = hist_1d
                _copy_valid_forex_daily_change_evidence(
                    merged,
                    {
                        "daily_change_basis": "trend_history",
                        "daily_change_base_date": daily_hist.get("base_1d_date"),
                    },
                )
                used_hist_1d = True
            else:
                merged['daily_change'] = orig.get('daily_change')
                _copy_valid_forex_daily_change_evidence(merged, orig)
        merged['change_120d'] = payload_120d_change
        if merged['change_120d'] is None:
            hist_120d = _coerce_float(hist_changes.get('change_120d'))
            if hist_120d is not None:
                merged['change_120d'] = hist_120d
                _copy_valid_forex_120d_change_evidence(
                    merged,
                    {
                        "change_120d_basis": "trend_history",
                        "change_120d_base_date": hist_changes.get("base_120d_date"),
                    },
                )
                used_hist_120d = True
            else:
                merged['change_120d'] = orig.get('change_120d')
                _copy_valid_forex_120d_change_evidence(merged, orig)
        else:
            _copy_valid_forex_120d_change_evidence(merged, payload)
        confidence, confidence_reason = _derive_trend_confidence(
            hist_changes,
            used_5d=used_hist_1d,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(merged, confidence)
        if confidence_reason:
            _append_note(merged, confidence_reason)
        if used_hist_1d and daily_hist.get("base_1d_estimated"):
            _merge_trend_confidence(merged, "low")
            _append_note(merged, "trend_history_base_estimated")
    else:
        merged['daily_change'] = payload_daily_change
        if merged['daily_change'] is None:
            merged['daily_change'] = orig.get('daily_change')
            _copy_valid_forex_daily_change_evidence(merged, orig)
        merged['change_120d'] = payload_120d_change
        if merged['change_120d'] is None:
            merged['change_120d'] = orig.get('change_120d')
            _copy_valid_forex_120d_change_evidence(merged, orig)
        else:
            _copy_valid_forex_120d_change_evidence(merged, payload)
    if payload_has_daily_change and not used_hist_1d:
        _copy_valid_forex_daily_change_evidence(merged, payload)
    if payload_has_120d_change and not used_hist_120d:
        _copy_valid_forex_120d_change_evidence(merged, payload)
    _copy_source_url(merged, payload)
    _copy_payload_metadata_fields(
        merged,
        payload,
        ("is_estimated", "estimation_method", "metric_basis", "confidence"),
    )

    # 自动推断外汇趋势（基于涨跌幅）
    raw_trend = payload.get('trend', orig.get('trend'))
    trend_daily_change = _usable_forex_change_value(merged, "daily_change")
    trend_120d_change = _usable_forex_change_value(merged, "change_120d")
    merged['trend'] = _infer_asset_trend(
        _usable_forex_raw_trend(raw_trend, trend_daily_change, trend_120d_change),
        trend_daily_change,
        trend_120d_change,
        "forex",
    )
    merged['source'] = _format_source_label(payload.get('source'))
    merged['note'] = payload.get('note', orig.get('note'))
    if is_manual and 'is_estimated' not in payload and _has_valid_value(merged.get('current_rate')):
        if 'is_estimated' in merged:
            merged['is_estimated'] = False
    if is_manual:
        _apply_manual_official_estimation_rule("forex", str(merged.get("pair") or ""), payload, merged)
    return merged


def _build_forex_entry(
    payload: Dict[str, Any],
    *,
    is_manual: bool = False,
    trend_history_base_dir: Optional[Path] = DEFAULT_BASE_DIR,
) -> Dict[str, Any]:
    pair = payload.get('pair') or payload.get('symbol') or 'UNKNOWN'
    current_rate = _coerce_float(payload.get('current_rate'))

    # 从 trend_history 计算变化值（daily_change 取前一交易日变化）
    payload_daily_change = _coerce_percent(payload.get('daily_change'))
    daily_change = payload_daily_change
    payload_120d_change = _coerce_percent(payload.get('change_120d'))
    change_120d = payload_120d_change
    trend_history_daily_evidence: Optional[Dict[str, Any]] = None
    trend_history_120d_evidence: Optional[Dict[str, Any]] = None
    if current_rate and pair and trend_history_base_dir is not None:
        hist_changes = _calc_change_from_trend_history(
            "forex",
            pair,
            current_rate,
            base_dir=trend_history_base_dir,
        )
        daily_hist = _calc_daily_change_from_trend_history(
            "forex",
            pair,
            current_rate,
            base_dir=trend_history_base_dir,
        )
        if daily_change is None:
            hist_daily_change = _coerce_float(daily_hist.get('change_1d'))
            if hist_daily_change is not None:
                daily_change = hist_daily_change
                trend_history_daily_evidence = {
                    "daily_change_basis": "trend_history",
                    "daily_change_base_date": daily_hist.get("base_1d_date"),
                }
        if change_120d is None:
            hist_120d_change = _coerce_float(hist_changes.get('change_120d'))
            if hist_120d_change is not None:
                change_120d = hist_120d_change
                trend_history_120d_evidence = {
                    "change_120d_basis": "trend_history",
                    "change_120d_base_date": hist_changes.get("base_120d_date"),
                }

    entry = {
        "pair": pair,
        "name": payload.get('name', pair),
        "current_rate": current_rate,
        "daily_change": daily_change,
        "change_120d": change_120d,
        "source": _format_source_label(payload.get('source')),
        "note": payload.get("note"),
    }
    if payload_daily_change is not None:
        _copy_valid_forex_daily_change_evidence(entry, payload)
    elif trend_history_daily_evidence is not None:
        _copy_valid_forex_daily_change_evidence(entry, trend_history_daily_evidence)
    if payload_120d_change is not None:
        _copy_valid_forex_120d_change_evidence(entry, payload)
    elif trend_history_120d_evidence is not None:
        _copy_valid_forex_120d_change_evidence(entry, trend_history_120d_evidence)
    _copy_source_url(entry, payload)
    _copy_payload_metadata_fields(
        entry,
        payload,
        ("is_estimated", "estimation_method", "metric_basis", "confidence"),
    )
    trend_daily_change = _usable_forex_change_value(entry, "daily_change")
    trend_120d_change = _usable_forex_change_value(entry, "change_120d")
    raw_trend = _usable_forex_raw_trend(payload.get("trend"), trend_daily_change, trend_120d_change)
    entry["trend"] = _infer_asset_trend(
        raw_trend,
        trend_daily_change,
        trend_120d_change,
        "forex",
    )
    if is_manual:
        _apply_manual_official_estimation_rule("forex", pair, payload, entry)
    return entry

def _default_cli_paths() -> Tuple[Path, Path, Path]:
    run_paths = build_run_paths_from_reference(fallback_to_today=True)
    return (
        run_paths.market_data_stage2,
        run_paths.websearch_results_manual,
        run_paths.market_data_complete,
    )


def parse_args() -> argparse.Namespace:
    default_market, default_websearch, default_output = _default_cli_paths()
    parser = argparse.ArgumentParser(
        description="Stage2.5 WebSearch 数据注入脚本",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "market_data_path",
        nargs="?",
        default=str(default_market),
        help="Stage2 产出的市场数据 JSON 路径",
    )
    parser.add_argument(
        "websearch_path",
        nargs="?",
        default=str(default_websearch),
        help="WebSearch 结果 JSON 路径（支持 Stage2 results 或 manual schema）",
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        default=str(default_output),
        help="注入后的完整市场数据输出路径",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="覆盖日期（YYYY-MM-DD 或 YYYYMMDD），用于质量指标/gap_monitor 文件名",
    )
    parser.add_argument(
        "--gap-monitor-path",
        default=None,
        help="指定重写的 gap_monitor 路径；不传则默认 data/runs/YYYYMMDD/gap_monitor.json",
    )
    parser.add_argument(
        "--backfill-trend",
        dest="backfill_trend",
        action="store_true",
        default=True,
        help="启用 trend_history 回填（默认开启）",
    )
    parser.add_argument(
        "--no-backfill-trend",
        "--disable-backfill-trend",
        dest="backfill_trend",
        action="store_false",
        help="禁用 trend_history 回填",
    )
    parser.add_argument(
        "--override-stale",
        dest="override_stale",
        action="store_true",
        default=True,
        help="允许手工注入覆盖 is_stale=True 的宏观/货币字段（默认开启）",
    )
    parser.add_argument(
        "--no-override-stale",
        dest="override_stale",
        action="store_false",
        help="禁用 stale 覆盖，仅填充 current_value 为空的字段",
    )
    parser.add_argument(
        "--force-override",
        action="store_true",
        default=False,
        help="强制覆盖已有值（应急模式，谨慎使用）",
    )
    parser.add_argument(
        "--trend-history-base-dir",
        default=None,
        help="指定 trend_history/min 基础目录；测试夹具可传入临时目录隔离真实历史",
    )
    parser.add_argument(
        "--disable-trend-history-write",
        action="store_true",
        default=False,
        help="禁用 Stage2.5 最终 trend_history 写入；只影响写入，不放松 Stage3/Stage4 gate",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    market_data_arg = getattr(args, "market_data_path", getattr(args, "input_file", None))
    websearch_arg = getattr(args, "websearch_path", getattr(args, "websearch_file", None))
    output_arg = getattr(args, "output_path", getattr(args, "output_file", None))
    market_data_file = Path(market_data_arg).expanduser().resolve()
    websearch_file = Path(websearch_arg).expanduser().resolve()
    output_file = Path(output_arg).expanduser().resolve()
    gap_monitor_path = (
        Path(args.gap_monitor_path).expanduser().resolve()
        if args.gap_monitor_path
        else None
    )
    trend_history_base_dir = (
        Path(args.trend_history_base_dir).expanduser().resolve()
        if args.trend_history_base_dir
        else None
    )

    if not market_data_file.exists():
        print(f"[ERROR] 市场数据文件不存在: {market_data_file}")
        sys.exit(1)
    if not websearch_file.exists():
        print(f"[ERROR] WebSearch结果文件不存在: {websearch_file}")
        sys.exit(1)

    try:
        run_dir = run_dir_from_artifact(output_file)
        with DailyRunLock(run_dir, owner="stage2_5_injector").acquire():
            inject_websearch_data(
                market_data_path=market_data_file,
                websearch_path=websearch_file,
                output_path=output_file,
                backfill_trend=args.backfill_trend,
                date_override=args.date,
                gap_monitor_path=gap_monitor_path,
                override_stale=args.override_stale,
                force_override=args.force_override,
                trend_history_base_dir=trend_history_base_dir,
                disable_trend_history_write=args.disable_trend_history_write,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] 数据注入失败: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
