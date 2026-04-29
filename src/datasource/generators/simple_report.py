"""简单报告生成器（正式版）

基于 market_data_complete.json 与 pring_result.json 生成 Markdown 报告。
原测试脚本已移至此处，供 Stage4 及 CLI 调用。
"""

from __future__ import annotations

import json
import os
import sys
import time
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Optional

from datasource.utils.coercion import to_float
from datasource.utils.run_paths import build_run_paths
from datasource.utils.trend_history_store import load_series_values

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - 环境缺省时延迟导入
    OpenAI = None  # type: ignore

NA_TEXT = "N/A（待 WebSearch）"
DEFAULT_ASSET_CONCLUSION = "资金流转正，汇率偏稳，债券小幅下行，商品分化。"
MAX_CONCLUSION_CHARS = 50
QUALITY_REASONS = {
    "trend_history_missing",
    "no_previous_value",
    "source_latest_only",
    "manual_incomplete",
    "estimated_not_allowed",
}
QUALITY_REASON_LABELS = {
    "trend_history_missing": "trend_history缺失",
    "no_previous_value": "无前值可比",
    "source_latest_only": "来源仅提供最新值",
    "manual_incomplete": "补数不完整",
    "estimated_not_allowed": "估算值禁用",
}
NON_MACRO_KEYS = {
    "GC=F", "CL=F", "BZ=F", "HG=F", "GSG", "BCOM",
    "DXY", "USDCNH", "USDCNY",
    "US10Y", "CN10Y", "CN10Y_CDB",
    "000016",
}
DAILY_MACRO_KEYS = {"bdi"}
DAILY_POLICY_KEYS = {"dr007"}
EVENTS_DIR = Path("data/trend_history/min/events")


def _to_float(value: Any) -> Optional[float]:
    return to_float(value)


def _normalize_trend(trend: Any) -> Optional[str]:
    if trend is None:
        return None
    text = str(trend).strip()
    if not text or text in {NA_TEXT, "未知", "待 WebSearch", "待MCP获取", "待MCP", "N/A"}:
        return None
    return text


def _infer_asset_trend(
    asset_type: str,
    raw_trend: Any = None,
    daily_change: Any = None,
    change_5d: Any = None,
    change_120d: Any = None,
    ytd_change: Any = None,
    bp5: Any = None,
    bp120: Any = None,
) -> Optional[str]:
    trend = _normalize_trend(raw_trend)
    if trend:
        return trend
    if asset_type == "bond":
        bp_val = _to_float(bp5) if bp5 is not None else None
        if bp_val is None:
            bp_val = _to_float(bp120) if bp120 is not None else None
        if bp_val is None:
            return None
        if bp_val > 5:
            return "上行"
        if bp_val < -5:
            return "下行"
        return "平稳"

    for candidate in (ytd_change, change_120d, change_5d, daily_change):
        val = _to_float(candidate)
        if val is None:
            continue
        if val > 10:
            return "强势上涨"
        if val > 3:
            return "温和上涨"
        if val < -10:
            return "强势下跌"
        if val < -3:
            return "温和下跌"
        return "横盘震荡"
    return None


def _infer_flow_trend(flow: dict) -> Optional[str]:
    trend = _normalize_trend(flow.get("trend"))
    if trend:
        return trend
    recent = _to_float(flow.get("recent_5d"))
    total = _to_float(flow.get("total_120d"))
    val = recent if recent is not None else total
    if val is None:
        return None
    if val > 0:
        return "流入"
    if val < 0:
        return "流出"
    return "平稳"


def _fmt_pct(value: Optional[float], digits: int = 1) -> Optional[str]:
    if value is None:
        return None
    return f"{value:+.{digits}f}%"


def _fmt_bp(value: Optional[float], digits: int = 1) -> Optional[str]:
    if value is None:
        return None
    return f"{value:+.{digits}f}bp"


def _is_low_trend_confidence(entry: dict) -> bool:
    level = str(entry.get("trend_history_confidence") or "").strip().lower()
    return level == "low"


def _is_mlf_non_unified_rate(policy: dict) -> bool:
    text = " ".join(
        str(policy.get(k) or "")
        for k in ("policy_name", "note", "source", "manual_reason")
    )
    markers = (
        "多重价位",
        "中标利率",
        "参考值",
        "口径不适用",
        "无统一利率",
        "美式招标",
        "利率区间",
    )
    return any(marker in text for marker in markers)


def _format_monetary_value_for_report(key: str, entry: dict) -> tuple[str, str]:
    current_value = _to_float(entry.get("current_value"))
    is_placeholder = entry.get("is_estimated") or "待MCP" in str(entry.get("source", ""))
    is_non_unified_mlf = key == "mlf" and _is_mlf_non_unified_rate(entry)

    if current_value is None:
        current = NA_TEXT
    elif is_non_unified_mlf:
        current = f"{current_value:.2f}%（参考）"
    else:
        current = f"{current_value:.2f}%" + ("(估)" if is_placeholder else "")

    if is_non_unified_mlf:
        return current, "口径不适用"

    change_value = entry.get("change_from_120d")
    change_suffix = "pp"
    if change_value is None:
        change_value = entry.get("change_120d_bp")
        change_suffix = "bp"

    reason = _extract_reason(entry.get("note"))
    change_num = _to_float(change_value)
    if reason == "no_previous_value" and (change_num is None or abs(change_num) < 1e-9):
        change = NA_TEXT
    elif change_num is None:
        change = NA_TEXT
    else:
        change = f"{change_num:+.1f}{change_suffix}" + ("(估)" if is_placeholder else "")

    return current, change


