import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from datasource.utils.key_aliases import (
    MONETARY_KEY_ALIASES,
    normalize_monetary_section,
)
from datasource.utils.contract_validation import (
    ContractValidationError,
    validate_market_data,
)
from datasource.utils.json_io import atomic_write_json
from datasource.utils.policy_rules import get_non_blocking_warning_rules
from datasource.utils.quality_metrics import build_quality_metrics
from datasource.utils.run_paths import build_run_paths_from_reference
from datasource.utils.trend_history_store import (
    DEFAULT_BASE_DIR,
    write_from_market_data,
    write_trend_history_gap_snapshot,
)

from datasource.engines.stage2_5 import entry_mergers, trend_backfill
from datasource.engines.stage2_5.common import (
    _apply_pipeline_quality_state,
    _attach_source_url,
    _coerce_float,
    _extract_domain,
    _has_valid_value,
    _is_estimated_allowlisted_entry,
    _policy_rules,
)
from datasource.engines.stage2_5.fund_flow import _normalize_fund_flow_payload
from datasource.engines.stage2_5.gap_sync import (
    _append_missing_item,
    _cleanup_metadata_missing,
    _collect_missing_source_urls,
    _refresh_stage2_gap_monitor,
    _refresh_stage2_notes,
    _remove_missing_item,
    _remove_top_missing,
    _remove_top_missing_on_skip,
)
from datasource.engines.stage2_5.schema_coercion import (
    _coerce_stage2_results_to_schema,
    _normalize_keyed_list,
    _normalize_monetary_payload,
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


@dataclass
class InjectionSummary:
    injected_items: List[Dict[str, Any]] = field(default_factory=list)
    metadata_updated_items: List[Dict[str, Any]] = field(default_factory=list)
    skipped_existing_items: List[Dict[str, Any]] = field(default_factory=list)
    skipped_no_parseable_value_items: List[Dict[str, Any]] = field(
        default_factory=list
    )
    forced_override_items: List[Dict[str, Any]] = field(default_factory=list)
    fund_flow_forced_estimated_items: List[Dict[str, Any]] = field(
        default_factory=list
    )

    def _record(
        self,
        bucket: List[Dict[str, Any]],
        category: str,
        key: str,
        **details: Any,
    ) -> None:
        item = {"category": category, "key": str(key)}
        item.update({k: v for k, v in details.items() if v is not None})
        bucket.append(item)

    def injected(self, category: str, key: str, **details: Any) -> None:
        self._record(self.injected_items, category, key, **details)

    def metadata_updated(
        self,
        category: str,
        key: str,
        reason: str,
        existing: Any,
        incoming: Any,
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
        self,
        category: str,
        key: str,
        reason: str,
        existing: Any,
        incoming: Any,
    ) -> None:
        self._record(
            self.skipped_existing_items,
            category,
            key,
            reason=reason,
            existing_value=existing,
            incoming_value=incoming,
        )

    def skipped_no_parseable_value(
        self, category: str, key: str, **details: Any
    ) -> None:
        self._record(
            self.skipped_no_parseable_value_items, category, key, **details
        )

    def forced_override(
        self, category: str, key: str, existing: Any, incoming: Any
    ) -> None:
        self._record(
            self.forced_override_items,
            category,
            key,
            reason="force_override",
            existing_value=existing,
            incoming_value=incoming,
        )

    def fund_flow_forced_estimated(
        self, category: str, key: str, **details: Any
    ) -> None:
        self._record(
            self.fund_flow_forced_estimated_items, category, key, **details
        )

    def to_dict(self) -> Dict[str, Any]:
        buckets = {
            "injected": self.injected_items,
            "metadata_updated": self.metadata_updated_items,
            "skipped_existing": self.skipped_existing_items,
            "skipped_no_parseable_value": (
                self.skipped_no_parseable_value_items
            ),
            "forced_override": self.forced_override_items,
            "fund_flow_forced_estimated": (
                self.fund_flow_forced_estimated_items
            ),
        }
        return {
            "counts": {name: len(items) for name, items in buckets.items()},
            **{name: list(items) for name, items in buckets.items()},
        }


def _append_non_blocking_warning(
    market_data: Dict[str, Any], warning: Dict[str, Any]
) -> None:
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
    risk_domains = [
        str(d).lower()
        for d in (warning_rules.get("gc_f_risk_domains") or [])
        if str(d).strip()
    ]
    anomaly_threshold = float(
        warning_rules.get("gc_f_anomaly_threshold_pct") or 8.0
    )
    warnings: List[Dict[str, Any]] = []

    for item in (
        websearch_raw.get("results", [])
        if isinstance(websearch_raw, dict)
        else []
    ):
        task = item.get("task", {}) if isinstance(item, dict) else {}
        if task.get("indicator_key") != "GC=F":
            continue
        extraction = (
            item.get("extraction", {}) if isinstance(item, dict) else {}
        )
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
                        "message": (
                            f"GC=F 价格变动 {pct:.2f}% 超过阈值 "
                            f"{anomaly_threshold:.1f}%"
                        ),
                    }
                )
            break

    return warnings


