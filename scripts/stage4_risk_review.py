#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage4 pre-report risk review.

This CLI is read-only for Stage4 inputs. It writes a derived JSON artifact
that highlights reportable-but-risky data items before Markdown generation.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from datasource.utils.run_paths import build_run_paths, build_run_paths_from_reference


Finding = Dict[str, Any]
JsonObject = Dict[str, Any]

CRITICAL_SOURCE_KEYS = {
    "commodities.BCOM",
    "bonds.CN10Y_CDB",
    "forex.USDCNY",
    "macro_indicators.bdi",
    "monetary_policy.mlf",
    "monetary_policy.rrr",
    "monetary_policy.reserve_ratio",
}

BCOM_BAD_TOKENS = (
    "bcomtr",
    "bcomx",
    "total return",
    "etf",
    "exchange traded fund",
    "fund",
    "sub-index",
    "sub index",
    "subindex",
    "ishares",
)

CN10Y_CDB_BASIS_TOKENS = (
    "spread",
    "cdb spread",
    "利差",
    "加点",
    "cn10y plus",
    "10y plus",
)
CN10Y_CDB_BASIS_PATTERNS = (
    re.compile(r"国债\s*(?:\+|加)\s*约?\s*\d+(?:\.\d+)?\s*bp"),
    re.compile(r"(?:cn10y|10y|国债)\s*(?:\+|加).{0,16}(?:spread|利差|加点|cdb|国开)"),
    re.compile(r"(?:cn10y|10y|国债).{0,16}(?:plus|加点|利差)"),
    re.compile(r"(?:spread|利差|加点).{0,16}(?:国开|cdb|cn10y|10y|国债)"),
)

WINDOW_EVIDENCE_OK = {"direct_window", "direct_daily_series", "direct_balance_delta"}
ESTIMATED_FLOW_BASIS = {"news_net_flow", "estimated_net_flow"}

CURRENT_VALUE_FIELDS = (
    "current_value",
    "current_price",
    "current_rate",
    "current_yield",
    "yield",
    "close",
    "price",
)
FUND_FLOW_VALUE_FIELDS = ("recent_5d", "total_120d", "current_value")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage4 前只读风险复核",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--date", default=None, help="运行日期，支持 YYYY-MM-DD 或 YYYYMMDD")
    parser.add_argument("--market-data", default=None, help="market_data_complete.json 路径")
    parser.add_argument("--gap-monitor", default=None, help="gap_monitor.json 路径")
    parser.add_argument("--quality-metrics", default=None, help="quality_metrics.json 路径")
    parser.add_argument("--output", default=None, help="stage4_risk_review.json 输出路径")
    parser.add_argument(
        "--allow-fund-flow-downgrade",
        action="store_true",
        help="记录 Stage4 fund_flow downgrade 路径已启用",
    )
    return parser.parse_args()


def _load_json(path: Path, *, required: bool) -> Optional[JsonObject]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"required market data input not found: {path}")
        return None
    with path.open("r", encoding="utf-8") as handle:
        try:
            payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"failed to load JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _item_text(item: JsonObject) -> str:
    fields = (
        "key",
        "symbol",
        "pair",
        "name",
        "source",
        "note",
        "manual_reason",
        "source_url",
        "url",
        "estimation_method",
        "metric_basis",
        "window_evidence",
        "data_source",
        "provider",
    )
    return " ".join(str(item.get(field)) for field in fields if item.get(field) not in (None, "")).lower()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _has_numeric_current(item: JsonObject, *, category: str) -> bool:
    fields = FUND_FLOW_VALUE_FIELDS if category == "fund_flow" else CURRENT_VALUE_FIELDS
    return any(_is_number(item.get(field)) for field in fields)


def _is_valid_source_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or text.lower() in {"n/a", "na", "none", "null"}:
        return False
    if "," in text or ";" in text or text.count("://") != 1:
        return False
    if any(char.isspace() for char in text):
        return False
    parsed = urlparse(text)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and parsed.geturl() == text


def _normalized_source_url(item: JsonObject) -> Optional[str]:
    for field in ("source_url", "url"):
        value = item.get(field)
        if _is_valid_source_url(value):
            return str(value).strip()
    return None


def _diagnostic_source_url(item: JsonObject) -> Any:
    normalized = _normalized_source_url(item)
    if normalized:
        return normalized
    for field in ("source_url", "url"):
        value = item.get(field)
        if value not in (None, ""):
            return value
    return None