def _fmt_change_cell(value: Any, *, digits: int, suffix: str, low_confidence: bool = False) -> str:
    num = _to_float(value)
    if num is None:
        return "N/A"
    return f"{num:+.{digits}f}{suffix}"


def _pick_top(items: list, score_fn, limit: int = 3) -> list:
    scored = []
    for item in items:
        score = score_fn(item)
        if score is None:
            continue
        scored.append((abs(score), item))
    scored.sort(key=lambda x: x[0], reverse=True)
    if scored:
        return [item for _, item in scored[:limit]]
    return items[:limit]


def _build_asset_summary(
    commodities: list,
    forex_list: list,
    bonds: list,
    fund_flow: dict,
) -> str:
    parts: list[str] = []
    def _is_tushare(item: dict) -> bool:
        source = str(item.get("source", "")).lower()
        return "tushare" in source

    def _commodity_score(item: dict) -> Optional[float]:
        return _to_float(item.get("ytd_change") or item.get("change_120d") or item.get("daily_change"))

    def _forex_score(item: dict) -> Optional[float]:
        return _to_float(item.get("change_120d") or item.get("daily_change"))

    def _bond_score(item: dict) -> Optional[float]:
        return _to_float(item.get("change_5d_bp") or item.get("change_120d_bp"))

    def _flow_score(item: dict) -> Optional[float]:
        return _to_float(item.get("recent_5d") or item.get("total_120d"))

    comm_descs: list[str] = []
    for comm in _pick_top([c for c in commodities if not _is_tushare(c)], _commodity_score):
        name = comm.get("name") or comm.get("symbol") or "商品"
        trend = _infer_asset_trend(
            "commodity",
            comm.get("trend"),
            daily_change=comm.get("daily_change"),
            change_120d=comm.get("change_120d"),
            ytd_change=comm.get("ytd_change"),
        )
        change_label = None
        ytd = _to_float(comm.get("ytd_change"))
        if ytd is not None:
            change_label = f"年内{_fmt_pct(ytd)}"
        else:
            c120 = _to_float(comm.get("change_120d"))
            if c120 is not None:
                change_label = f"120日{_fmt_pct(c120)}"
            else:
                daily = _to_float(comm.get("daily_change"))
                if daily is not None:
                    change_label = f"日{_fmt_pct(daily)}"
        parts_local = [p for p in (change_label, trend) if p]
        if parts_local:
            comm_descs.append(f"{name}({ '，'.join(parts_local) })")
    if comm_descs:
        parts.append(f"商品:{'；'.join(comm_descs)}")

    fx_descs: list[str] = []
    for fx in _pick_top([f for f in forex_list if not _is_tushare(f)], _forex_score):
        name = fx.get("name") or fx.get("pair") or "外汇"
        trend = _infer_asset_trend(
            "forex",
            fx.get("trend"),
            daily_change=fx.get("daily_change"),
            change_120d=fx.get("change_120d"),
        )
        change_label = None
        c120 = _to_float(fx.get("change_120d"))
        if c120 is not None:
            change_label = f"120日{_fmt_pct(c120)}"
        else:
            daily = _to_float(fx.get("daily_change"))
            if daily is not None:
                change_label = f"日{_fmt_pct(daily)}"
        parts_local = [p for p in (change_label, trend) if p]
        if parts_local:
            fx_descs.append(f"{name}({ '，'.join(parts_local) })")
    if fx_descs:
        parts.append(f"外汇:{'；'.join(fx_descs)}")

    bond_descs: list[str] = []
    for bond in _pick_top([b for b in bonds if not _is_tushare(b)], _bond_score):
        name = bond.get("name") or bond.get("symbol") or "债券"
        bp5 = _to_float(bond.get("change_5d_bp"))
        bp120 = _to_float(bond.get("change_120d_bp"))
        trend = _infer_asset_trend("bond", bond.get("trend"), bp5=bp5, bp120=bp120)
        change_label = None
        if bp5 is not None:
            change_label = f"5日{_fmt_bp(bp5)}"
        elif bp120 is not None:
            change_label = f"120日{_fmt_bp(bp120)}"
        parts_local = [p for p in (change_label, trend) if p]
        if parts_local:
            bond_descs.append(f"{name}({ '，'.join(parts_local) })")
    if bond_descs:
        parts.append(f"债券:{'；'.join(bond_descs)}")

    flow_descs: list[str] = []
    flow_items = list(fund_flow.items())
    flow_items = _pick_top(
        flow_items,
        lambda item: _flow_score(item[1]) if isinstance(item, tuple) else _flow_score(item),
    )
    for key, flow in flow_items:
        if flow.get("source") == "异常零值-需核查":
            continue
        label = {
            "northbound": "北向",
            "southbound": "南向",
            "etf": "ETF",
            "margin": "融资融券",
        }.get(key, str(key))
        recent = _to_float(flow.get("recent_5d"))
        total = _to_float(flow.get("total_120d"))
        trend = _infer_flow_trend(flow)
        parts_local: list[str] = []
        if recent is not None:
            parts_local.append(f"5日{recent:+.1f}亿")
        if total is not None:
            parts_local.append(f"120日{total:+.1f}亿")
        if trend:
            parts_local.append(trend)
        if parts_local:
            flow_descs.append(f"{label}({ '，'.join(parts_local) })")
    if flow_descs:
        parts.append(f"资金流:{'；'.join(flow_descs)}")

    return " | ".join(parts)


