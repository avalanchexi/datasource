#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复已验证指标的 is_estimated 残留阻断（默认 bdi）。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from datasource.utils.policy_rules import is_estimated_allowlisted, load_policy_rules
from datasource.utils.run_paths import build_run_paths_from_reference


def _find_entry(payload: Dict[str, Any], key: str) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    key_str = str(key)

    macro = payload.get("macro_indicators", {})
    if isinstance(macro, dict) and isinstance(macro.get(key_str), dict):
        return "macro_indicators", key_str, macro[key_str]

    monetary = payload.get("monetary_policy", {})
    if isinstance(monetary, dict) and isinstance(monetary.get(key_str), dict):
        return "monetary_policy", key_str, monetary[key_str]

    for category, list_name, id_field in [
        ("bonds", "bonds", "symbol"),
        ("forex", "forex", "pair"),
        ("commodities", "commodities", "symbol"),
        ("stock_indices", "stock_indices", "symbol"),
    ]:
        for item in payload.get(list_name, []) or []:
            if not isinstance(item, dict):
                continue
            if str(item.get(id_field)) == key_str:
                return category, str(item.get(id_field)), item
    return None


def _remove_from_top_missing(payload: Dict[str, Any], key: str) -> bool:
    missing = payload.get("missing_items")
    if not isinstance(missing, list):
        return False

    changed = False
    kept: List[Any] = []
    for item in missing:
        item_key = item.get("key") if isinstance(item, dict) else item
        if isinstance(item, dict) and not item_key:
            item_key = item.get("indicator_key")
        if str(item_key) == str(key):
            changed = True
            continue
        kept.append(item)
    payload["missing_items"] = kept
    return changed


def _remove_from_metadata_missing(payload: Dict[str, Any], key: str) -> bool:
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    missing = metadata.get("missing_items") if isinstance(metadata, dict) else None
    if not isinstance(missing, dict):
        return False

    changed = False
    cleaned: Dict[str, List[Any]] = {}
    for category, rows in missing.items():
        if not isinstance(rows, list):
            continue
        kept_rows: List[Any] = []
        for row in rows:
            row_key = row.get("key") if isinstance(row, dict) else row
            if isinstance(row, dict) and not row_key:
                row_key = row.get("indicator_key")
            if str(row_key) == str(key):
                changed = True
                continue
            kept_rows.append(row)
        if kept_rows:
            cleaned[category] = kept_rows
    metadata["missing_items"] = cleaned
    return changed


def _update_gap_monitor(path: Path, key: str) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False

    changed = False
    for field in ("manual_required", "pending_tasks"):
        rows = payload.get(field)
        if not isinstance(rows, list):
            continue
        filtered = [item for item in rows if str(item) != str(key)]
        if len(filtered) != len(rows):
            payload[field] = filtered
            changed = True
    if changed:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def _extract_redlist_keys(rows: List[Any]) -> List[str]:
    keys: List[str] = []
    for row in rows:
        if isinstance(row, dict):
            key = row.get("key") or row.get("indicator_key")
        else:
            key = row
        if key:
            keys.append(str(key))
    return keys


def _filter_redlist_rows(rows: List[Any], key: str) -> Tuple[List[Any], bool]:
    kept: List[Any] = []
    changed = False
    for row in rows:
        if isinstance(row, dict):
            row_key = row.get("key") or row.get("indicator_key")
        else:
            row_key = row
        if str(row_key) == str(key):
            changed = True
            continue
        kept.append(row)
    return kept, changed


def _update_policy(path: Path, key: str) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False

    changed = False

    redlist = payload.get("redlist") if isinstance(payload.get("redlist"), list) else []
    stale_redlist = payload.get("stale_redlist") if isinstance(payload.get("stale_redlist"), list) else []

    filtered_redlist, redlist_changed = _filter_redlist_rows(redlist, key)
    filtered_stale, stale_changed = _filter_redlist_rows(stale_redlist, key)
    if redlist_changed:
        payload["redlist"] = filtered_redlist
        changed = True
    if stale_changed:
        payload["stale_redlist"] = filtered_stale
        changed = True

    has_redlist = bool(_extract_redlist_keys(payload.get("redlist") or []))
    has_stale = bool(payload.get("stale_redlist") or [])
    new_block = has_redlist or has_stale
    if payload.get("block_stage3") != new_block:
        payload["block_stage3"] = new_block
        changed = True

    if changed:
        payload["updated_at"] = datetime.now().isoformat()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="修复已验证 estimated 指标（默认 bdi）")
    parser.add_argument("--date", default=None, help="日期 YYYY-MM-DD，用于推导 gap/policy 文件名")
    parser.add_argument("--market-data", required=True, help="market_data_complete.json 路径")
    parser.add_argument("--key", default="bdi", help="待修复指标键（默认 bdi）")
    parser.add_argument("--gap-monitor", default=None, help="可选：显式 gap_monitor 路径")
    parser.add_argument("--policy-path", default=None, help="可选：显式 policy_evaluation 路径")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    market_path = Path(args.market_data)
    if not market_path.exists():
        raise FileNotFoundError(f"未找到 market_data 文件: {market_path}")

    payload = json.loads(market_path.read_text(encoding="utf-8"))
    key = str(args.key)

    located = _find_entry(payload, key)
    if not located:
        raise RuntimeError(f"未在 market_data 中找到 key={key} 对应条目")

    category, real_key, entry = located
    rules = load_policy_rules()
    allowed, reasons = is_estimated_allowlisted(category, real_key, entry, rules=rules)
    if not allowed:
        reason_text = "|".join(reasons) if reasons else "unknown"
        raise RuntimeError(f"key={key} 当前不满足白名单放行条件: {reason_text}")

    changed_fields = []
    if isinstance(entry, dict) and entry.get("is_estimated") is not False:
        entry["is_estimated"] = False
        changed_fields.append("entry.is_estimated")

    if _remove_from_top_missing(payload, key):
        changed_fields.append("missing_items")
    if _remove_from_metadata_missing(payload, key):
        changed_fields.append("metadata.missing_items")

    if changed_fields:
        market_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    run_paths = build_run_paths_from_reference(
        date=args.date,
        payload=payload,
        fallback_to_today=True,
    )
    gap_path = Path(args.gap_monitor) if args.gap_monitor else run_paths.gap_monitor
    policy_path = Path(args.policy_path) if args.policy_path else run_paths.policy_evaluation

    gap_changed = _update_gap_monitor(gap_path, key)
    policy_changed = _update_policy(policy_path, key)

    print(f"[DONE] 修复完成 key={key}")
    print(f"  - market_data: {'updated' if changed_fields else 'no_change'}")
    if changed_fields:
        print(f"    fields: {', '.join(changed_fields)}")
    print(f"  - gap_monitor: {'updated' if gap_changed else 'no_change'} ({gap_path})")
    print(f"  - policy_evaluation: {'updated' if policy_changed else 'no_change'} ({policy_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