def _derive_date_compact(
    payload: Dict[str, Any], override: Optional[str] = None
) -> str:
    """从元数据推导 YYYYMMDD 字符串，支持外部覆盖。"""
    if override:
        return str(override).replace("-", "")
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    date_val = (
        metadata.get("date")
        or metadata.get("end_date")
        or metadata.get("start_date")
    )
    if date_val:
        return str(date_val).replace("-", "")
    return datetime.now().strftime("%Y%m%d")


def _enforce_quality_blockers(
    market_data: Dict[str, Any],
) -> List[Dict[str, str]]:
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
            if entry.get(
                "is_estimated"
            ) and not _is_estimated_allowlisted_entry(
                "macro_indicators", str(key), entry
            ):
                _add("macro_indicators", key, "estimated_not_allowed")
            if (
                entry.get("previous_value") is None
                or entry.get("change_rate") is None
            ):
                _add("macro_indicators", key, "missing_compare_values")

    for key, entry in (market_data.get("monetary_policy", {}) or {}).items():
        if not isinstance(entry, dict):
            continue
        if _has_valid_value(entry.get("current_value")):
            if entry.get(
                "is_estimated"
            ) and not _is_estimated_allowlisted_entry(
                "monetary_policy", str(key), entry
            ):
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
            and not _is_estimated_allowlisted_entry(
                "commodities", str(symbol), comm
            )
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
            and not _is_estimated_allowlisted_entry(
                "stock_indices", str(symbol), idx
            )
        ):
            _add("stock_indices", str(symbol), "estimated_not_allowed")

    for flow_key, flow in (market_data.get("fund_flow", {}) or {}).items():
        if not isinstance(flow, dict):
            continue
        if str(flow_key) != "etf":
            continue
        if not (
            _has_valid_value(flow.get("recent_5d"))
            and _has_valid_value(flow.get("total_120d"))
        ):
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
    gap_view = (
        state.get("gap_monitor_view", {}) if isinstance(state, dict) else {}
    )
    gap_payload = {
        "generated_at": datetime.now().isoformat(),
        "manual_required": list(gap_view.get("manual_required") or []),
        "pending_tasks": list(gap_view.get("pending_tasks") or []),
        "data_quality_issues": list(state.get("quality_blockers") or []),
        "quality_blockers": list(state.get("quality_blockers") or []),
    }
    if gap_monitor_path is not None:
        atomic_write_json(gap_payload, gap_monitor_path)

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
    atomic_write_json(quality_payload, quality_metrics_path)

    atomic_write_json(
        state.get("policy_evaluation") or {},
        policy_evaluation_path,
    )