def _limit_text_length(text: str, max_len: int = MAX_CONCLUSION_CHARS) -> str:
    cleaned = (text or "").replace("\n", " ").replace("\r", " ").strip()
    if not cleaned:
        return ""
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()
    if cleaned and cleaned[-1] not in "。！？.!?":
        if len(cleaned) >= max_len:
            cleaned = cleaned[:-1] + "。"
        else:
            cleaned += "。"
    return cleaned


def _generate_asset_conclusion(summary: str) -> tuple[str, str, float]:
    if not summary:
        return DEFAULT_ASSET_CONCLUSION, "no_summary", 0.0
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key or OpenAI is None:
        return DEFAULT_ASSET_CONCLUSION, "no_deepseek_key", 0.0
    model = os.getenv("DEEPSEEK_SUMMARY_MODEL") or os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-pro"
    base_url = os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
    timeout = _to_float(os.getenv("DEEPSEEK_SUMMARY_TIMEOUT")) or 8.0

    prompt = (
        "你是资产配置简报助手。根据给定的资产变化摘要，"
        "生成不超过50字的中文结论，仅输出结论，不要列表或标题。"
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": summary},
    ]
    start = time.perf_counter()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        client = client.with_options(timeout=timeout)
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=120,
        )
        text = (completion.choices[0].message.content or "").strip()
        text = _limit_text_length(text)
        if not text:
            return DEFAULT_ASSET_CONCLUSION, "empty_output", (time.perf_counter() - start) * 1000
        return text, "success", (time.perf_counter() - start) * 1000
    except Exception as exc:  # pragma: no cover - 网络异常兜底
        return DEFAULT_ASSET_CONCLUSION, f"deepseek_error:{exc}", (time.perf_counter() - start) * 1000


def _write_report_observability(
    report_date: str,
    summary_input: str,
    summary_output: str,
    latency_ms: float,
    status: str,
) -> None:
    output_path = build_run_paths(report_date).observability
    payload: dict = {}
    if output_path.exists():
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    payload.setdefault("report_summaries", [])
    payload["report_summaries"].append(
        {
            "type": "asset_conclusion",
            "generated_at": datetime.now().isoformat(),
            "input_summary": summary_input,
            "output_text": summary_output,
            "latency_ms": round(latency_ms, 2),
            "status": status,
        }
    )
    payload.setdefault("generated_at", datetime.now().isoformat())
    payload.setdefault("items", payload.get("items", []))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_reason(note: Any) -> Optional[str]:
    if not note:
        return None
    match = re.search(r"reason=([a-z_]+)", str(note))
    if match and match.group(1) in QUALITY_REASONS:
        return match.group(1)
    return None


def _has_trend_history(category: str, symbol: str) -> bool:
    try:
        values = load_series_values(category, symbol)
    except Exception:
        return False
    return len(values) >= 2


def _parse_event_date(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value)[:10]
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m", "%Y%m"):
        try:
            dt = datetime.strptime(text, fmt)
        except Exception:
            continue
        if fmt in ("%Y-%m", "%Y%m"):
            return datetime(dt.year, dt.month, 1)
        return dt
    return None


def _load_latest_event_marker(indicator_key: str) -> Optional[str]:
    path = EVENTS_DIR / f"{indicator_key}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    events = payload.get("events") if isinstance(payload.get("events"), list) else []
    latest_event = None
    latest_dt = None
    for event in events:
        if not isinstance(event, dict):
            continue
        dt = _parse_event_date(event.get("release_date") or event.get("date"))
        if dt is None:
            continue
        if latest_dt is None or dt > latest_dt:
            latest_dt = dt
            latest_event = event
    if not latest_event:
        return None
    return (
        latest_event.get("report_period")
        or latest_event.get("release_date")
        or latest_event.get("date")
    )


def _is_placeholder_entry(entry: dict) -> bool:
    if entry.get("current_value") in (None, "N/A"):
        return True
    if entry.get("is_estimated"):
        return True
    source = str(entry.get("source", ""))
    return "待MCP" in source or "待 WebSearch" in source


def _pick_release_date(
    entry: dict,
    indicator_key: str,
    report_date: str,
    *,
    is_non_daily: bool,
) -> Optional[str]:
    if _is_placeholder_entry(entry):
        return None
    candidate = entry.get("as_of_date") or entry.get("report_period")
    if candidate:
        return str(candidate)
    candidate = entry.get("date")
    if candidate:
        cand_text = str(candidate)[:10]
        if is_non_daily and cand_text == str(report_date)[:10]:
            latest = _load_latest_event_marker(indicator_key)
            if latest and str(latest)[:10] != str(report_date)[:10]:
                return str(latest)
            return None
        return str(candidate)
    latest = _load_latest_event_marker(indicator_key)
    if latest and is_non_daily and str(latest)[:10] == str(report_date)[:10]:
        return None
    return latest