def _entry_key(category: str, name: str, item: JsonObject) -> str:
    fields_by_category = {
        "commodities": ("symbol", "key", "name"),
        "bonds": ("symbol", "key", "name"),
        "forex": ("pair", "symbol", "key", "name"),
        "stock_indices": ("symbol", "ts_code", "code", "key", "name"),
    }
    for field in fields_by_category.get(category, ("key", "symbol", "pair", "name")):
        value = item.get(field)
        if value not in (None, ""):
            return str(value)
    return str(name)


def _iter_items(payload: JsonObject) -> Iterable[Tuple[str, str, JsonObject]]:
    for category, values in payload.items():
        if category == "metadata":
            continue
        if isinstance(values, dict):
            for name, item in values.items():
                if isinstance(item, dict):
                    key = _entry_key(str(category), str(name), item)
                    yield str(category), f"{category}.{key}", item
        elif isinstance(values, list):
            for index, item in enumerate(values):
                if isinstance(item, dict):
                    key = _entry_key(str(category), str(index), item)
                    yield str(category), f"{category}.{key}", item


def _find_item(payload: JsonObject, category: str, target_key: str) -> Optional[JsonObject]:
    target_lower = target_key.lower()
    for found_category, full_key, item in _iter_items(payload):
        if found_category != category:
            continue
        key_tail = full_key.split(".", 1)[1].lower()
        aliases = {
            str(item.get(field) or "").strip().lower()
            for field in ("key", "symbol", "pair", "name", "ts_code", "code")
        }
        aliases.discard("")
        if key_tail == target_lower or target_lower in aliases:
            return item
    return None


def _finding(severity: str, key: str, code: str, message: str, item: JsonObject) -> Finding:
    result: Finding = {
        "severity": severity,
        "key": key,
        "code": code,
        "message": message,
    }
    diagnostic_url = _diagnostic_source_url(item)
    if diagnostic_url not in (None, ""):
        result["source_url"] = diagnostic_url
    for field in (
        "is_estimated",
        "metric_basis",
        "window_evidence",
        "source_tier",
        "estimation_method",
    ):
        if item.get(field) not in (None, ""):
            result[field] = item.get(field)
    return result


def review_bcom(payload: JsonObject) -> List[Finding]:
    item = _find_item(payload, "commodities", "BCOM")
    if not isinstance(item, dict):
        return []
    text = _item_text(item)
    for token in BCOM_BAD_TOKENS:
        if token in text:
            return [
                _finding(
                    "blocker",
                    "commodities.BCOM",
                    "bcom_scope_mismatch",
                    f"BCOM evidence appears to reference incompatible scope: {token}",
                    item,
                )
            ]
    return [
        _finding(
            "review_required",
            "commodities.BCOM",
            "bcom_plain_index_review",
            "Confirm source represents plain Bloomberg Commodity Index, not TR, ETF, fund, or sub-index scope",
            item,
        )
    ]


def review_cn10y_cdb(payload: JsonObject) -> List[Finding]:
    item = _find_item(payload, "bonds", "CN10Y_CDB")
    if not isinstance(item, dict) or item.get("is_estimated") is not True:
        return []
    text = _item_text(item)
    has_basis = any(token in text for token in CN10Y_CDB_BASIS_TOKENS) or any(
        pattern.search(text) for pattern in CN10Y_CDB_BASIS_PATTERNS
    )
    if has_basis:
        return [
            _finding(
                "info",
                "bonds.CN10Y_CDB",
                "cn10y_cdb_estimate_disclosed",
                "CN10Y_CDB estimate includes spread/proxy basis disclosure",
                item,
            )
        ]
    return [
        _finding(
            "review_required",
            "bonds.CN10Y_CDB",
            "cn10y_cdb_estimate_missing_basis",
            "CN10Y_CDB is estimated but lacks spread/proxy basis disclosure",
            item,
        )
    ]


def review_fund_flow(
    payload: JsonObject,
    *,
    allow_fund_flow_downgrade: bool,
) -> List[Finding]:
    findings: List[Finding] = []
    fund_flow = payload.get("fund_flow") or {}
    if not isinstance(fund_flow, dict):
        return findings

    for name, item in fund_flow.items():
        if not isinstance(item, dict):
            continue
        basis = str(item.get("metric_basis") or "").strip()
        window_evidence = str(item.get("window_evidence") or "").strip()
        estimated = item.get("is_estimated") is True
        weak_window = window_evidence not in WINDOW_EVIDENCE_OK
        estimated_basis = basis in ESTIMATED_FLOW_BASIS
        if not (estimated or estimated_basis or weak_window):
            continue
        code = (
            "fund_flow_downgrade_review"
            if allow_fund_flow_downgrade
            else "fund_flow_estimate_review"
        )
        findings.append(
            _finding(
                "review_required",
                f"fund_flow.{name}",
                code,
                "fund_flow uses estimated/news/weak-window evidence and needs disclosure review",
                item,
            )
        )
    return findings