def _cleanup_monetary_aliases(
    market_data: Dict[str, Any], metadata: Dict[str, Any]
) -> None:
    """清理货币政策别名重复项（canonical 有值、alias 仍为占位时删除 alias）。"""
    section = (
        market_data.get("monetary_policy", {})
        if isinstance(market_data, dict)
        else {}
    )
    if not isinstance(section, dict):
        return
    for alias, canonical in MONETARY_KEY_MAP.items():
        if alias == canonical:
            continue
        if alias not in section or canonical not in section:
            continue
        alias_entry = section.get(alias) or {}
        canonical_entry = section.get(canonical) or {}
        if _has_valid_value(
            canonical_entry.get("current_value")
        ) and not _has_valid_value(alias_entry.get("current_value")):
            section.pop(alias, None)
            _remove_missing_item(metadata, "monetary_policy", alias)
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
    with open(market_data_path, "r", encoding="utf-8") as f:
        market_data = json.load(f)
    metadata = market_data.setdefault("metadata", {})
    if isinstance(market_data.get("monetary_policy"), dict):
        market_data["monetary_policy"] = normalize_monetary_section(
            market_data.get("monetary_policy")
        )
    run_paths = build_run_paths_from_reference(
        date=date_override,
        payload=market_data,
        path=market_data_path,
        fallback_to_today=True,
    )
    trend_base_dir = trend_history_base_dir or (
        None if disable_trend_history_write else DEFAULT_BASE_DIR
    )

    # 读取WebSearch结果
    print(f"[INFO] 读取WebSearch结果: {websearch_path}")
    with open(websearch_path, "r", encoding="utf-8") as f:
        websearch_raw = json.load(f)
    is_stage2_results = isinstance(websearch_raw, dict) and isinstance(
        websearch_raw.get("results"), list
    )
    # 若为 Stage2 results 结构，先转换为 schema
    websearch_data = _coerce_stage2_results_to_schema(websearch_raw)
    # 统一结构，容忍 {symbol: {...}} / list / None
    websearch_data["forex"] = _normalize_keyed_list(
        websearch_data.get("forex"), "pair"
    )
    websearch_data["bonds"] = _normalize_keyed_list(
        websearch_data.get("bonds"), "symbol"
    )
    websearch_data["commodities"] = _normalize_keyed_list(
        websearch_data.get("commodities"), "symbol"
    )
    websearch_data["stock_indices"] = _normalize_keyed_list(
        websearch_data.get("stock_indices"), "symbol"
    )
    websearch_data["monetary_policy"] = _normalize_monetary_payload(
        websearch_data.get("monetary_policy")
    )

    gc_warnings: List[Dict[str, Any]] = []
    if is_stage2_results:
        gc_warnings = _collect_gc_non_blocking_warnings(
            market_data, websearch_raw
        )
        for warning in gc_warnings:
            _append_non_blocking_warning(market_data, warning)
    is_manual = (
        "manual" in Path(websearch_path).name.lower() and not is_stage2_results
    )
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
    macro_section = market_data.setdefault("macro_indicators", {})
    for raw_key, payload in websearch_data.get("macro_indicators", {}).items():
        key = MACRO_KEY_MAP.get(raw_key, raw_key)  # 键名规范化
        if key not in macro_section:
            # 缺失即创建占位，避免 industrial_sales 等被跳过
            macro_section[key] = entry_mergers._create_macro_placeholder(
                key, payload, metadata
            )
        metadata_updated_before = len(summary.metadata_updated_items)
        updated = entry_mergers._apply_macro_entry(
            key,
            macro_section[key],
            payload,
            metadata.get("date"),
            is_manual=is_manual,
            override_stale=override_stale,
            force_override=force_override,
            trend_history_base_dir=trend_base_dir,
            summary=summary,
        )
        if updated:
            if len(summary.metadata_updated_items) == metadata_updated_before:
                inject_count += 1
            print(
                f"  [OK] {payload.get('indicator_name', key)}: "
                f"{payload.get('current_value')} "
                f"{payload.get('unit', '')}".strip()
            )
            _remove_missing_item(metadata, "macro_indicators", key)
            _remove_top_missing(market_data, key)
        else:
            _remove_top_missing_on_skip(
                market_data, key, macro_section.get(key)
            )

    # 2. 注入货币政策
    print("\n[STEP 2] 注入货币政策数据...")
    monetary_section = market_data.setdefault("monetary_policy", {})
    for raw_key, payload in websearch_data.get("monetary_policy", {}).items():
        key = MONETARY_KEY_MAP.get(raw_key, raw_key)
        if key not in monetary_section:
            monetary_section[key] = entry_mergers._create_monetary_placeholder(
                key, payload, metadata
            )
        metadata_updated_before = len(summary.metadata_updated_items)
        updated = entry_mergers._apply_monetary_entry(
            key,
            monetary_section[key],
            payload,
            metadata.get("date"),
            is_manual=is_manual,
            override_stale=override_stale,
            force_override=force_override,
            trend_history_base_dir=trend_base_dir,
            summary=summary,
        )
        if updated:
            if len(summary.metadata_updated_items) == metadata_updated_before:
                inject_count += 1
            print(
                f"  [OK] {payload.get('policy_name', key)}: "
                f"{payload.get('current_value')} "
                f"{payload.get('unit', '')}".strip()
            )
            _remove_missing_item(metadata, "monetary_policy", key)
            _remove_top_missing(market_data, key)
        else:
            _remove_top_missing_on_skip(
                market_data, key, monetary_section.get(key)
            )
    _cleanup_monetary_aliases(market_data, metadata)
    market_data["monetary_policy"] = normalize_monetary_section(
        market_data.get("monetary_policy")
    )

    # 3. 注入资金流向（标准化为浮点+统一来源）
    print("\n[STEP 3] 注入资金流向数据...")
    for raw_key, payload in websearch_data.get("fund_flow", {}).items():
        key = FUND_FLOW_KEY_MAP.get(raw_key, raw_key)
        if key not in market_data.get("fund_flow", {}):
            continue
        normalized_payload = _normalize_fund_flow_payload(raw_key, payload)
        if entry_mergers._apply_fund_flow_entry(
            market_data["fund_flow"][key],
            key,
            normalized_payload,
            summary=summary,
        ):
            inject_count += 1
            summary.injected("fund_flow", key)
            print(
                f"  [OK] {key}: "
                f"recent_5d={market_data['fund_flow'][key]['recent_5d']} "
                f"total_120d={market_data['fund_flow'][key]['total_120d']} "
                f"source={market_data['fund_flow'][key]['source']}"
            )
            _remove_missing_item(metadata, "fund_flow", key)
            _remove_top_missing(market_data, key)
        else:
            summary.skipped_no_parseable_value("fund_flow", key)

    # 4. 注入外汇数据
    print("\n[STEP 4] 注入外汇数据...")
    forex_iterable = websearch_data.get("forex") or []

    market_forex = market_data.setdefault("forex", [])
    for fx in forex_iterable:
        pair = fx.get("pair") or fx.get("symbol")
        if not pair:
            continue
        updated = False
        for i, item in enumerate(market_forex):
            if item.get("pair") == pair:
                market_forex[i] = entry_mergers._merge_forex_entry(
                    item,
                    fx,
                    is_manual=is_manual,
                    trend_history_base_dir=trend_base_dir,
                )
                updated = True
                break
        if not updated:
            market_forex.append(
                entry_mergers._build_forex_entry(
                    fx,
                    is_manual=is_manual,
                    trend_history_base_dir=trend_base_dir,
                )
            )
        inject_count += 1
        summary.injected("forex", pair)
        print(
            f"  [OK] {fx.get('name', pair)}: {fx.get('current_rate')} "
            f"(source={fx.get('source')})"
        )
        _remove_missing_item(metadata, "forex", pair)
        _remove_top_missing(market_data, pair)

    # 5. 注入股票指数（含 000016 等补全）
    print("\n[STEP 5] 注入股票指数数据...")
    stock_indices_iterable = websearch_data.get("stock_indices") or []
    stock_indices_section = market_data.setdefault("stock_indices", [])
    for idx_payload in stock_indices_iterable:
        symbol = idx_payload.get("symbol")
        if not symbol:
            print("  [WARN] stock_index 缺少 symbol，已跳过")
            continue
        price = _coerce_float(
            idx_payload.get("current_price")
            or idx_payload.get("close")
            or idx_payload.get("price")
        )
        if price is None:
            print(f"  [WARN] {symbol} 缺少可解析价格，跳过注入")
            summary.skipped_no_parseable_value("stock_indices", symbol)
            continue
        merged = False
        for i, existing in enumerate(stock_indices_section):
            if existing.get("symbol") == symbol:
                stock_indices_section[i] = (
                    entry_mergers._merge_stock_index_entry(
                        existing, idx_payload
                    )
                )
                merged = True
                break
        if not merged:
            stock_indices_section.append(
                entry_mergers._build_stock_index_entry(symbol, idx_payload)
            )
        inject_count += 1
        summary.injected("stock_indices", symbol)
        print(f"  [OK] {idx_payload.get('name', symbol)}: {price}")
        _remove_missing_item(metadata, "stock_indices", symbol)
        _remove_top_missing(market_data, symbol)

    # 6. 注入债券收益率
    print("\n[STEP 6] 注入债券收益率数据...")
    bond_iterable = websearch_data.get("bonds") or []

    for bond_data in bond_iterable:
        symbol = bond_data.get("symbol")
        if not symbol:
            print("  [WARN] bond 缺少 symbol，已跳过")
            continue
        bond_data.setdefault("name", symbol)
        bond_data["current_yield"] = _coerce_float(
            bond_data.get("current_yield")
        )
        if bond_data["current_yield"] is None:
            print(f"  [WARN] {symbol} 缺少 current_yield，跳过注入")
            summary.skipped_no_parseable_value("bonds", symbol)
            continue
        # 在bonds列表中找到对应项并更新
        updated = False
        for i, bond in enumerate(market_data["bonds"]):
            if bond.get("symbol") == symbol:
                market_data["bonds"][i] = entry_mergers._merge_bond_entry(
                    bond,
                    bond_data,
                    is_manual=is_manual,
                    trend_history_base_dir=trend_base_dir,
                )
                inject_count += 1
                summary.injected("bonds", symbol)
                print(
                    f"  [OK] {bond_data['name']}: "
                    f"{bond_data['current_yield']}%"
                )
                _remove_missing_item(metadata, "bonds", symbol)
                _remove_top_missing(market_data, symbol)
                updated = True
                break
        if not updated:
            merged_entry = entry_mergers._merge_bond_entry(
                {},
                bond_data,
                is_manual=is_manual,
                trend_history_base_dir=trend_base_dir,
            )
            market_data.setdefault("bonds", []).append(merged_entry)
            inject_count += 1
            summary.injected("bonds", symbol)
            _remove_missing_item(metadata, "bonds", symbol)
            _remove_top_missing(market_data, symbol)

    # 7. 注入商品价格
    print("\n[STEP 7] 注入商品价格数据...")
    commodity_iterable = websearch_data.get("commodities") or []

    for commodity_data in commodity_iterable:
        symbol = commodity_data.get("symbol")
        if not symbol:
            print("  [WARN] commodity 缺少 symbol，已跳过")
            continue
        commodity_data.setdefault("name", symbol)
        commodity_data["current_price"] = _coerce_float(
            commodity_data.get("current_price")
        )
        if commodity_data["current_price"] is None:
            print(f"  [WARN] {symbol} 缺少 current_price，跳过注入")
            summary.skipped_no_parseable_value("commodities", symbol)
            continue
        # 在commodities列表中找到对应项并更新
        updated = False
        for i, commodity in enumerate(market_data["commodities"]):
            if commodity.get("symbol") == symbol:
                market_data["commodities"][i] = (
                    entry_mergers._merge_commodity_entry(
                        commodity,
                        commodity_data,
                        is_manual=is_manual,
                        trend_history_base_dir=trend_base_dir,
                    )
                )
                updated = True
                break
        if not updated:
            market_data.setdefault("commodities", []).append(
                entry_mergers._merge_commodity_entry(
                    {},
                    commodity_data,
                    is_manual=is_manual,
                    trend_history_base_dir=trend_base_dir,
                )
            )
        inject_count += 1
        summary.injected("commodities", symbol)
        price_val = commodity_data.get("current_price") or 0.0
        ytd_val = commodity_data.get("ytd_change") or 0.0
        print(
            f"  [OK] {commodity_data['name']}: "
            f"{commodity_data.get('unit', '')}{price_val:.2f} "
            f"(YTD {ytd_val:+.2f}%)"
        )
        _remove_missing_item(metadata, "commodities", symbol)
        _remove_top_missing(market_data, symbol)

    # 注入完成后回读 trend_history 补齐缺失变化值（默认开启）
    if backfill_trend and trend_base_dir is not None:
        try:
            backfill_stats = trend_backfill._backfill_trend_changes(
                market_data, base_dir=trend_base_dir
            )
            total_backfilled = sum(backfill_stats.values())
            if total_backfilled:
                print(f"  - trend_history backfill: {backfill_stats}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] trend_history backfill failed: {exc}")

    # 更新元数据
    metadata_section = websearch_data.get("metadata", {})

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
    for item in market_data.get("commodities", []):
        total += 1
        filled += 1 if _is_filled(item.get("current_price")) else 0
    # forex
    for item in market_data.get("forex", []):
        total += 1
        filled += 1 if _is_filled(item.get("current_rate")) else 0
    # bonds
    for item in market_data.get("bonds", []):
        total += 1
        filled += 1 if _is_filled(item.get("current_yield")) else 0
    # stock indices
    for item in market_data.get("stock_indices", []):
        total += 1
        filled += 1 if _is_filled(item.get("current_price")) else 0
    # fund flow
    for item in market_data.get("fund_flow", {}).values():
        total += 1
        filled += (
            1
            if _is_filled(item.get("recent_5d"))
            and _is_filled(item.get("total_120d"))
            else 0
        )
    # macro & monetary
    for section in ("macro_indicators", "monetary_policy"):
        for entry in market_data.get(section, {}).values():
            total += 1
            filled += 1 if _is_filled(entry.get("current_value")) else 0

    metadata["data_completeness"] = round(filled / total, 3) if total else 1.0
    metadata["ai_websearch_enhanced"] = True
    collection_time = websearch_data.get(
        "collection_time"
    ) or metadata_section.get("collection_time")
    if collection_time:
        metadata["websearch_timestamp"] = collection_time

    # 根据已有数据再清理一次顶层 missing_items，避免遗留占位符
    for key in list(market_data.get("missing_items", [])):
        if isinstance(key, dict):
            key_val = key.get("key") or key.get("indicator_key")
        else:
            key_val = key
        if not key_val:
            continue
        _remove_top_missing(market_data, key_val)
    # 同步根据已填充的 stock_indices 清理缺口
    for idx in market_data.get("stock_indices", []):
        _remove_top_missing(market_data, idx.get("symbol"))
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
    validate_market_data(market_data)
    atomic_write_json(market_data, output_path)

    summary_counts = metadata["injection_summary"]["counts"]
    print("\n[SUCCESS] 数据注入完成！")
    print(f"  - 注入数据项: {inject_count}")
    print(f"  - 元数据更新项: {summary_counts.get('metadata_updated', 0)}")
    print(f"  - 已有值跳过项: {summary_counts.get('skipped_existing', 0)}")
    print(
        f"  - 资金流强制估算项: {summary_counts.get('fund_flow_forced_estimated', 0)}"
    )
    print(
        f"  - 数据完整性: {market_data['metadata']['data_completeness']:.1%}"
    )
    print(f"  - 输出文件: {output_path}")
    if quality_blockers:
        print(
            f"  [WARN] 质量阻断项: {len(quality_blockers)}"
            "（需通过 Stage2/Stage2.5 补齐真实值/对比值）"
        )
        for blocker in quality_blockers:
            print(
                f"    - {blocker.get('category')}."
                f"{blocker.get('key')}: {blocker.get('reason')}"
            )

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
                print(
                    "  - trend_history gap snapshot refreshed: "
                    f"{run_paths.trend_history_gap}"
                )
            except Exception as exc:  # noqa: BLE001
                print(
                    "  [WARN] trend_history gap snapshot refresh failed: "
                    f"{exc}"
                )
        except Exception as exc:  # noqa: BLE001
            print(f"  - trend_history final write failed: {exc}")

    # Post-write backfill: use freshly written trend_history details.
    if backfill_trend and trend_base_dir is not None:
        try:
            post_stats = trend_backfill._run_post_write_trend_backfill(
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
            validate_market_data(market_data)
            atomic_write_json(market_data, output_path)
        except ContractValidationError:
            raise
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
    trend_backfill._sync_backfill_issues_to_logs(
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
    for bond in market_data.get("bonds", []) or []:
        if bond.get("is_estimated"):
            name = bond.get("name") or bond.get("symbol") or "unknown"
            estimated_fields.append(f"bonds.{name}")

    # Check macro_indicators
    for key, entry in (market_data.get("macro_indicators", {}) or {}).items():
        if isinstance(entry, dict) and entry.get("is_estimated"):
            name = entry.get("indicator_name") or key
            estimated_fields.append(f"macro_indicators.{name}")

    # Check monetary_policy
    for key, entry in (market_data.get("monetary_policy", {}) or {}).items():
        if isinstance(entry, dict) and entry.get("is_estimated"):
            name = entry.get("policy_name") or key
            estimated_fields.append(f"monetary_policy.{name}")

    # Check commodities
    for comm in market_data.get("commodities", []) or []:
        if comm.get("is_estimated"):
            name = comm.get("name") or comm.get("symbol") or "unknown"
            estimated_fields.append(f"commodities.{name}")

    # Check forex
    for fx in market_data.get("forex", []) or []:
        if fx.get("is_estimated"):
            name = fx.get("name") or fx.get("pair") or "unknown"
            estimated_fields.append(f"forex.{name}")

    # Print validation result
    print("\n[VALIDATION] 估计值校验:")
    if estimated_fields:
        print(f"  [WARN] 仍有 {len(estimated_fields)} 个估计值字段:")
        for field in estimated_fields:  # noqa: F402
            print(f"    - {field}")
    else:
        print("  [OK] 所有字段已去除估计值标记")