def _extract_date_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
    if match:
        return match.group(1)
    match = re.search(r"(20\d{2}-\d{2})", text)
    if match:
        return match.group(1)
    # 英文日期：Feb 6, 2026 / February 6, 2026 / 6 Feb 2026
    english_candidates = [
        r"\b([A-Za-z]{3,9}\s+\d{1,2},\s*20\d{2})\b",
        r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2})\b",
        r"\b([A-Za-z]{3,9}\s+\d{1,2}\s+20\d{2})\b",
    ]
    parse_formats = ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y")
    for pattern in english_candidates:
        m = re.search(pattern, text)
        if not m:
            continue
        raw = m.group(1).strip()
        for fmt in parse_formats:
            try:
                dt = datetime.strptime(raw, fmt)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                continue
    return None


def _bond_display_date(bond: dict, report_date: str) -> str:
    explicit_date = bond.get("as_of_date") or bond.get("date") or bond.get("report_period")
    if explicit_date:
        return _extract_date_from_text(str(explicit_date)) or str(explicit_date)[:10]

    note_date = _extract_date_from_text(str(bond.get("note") or ""))
    if note_date:
        return note_date
    return "N/A"


def _collect_quality_issues(market_data: dict) -> list[dict]:
    issues: list[dict] = []

    def _issue(category: str, key: str, field: str, reason: str, detail: Optional[str] = None) -> None:
        if reason not in QUALITY_REASONS:
            reason = "manual_incomplete"
        issues.append(
            {
                "category": category,
                "key": key,
                "field": field,
                "reason": reason,
                "detail": detail or "",
            }
        )

    def _as_list(section: Any) -> list:
        if isinstance(section, dict):
            return list(section.values())
        return section or []

    # Bonds: change_120d_bp 缺失
    for bond in _as_list(market_data.get("bonds", [])):
        symbol = bond.get("symbol") or bond.get("name") or "bond"
        current = bond.get("current_yield")
        if current in (None, 0.0):
            _issue("bonds", symbol, "current_yield", "manual_incomplete")
            continue
        if bond.get("is_estimated"):
            _issue("bonds", str(symbol), "current_yield", "estimated_not_allowed")
        change_120d = bond.get("change_120d_bp")
        if change_120d is None:
            source = str(bond.get("source", "")).lower()
            if not _has_trend_history("bonds", str(symbol)):
                reason = "trend_history_missing"
            elif "tushare" in source or "us_tycr" in source:
                reason = "source_latest_only"
            else:
                reason = "manual_incomplete"
            _issue("bonds", str(symbol), "change_120d_bp", reason)

    # Macro indicators: previous_value / change_rate
    for key, indicator in (market_data.get("macro_indicators", {}) or {}).items():
        if key in NON_MACRO_KEYS:
            continue
        curr = indicator.get("current_value")
        if curr in (None, "N/A"):
            _issue("macro_indicators", key, "current_value", "manual_incomplete")
            continue
        if indicator.get("is_estimated"):
            _issue("macro_indicators", key, "current_value", "estimated_not_allowed")
        reason = _extract_reason(indicator.get("note"))
        if indicator.get("previous_value") is None and indicator.get("change_rate") is None:
            _issue("macro_indicators", key, "previous_value", reason or "no_previous_value")

    # Monetary policy: change_from_120d
    for key, policy in (market_data.get("monetary_policy", {}) or {}).items():
        curr = policy.get("current_value")
        if curr in (None, "N/A"):
            _issue("monetary_policy", key, "current_value", "manual_incomplete")
            continue
        if policy.get("is_estimated"):
            _issue("monetary_policy", key, "current_value", "estimated_not_allowed")
        reason = _extract_reason(policy.get("note"))
        change = policy.get("change_from_120d")
        if change is None:
            _issue("monetary_policy", key, "change_from_120d", reason or "no_previous_value")

    return issues