def review_source_evidence(payload: JsonObject) -> List[Finding]:
    findings: List[Finding] = []
    for category, key, item in _iter_items(payload):
        if not _has_numeric_current(item, category=category):
            continue
        if _normalized_source_url(item):
            continue
        severity = "blocker" if key in CRITICAL_SOURCE_KEYS else "review_required"
        findings.append(
            _finding(
                severity,
                key,
                "missing_source_url",
                "Numeric report-facing value is missing source_url evidence",
                item,
            )
        )
    return findings


def build_review(
    market_payload: JsonObject,
    *,
    gap_monitor: Optional[JsonObject] = None,
    quality_metrics: Optional[JsonObject] = None,
    allow_fund_flow_downgrade: bool = False,
    missing_optional_files: Optional[List[str]] = None,
) -> JsonObject:
    findings: List[Finding] = []
    findings.extend(review_bcom(market_payload))
    findings.extend(review_cn10y_cdb(market_payload))
    findings.extend(
        review_fund_flow(
            market_payload,
            allow_fund_flow_downgrade=allow_fund_flow_downgrade,
        )
    )
    findings.extend(review_source_evidence(market_payload))

    grouped: Dict[str, List[Finding]] = {"blocker": [], "review_required": [], "info": []}
    for finding in findings:
        grouped[finding["severity"]].append(finding)

    metadata = market_payload.get("metadata") if isinstance(market_payload.get("metadata"), dict) else {}
    return {
        "metadata": {
            "date": metadata.get("date") or metadata.get("end_date") or metadata.get("start_date"),
            "allow_fund_flow_downgrade": allow_fund_flow_downgrade,
            "gap_monitor_present": gap_monitor is not None,
            "quality_metrics_present": quality_metrics is not None,
            "missing_optional_files": missing_optional_files or [],
            "finding_count": len(findings),
            "blocker_count": len(grouped["blocker"]),
            "review_required_count": len(grouped["review_required"]),
            "info_count": len(grouped["info"]),
        },
        "findings": grouped,
    }


def resolve_paths(args: argparse.Namespace) -> Tuple[Path, Path, Path, Path]:
    if args.market_data:
        market_path = Path(args.market_data)
        run_paths = build_run_paths_from_reference(path=market_path, fallback_to_today=True)
    elif args.date:
        run_paths = build_run_paths(args.date)
        market_path = run_paths.market_data_complete
    else:
        run_paths = build_run_paths_from_reference(fallback_to_today=True)
        market_path = run_paths.market_data_complete

    gap_path = Path(args.gap_monitor) if args.gap_monitor else run_paths.gap_monitor
    quality_path = Path(args.quality_metrics) if args.quality_metrics else run_paths.quality_metrics
    output_path = Path(args.output) if args.output else run_paths.data_dir / "stage4_risk_review.json"
    return market_path, gap_path, quality_path, output_path


def main() -> None:
    args = parse_args()
    market_path, gap_path, quality_path, output_path = resolve_paths(args)

    market_payload = _load_json(market_path, required=True)
    assert market_payload is not None

    missing_optional_files: List[str] = []
    gap_monitor = _load_json(gap_path, required=False)
    if gap_monitor is None:
        missing_optional_files.append(str(gap_path))
    quality_metrics = _load_json(quality_path, required=False)
    if quality_metrics is None:
        missing_optional_files.append(str(quality_path))

    review = build_review(
        market_payload,
        gap_monitor=gap_monitor,
        quality_metrics=quality_metrics,
        allow_fund_flow_downgrade=args.allow_fund_flow_downgrade,
        missing_optional_files=missing_optional_files,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(review, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"[DONE] Stage4 risk review written: {output_path}")
    print(
        "[INFO] "
        f"blockers={review['metadata']['blocker_count']}, "
        f"review_required={review['metadata']['review_required_count']}, "
        f"info={review['metadata']['info_count']}"
    )


if __name__ == "__main__":
    main()
