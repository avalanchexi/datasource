"""Compatibility shim for the Stage3 Pring analyzer entrypoint."""

from __future__ import annotations

from datasource.engines.stage3.cli import main, parse_args  # noqa: F401
from datasource.engines.stage3.core import (  # noqa: F401
    MIN_COMPLETENESS_DEFAULT,
    _append_non_blocking_warning,
    _collect_compare_gaps,
    _collect_estimated_items,
    _collect_stale_items,
    _effective_policy_rules,
    _find_entry_by_item,
    _find_estimated_entry_by_key,
    _flatten_missing_items,
    _gap_item_key,
    _is_allowlisted_gap_item,
    _issue_label,
    _item_label,
    _iter_estimated_entries,
    _load_gap_monitor,
    _message_items,
    _policy_item_has_current_entry,
    _policy_item_matches_live_blocker,
    _quality_blocker_keys,
    _require_data_completeness,
    _resolve_gap_monitor_path,
    _run_analysis,
)

__all__ = [
    "MIN_COMPLETENESS_DEFAULT",
    "_append_non_blocking_warning",
    "_collect_compare_gaps",
    "_collect_estimated_items",
    "_collect_stale_items",
    "_effective_policy_rules",
    "_find_entry_by_item",
    "_find_estimated_entry_by_key",
    "_flatten_missing_items",
    "_gap_item_key",
    "_is_allowlisted_gap_item",
    "_issue_label",
    "_item_label",
    "_iter_estimated_entries",
    "_load_gap_monitor",
    "_message_items",
    "_policy_item_has_current_entry",
    "_policy_item_matches_live_blocker",
    "_quality_blocker_keys",
    "_require_data_completeness",
    "_resolve_gap_monitor_path",
    "_run_analysis",
    "main",
    "parse_args",
]


if __name__ == "__main__":
    main()