def _write_quality_gate_logs(report_date: str, issues: list[dict]) -> None:
    run_paths = build_run_paths(report_date)
    gap_path = run_paths.gap_monitor
    gap_payload: dict = {}
    if gap_path.exists():
        try:
            gap_payload = json.loads(gap_path.read_text(encoding="utf-8"))
        except Exception:
            gap_payload = {}
    gap_payload.setdefault("generated_at", datetime.now().isoformat())
    gap_payload["data_quality_issues"] = []
    if issues:
        existing = {(item.get("category"), item.get("key"), item.get("field"), item.get("reason"))
                    for item in gap_payload.get("data_quality_issues", []) if isinstance(item, dict)}
        for issue in issues:
            sig = (issue.get("category"), issue.get("key"), issue.get("field"), issue.get("reason"))
            if sig not in existing:
                gap_payload["data_quality_issues"].append(issue)
    gap_path.parent.mkdir(parents=True, exist_ok=True)
    gap_path.write_text(json.dumps(gap_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    obs_path = run_paths.observability
    obs_payload: dict = {}
    if obs_path.exists():
        try:
            obs_payload = json.loads(obs_path.read_text(encoding="utf-8"))
        except Exception:
            obs_payload = {}
    obs_payload.setdefault("generated_at", datetime.now().isoformat())
    obs_payload["data_quality_issues"] = []
    if issues:
        existing_obs = {(item.get("category"), item.get("key"), item.get("field"), item.get("reason"))
                        for item in obs_payload.get("data_quality_issues", []) if isinstance(item, dict)}
        for issue in issues:
            sig = (issue.get("category"), issue.get("key"), issue.get("field"), issue.get("reason"))
            if sig not in existing_obs:
                obs_payload["data_quality_issues"].append(issue)
    obs_path.parent.mkdir(parents=True, exist_ok=True)
    obs_path.write_text(json.dumps(obs_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_report(market_data_path: Path, pring_result_path: Path, output_path: Path) -> None:
    """生成背景扫描120日报告"""

    with open(market_data_path, 'r', encoding='utf-8') as f:
        market_data = json.load(f)

    with open(pring_result_path, 'r', encoding='utf-8') as f:
        pring_result = json.load(f)

    report_date = market_data['metadata']['date']
    completeness = market_data['metadata']['data_completeness']

    def _as_list(section: Any) -> list:
        """兼容 dict/list 结构，避免 Stage2.5 注入后的结构差异导致 N/A。"""
        if isinstance(section, dict):
            return list(section.values())
        return section or []

    stock_indices = _as_list(market_data.get('stock_indices', []))
    commodities = _as_list(market_data.get('commodities', []))
    bonds = _as_list(market_data.get('bonds', []))
    forex_list = _as_list(market_data.get('forex', []))

    def _collect_estimated_items() -> list[str]:
        items: list[str] = []
        for bond in bonds:
            if bond.get('is_estimated'):
                name = bond.get('name') or bond.get('symbol') or '债券'
                items.append(f"债券:{name}")
        for indicator in market_data.get('macro_indicators', {}).values():
            if indicator.get('is_estimated'):
                name = indicator.get('indicator_name') or '宏观指标'
                items.append(f"宏观:{name}")
        for policy in market_data.get('monetary_policy', {}).values():
            if policy.get('is_estimated'):
                name = policy.get('policy_name') or '货币政策'
                items.append(f"货币政策:{name}")
        for key, flow in market_data.get('fund_flow', {}).items():
            if isinstance(flow, dict) and flow.get('is_estimated'):
                name = {
                    "northbound": "北向资金",
                    "southbound": "南向资金",
                    "etf": "ETF资金流",
                    "margin": "融资融券",
                }.get(key, key)
                items.append(f"资金流:{name}")
        return items

    estimated_items = _collect_estimated_items()

    asset_summary = _build_asset_summary(commodities, forex_list, bonds, market_data.get("fund_flow", {}))
    asset_conclusion, asset_status, asset_latency = _generate_asset_conclusion(asset_summary)
    try:
        _write_report_observability(report_date, asset_summary, asset_conclusion, asset_latency, asset_status)
    except Exception:
        pass

    quality_issues = _collect_quality_issues(market_data)
    try:
        _write_quality_gate_logs(report_date, quality_issues)
    except Exception:
        pass

    quality_gate_section = ""
    if quality_issues:
        lines = []
        for issue in quality_issues:
            reason = QUALITY_REASON_LABELS.get(issue.get("reason"), issue.get("reason"))
            key = issue.get("key")
            field = issue.get("field")
            category = issue.get("category")
            lines.append(f"- 🔴 {category}.{key} {field} 缺失（{reason}）")
        joined = "\n".join(lines[:12])
        quality_gate_section = f"""
## 0、数据质量闸（需补数）

{joined}
"""

    report = f"""# A股背景扫描120日报告

**报告日期**: {report_date}
**数据完整性**: {completeness:.1%}
**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 一、核心结论

**Pring六阶段判定**: {pring_result['final_stage']}
**置信度**: {pring_result['confidence']:.1%}
**投资建议**: {pring_result['recommendation']}
**资产层面结论**: {asset_conclusion}

---
{quality_gate_section}

## 二、股票市场

### 主要指数表现

| 指数 | 最新点位 | 近5日涨跌 | 近120日涨跌 | MA50趋势 | MA200趋势 | 趋势评级 |
|------|----------|-----------|-------------|----------|-----------|----------|
"""
    for idx in stock_indices:
        above_ma50 = "向上" if idx['above_ma50'] else "向下"
        above_ma200 = "向上" if idx['above_ma200'] else "向下"
        change_5d = _fmt_change_cell(idx.get("change_5d"), digits=2, suffix="%")
        change_120d = _fmt_change_cell(idx.get("change_120d"), digits=1, suffix="%")
        report += f"| {idx['name']} | {idx['current_price']:.2f} | {change_5d} | {change_120d} | {above_ma50} | {above_ma200} | {idx['trend_label']} |\n"

    use_commodity_120d_window = any(
        comm.get("change_120d") is not None
        for comm in commodities
    )
    commodity_change_header = "近120日变化" if use_commodity_120d_window else "年内涨跌"

    report += f"""

---

## 三、商品与黄金

| 品种 | 最新报价 | 日涨跌 | {commodity_change_header} | 趋势方向 |
|------|----------|--------|----------|----------|
"""
    commodity_name_map = {
        "GC=F": "COMEX黄金",
        "CL=F": "WTI原油",
        "BZ=F": "Brent原油",
        "HG=F": "COMEX铜",
        "BCOM": "彭博商品指数",
        "GSG": "标普GSCI商品ETF",
    }
    def _commodity_name(comm: dict) -> str:
        name = comm.get("name")
        symbol = comm.get("symbol")
        if not name or name == symbol:
            return commodity_name_map.get(symbol, symbol or "未知")
        return name
    for comm in commodities:
        current_price = comm.get('current_price')
        is_placeholder = current_price in (None, 0.0)
        low_confidence = _is_low_trend_confidence(comm)

        if is_placeholder:
            latest_price = NA_TEXT
        else:
            unit = str(comm.get('unit', '')).strip()
            if unit:
                latest_price = f"{current_price:.2f} {unit}"
            else:
                latest_price = f"{current_price:.2f}"

        daily_change = _fmt_change_cell(
            comm.get("daily_change"),
            digits=2,
            suffix="%",
            low_confidence=low_confidence,
        )
        if use_commodity_120d_window:
            commodity_window_change = comm.get("change_120d")
        else:
            commodity_window_change = comm.get("ytd_change")
        ytd_change = _fmt_change_cell(
            commodity_window_change,
            digits=2,
            suffix="%",
            low_confidence=low_confidence,
        )
        trend = comm.get('trend') or ("待 WebSearch" if is_placeholder else "未知")

        report += f"| {_commodity_name(comm)} | {latest_price} | {daily_change} | {ytd_change} | {trend} |\n"

    report += """

---

## 四、债券市场

| 债券品种 | 当前收益率 | 近5日变化 | 近120日变化 | 趋势方向 | 日期 | 来源 |
|----------|-----------|----------|-------------|----------|------|------|
"""
    for bond in bonds:
        current_yield = bond.get('current_yield')
        is_placeholder = current_yield in (None, 0.0)
        low_confidence = _is_low_trend_confidence(bond)

        if is_placeholder:
            yield_str = NA_TEXT
        else:
            suffix = "(估)" if bond.get('is_estimated') else ""
            yield_str = f"{current_yield:.2f}%{suffix}"

        bp5 = bond.get('change_5d_bp')
        bp120 = bond.get('change_120d_bp')
        bp5_str = _fmt_change_cell(bp5, digits=1, suffix="bp", low_confidence=low_confidence)
        bp120_str = _fmt_change_cell(bp120, digits=1, suffix="bp", low_confidence=low_confidence)
        trend = bond.get('trend') or ("待 WebSearch" if is_placeholder else "未知")

        date_str = _bond_display_date(bond, report_date)
        if is_placeholder:
            date_str = NA_TEXT
        source_str = bond.get('source') or "-"

        report += f"| {bond['name']} | {yield_str} | {bp5_str} | {bp120_str} | {trend} | {date_str} | {source_str} |\n"

    report += """

---

## 五、外汇市场

| 货币对 | 当前汇率 | 日涨跌 | 近120日变化 | 趋势方向 |
|--------|---------|--------|-------------|----------|
"""
    for forex in forex_list:
        current_rate = _to_float(forex.get("current_rate"))
        current_rate_text = f"{current_rate:.4f}" if current_rate is not None else NA_TEXT
        low_confidence = _is_low_trend_confidence(forex)
        daily_change = _fmt_change_cell(
            forex.get("daily_change"),
            digits=2,
            suffix="%",
            low_confidence=low_confidence,
        )
        change_120d = _fmt_change_cell(
            forex.get("change_120d"),
            digits=2,
            suffix="%",
            low_confidence=low_confidence,
        )
        trend = forex.get("trend") or ("待 WebSearch" if current_rate is None else "未知")
        report += f"| {forex.get('name') or forex.get('pair') or '外汇'} | {current_rate_text} | {daily_change} | {change_120d} | {trend} |\n"

    report += """

---

## 六、宏观经济指标

| 指标 | 当前值 | 前值 | 变化 | 单位 | 日期 |
|------|--------|------|------|------|------|
"""

    # 仅展示真正的宏观指标；滤除误写入宏观区的商品/外汇/债券/指数键
    for key, indicator in market_data['macro_indicators'].items():
        if key in NON_MACRO_KEYS:
            continue
        curr = indicator.get('current_value', 'N/A')
        prev = indicator.get('previous_value', 'N/A')
        change = indicator.get('change_rate', 'N/A')
        unit = indicator.get('unit', '')
        is_non_daily = key not in DAILY_MACRO_KEYS
        date_val = _pick_release_date(indicator, key, report_date, is_non_daily=is_non_daily)
        date = date_val or NA_TEXT

        name = indicator.get('indicator_name') or key
        if key == "industrial":
            value_type = indicator.get('value_type')
            yoy_ytd = indicator.get('yoy_ytd')
            if value_type == "yoy_ytd":
                name = f"{name}(累计同比)"
            else:
                if yoy_ytd is not None:
                    try:
                        name = f"{name}(当月同比/累计同比{float(yoy_ytd):.1f}%)"
                    except Exception:
                        name = f"{name}(当月同比/累计同比)"
                else:
                    name = f"{name}(当月同比)"

        is_placeholder = indicator.get('is_estimated') or '待MCP' in indicator.get('source', '')
        def _fmt_val(val, suffix="", allow_est=False):
            if val in (None, 'N/A'):
                return NA_TEXT
            if is_placeholder and not allow_est:
                return NA_TEXT
            return f"{val}{suffix}" + ("(估)" if is_placeholder else "")

        curr_str = _fmt_val(curr, unit, allow_est=True)
        prev_str = _fmt_val(prev, unit, allow_est=True)

        if change not in ('N/A', None):
            suffix = unit
            change_str = _fmt_val(f"{float(change):+.1f}", suffix, allow_est=True)
        else:
            change_str = NA_TEXT

        report += f"| {name} | {curr_str} | {prev_str} | {change_str} | {unit} | {date} |\n"

    report += """

---

## 七、货币政策

| 政策工具 | 当前值 | 120日变化 | 单位 | 更新日期 |
|----------|--------|-----------|------|----------|
"""

    for key, policy in market_data['monetary_policy'].items():
        unit = policy.get('unit', '')
        is_non_daily = key not in DAILY_POLICY_KEYS
        is_mlf_non_unified = key == "mlf" and _is_mlf_non_unified_rate(policy)
        date_val = _pick_release_date(policy, key, report_date, is_non_daily=is_non_daily)
        if is_mlf_non_unified and not date_val:
            date_val = policy.get("date") or policy.get("as_of_date") or policy.get("report_period")
        date = date_val or ("口径不适用" if is_mlf_non_unified else NA_TEXT)

        name = policy.get('policy_name') or key
        if key == "mlf":
            name = "中国MLF利率"
        if name and policy.get('rrr_type') and name in ("存款准备金率", "存准率", "Reserve Requirement Ratio"):
            rrr_type = policy.get('rrr_type')
            label = "加权平均" if rrr_type == "weighted" else "法定平均" if rrr_type == "statutory" else rrr_type
            name = f"{name}({label})"

        curr_str, change_str = _format_monetary_value_for_report(key, policy)

        report += f"| {name} | {curr_str} | {change_str} | {unit} | {date} |\n"

    leading_summary = pring_result.get('leading_summary')
    if not leading_summary:
        leading_indicator = pring_result.get('leading_indicator') or {}
        status = leading_indicator.get('status')
        bp_change = leading_indicator.get('bp_change')
        lead_days = leading_indicator.get('lead_days')
        shift = leading_indicator.get('applied_shift', 0)
        direction = leading_indicator.get('direction')

        if status == 'ok':
            dir_text = "宽松" if direction == 'easing' else "收紧"
            shift_text = ""
            if shift:
                arrow = "前" if shift < 0 else "后"
                shift_text = f"，阶段预计向{arrow}{abs(shift)}档"
            bp_text = f"{bp_change:+.0f}bp" if bp_change is not None else "未知bp"
            lead_text = f"{lead_days}天" if lead_days is not None else "数十天"
            leading_summary = f"DR007出现{dir_text}信号（{bp_text}，领先期约{lead_text}{shift_text}）"
            if leading_indicator.get('message'):
                leading_summary += f"，{leading_indicator['message']}"
        elif status == 'flat':
            leading_summary = leading_indicator.get('message', 'DR007变化有限，领先指标保持中性')
        elif status == 'missing':
            leading_summary = "缺少DR007/逆回购原始数据，需补充WebSearch"
        else:
            leading_summary = leading_indicator.get('message', '暂无领先指标结论')

    pending_websearch = pring_result.get('pending_websearch') or []
    fallback_used = pring_result.get('fallback_used', False)

    focus_assets = pring_result.get('focus_assets') or []
    focus_assets_summary = "、".join(focus_assets) if focus_assets else "未提供（请检查Pring结果）"

    layer1 = pring_result.get('layer_1_inventory_cycle', {})
    layer2 = pring_result.get('layer_2_monetary_cycle', {})
    layer3 = pring_result.get('layer_3_pring_final', {})
    analysis1 = layer1.get('analysis', '（暂无详细解析，待Stage2.5补充）')
    analysis2 = layer2.get('analysis', '（暂无详细解析，待Stage2.5补充）')
    analysis3 = layer3.get('analysis', '（暂无详细解析，待Stage2.5补充）')

    report += """

---

## 八、Pring三层框架分析

### Layer 1：库存周期
- **基本面得分**: {score1}/60
- **周期阶段**: {stage1}
- **商品偏向**: {comm_bias}
- **诊断摘要**: {analysis1}

### Layer 2：货币周期
- **货币宽松度**: {score2}/100
- **周期阶段**: {stage2}
- **权益/债券偏向**: {equity_bias} / {bond_bias}
- **诊断摘要**: {analysis2}

### Layer 3：Pring最终判定
- **基础阶段 → 最终阶段**: {base_stage} → {final_stage}
- **置信度**: {confidence:.1%}
- **DR007领先指标**: {leading_summary}
- **阶段关注资产**: {focus_assets_summary}
- **诊断摘要**: {analysis3}
- **数据完整度**: {data_completeness:.1%}（阈值≥{min_completeness:.0%}）{fallback_hint}
- **待补WebSearch**: {pending_ws}

---

## 九、资金流向

| 类别 | 近5日(亿元) | 近120日(亿元) | 趋势 | 来源 | 备注 |
|------|-------------|----------------|------|------|------|
""".format(
        score1=layer1.get('fundamental_score', 0),
        stage1=layer1.get('cycle_stage', '未知'),
        comm_bias=layer1.get('commodity_bias', '未知'),
        analysis1=analysis1,
        score2=layer2.get('monetary_score', 0),
        stage2=layer2.get('cycle_stage', '未知'),
        equity_bias=layer2.get('equity_bias', '未知'),
        bond_bias=layer2.get('bond_bias', '未知'),
        analysis2=analysis2,
        base_stage=layer3.get('base_stage', 'N/A'),
        final_stage=layer3.get('final_stage', 'N/A'),
        confidence=pring_result.get('confidence', 0.0),
        analysis3=analysis3,
        leading_summary=leading_summary,
        focus_assets_summary=focus_assets_summary,
        data_completeness=pring_result.get('data_completeness', completeness),
        min_completeness=pring_result.get('metadata', {}).get('min_completeness', 0.8),
        fallback_hint="；allow_fallback=TRUE" if fallback_used else "",
        pending_ws="、".join(map(str, pending_websearch)) if pending_websearch else "无",
    )

    FLOW_LABELS = {
        "northbound": "北向资金",
        "southbound": "南向资金",
        "etf": "ETF资金流",
        "margin": "融资融券",
    }

    def _flow_label(key: str) -> str:
        return FLOW_LABELS.get(key, key)

    def _format_flow_amount(value: Any) -> str:
        if isinstance(value, (int, float)):
            return f"{value:.2f}"
        return 'N/A'

    for key, flow in market_data['fund_flow'].items():
        report += (
            f"| {_flow_label(key)} | {_format_flow_amount(flow.get('recent_5d'))} | "
            f"{_format_flow_amount(flow.get('total_120d'))} | {flow.get('trend', 'N/A')} | "
            f"{flow.get('source', '-')} | {flow.get('note', '-') or '-'} |\n"
        )

    estimated_note = ""
    if estimated_items:
        estimated_text = "、".join(estimated_items)
        estimated_note = (
            f"- **估计值提醒**: 以下指标仍为估计值（is_estimated=True），请谨慎解读：{estimated_text}\n"
        )

    non_blocking_warnings = market_data.get("metadata", {}).get("non_blocking_warnings", [])
    warning_note = ""
    if isinstance(non_blocking_warnings, list) and non_blocking_warnings:
        warning_lines = []
        for item in non_blocking_warnings:
            if not isinstance(item, dict):
                continue
            msg = str(item.get("message") or "").strip()
            if not msg:
                continue
            warning_lines.append(f"  - {msg}")
        if warning_lines:
            warning_note = "- **非阻断告警**:\n" + "\n".join(warning_lines) + "\n"
    report += f"""

---

## 附录：数据来源

- **API数据源**: TuShare
- **补数链路**: Stage2 Tavily/DeepSeek + Stage2.5 manual/WebSearch JSON 注入
- **数据完整性**: {completeness:.1%}
- **分析方法**: {pring_result['metadata'].get('analysis_method', 'Pring三层框架')}
{estimated_note}{warning_note}

---

**免责声明**: 本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。
"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"[SUCCESS] 报告生成完成！")
    print(f"  - 输出文件: {output_path}")
    print(f"  - 报告日期: {report_date}")
    print(f"  - 数据完整性: {completeness:.1%}")
    print(f"  - Pring阶段: {pring_result['final_stage']}")
    print(f"  - 置信度: {pring_result['confidence']:.1%}")
    if estimated_items:
        print(f"[WARN] 报告包含估计值指标: {'、'.join(estimated_items)}")
    if quality_issues:
        print(f"[WARN] 数据质量闸未通过: {len(quality_issues)} 项需补数")


    if isinstance(non_blocking_warnings, list) and non_blocking_warnings:
        print(f"[WARN] 报告包含非阻断告警: {len(non_blocking_warnings)} 项")

def main(argv: list[str] | None = None) -> None:
    argv = argv or sys.argv[1:]
    default_paths = build_run_paths(datetime.now().strftime("%Y-%m-%d"))
    market_data_file = default_paths.market_data_complete
    pring_result_file = default_paths.pring_result
    output_file = default_paths.report_markdown

    if len(argv) > 0:
        market_data_file = Path(argv[0])
    if len(argv) > 1:
        pring_result_file = Path(argv[1])
    if len(argv) > 2:
        output_file = Path(argv[2])

    generate_report(market_data_file, pring_result_file, output_file)


if __name__ == "__main__":
    main()
