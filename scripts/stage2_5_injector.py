#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI WebSearch 数据注入脚本。

将 websearch_results 注入到 market_data 文件中，作为 Stage2.5 主入口。
"""

# C4 compatibility re-exports.
import argparse  # noqa: F401 (C4 re-export)
import json  # noqa: F401 (C4 re-export)
from functools import partial  # noqa: F401 (C4 re-export)
import re  # noqa: F401 (C4 re-export)
import sys  # noqa: F401 (C4 re-export)
from dataclasses import dataclass, field  # noqa: F401 (C4 re-export)
from datetime import datetime, timedelta  # noqa: F401 (C4 re-export)
from pathlib import Path  # noqa: F401 (C4 re-export)
from typing import (  # noqa: F401 (C4 re-export)
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

# C4 compatibility re-exports.
from datasource.models.market_data_contract import FundFlowData  # noqa: F401
from datasource.utils.trend_history_store import (  # noqa: F401
    write_from_market_data,
    write_trend_history_gap_snapshot,
    DEFAULT_BASE_DIR,
    SERIES_WINDOWS,
)
from datasource.utils.fund_flow_series import (  # noqa: F401
    apply_override,
    compute_rollup,
    load_daily_series,
)
from datasource.utils.quality_metrics import (  # noqa: F401
    build_quality_metrics,
)
from datasource.utils.key_aliases import (  # noqa: F401
    MONETARY_KEY_ALIASES,
    normalize_monetary_section,
)
from datasource.utils.policy_rules import (  # noqa: F401
    get_non_blocking_warning_rules,
)
from datasource.utils.run_lock import (  # noqa: F401
    DailyRunLock,
    run_dir_from_artifact,
)
from datasource.utils.run_paths import (  # noqa: F401
    build_run_paths_from_reference,
)
from datasource.utils.text_markers import contains_ytd_marker  # noqa: F401
from datasource.utils.forex_evidence import (  # noqa: F401
    FOREX_DAILY_CHANGE_EVIDENCE_KEYS,
    FOREX_120D_CHANGE_EVIDENCE_KEYS,
    STAGE25_FOREX_DAILY_CHANGE_SOURCE_MARKERS
    as FOREX_DAILY_CHANGE_SOURCE_MARKERS,
    STAGE25_FOREX_120D_CHANGE_SOURCE_MARKERS
    as FOREX_120D_CHANGE_SOURCE_MARKERS,
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
from datasource.utils.note_utils import (  # noqa: F401
    append_note_once as _append_note_once,
    append_note_to_entry as _append_note,
)
# C4 compatibility re-exports.
from datasource.engines.stage2_5.common import (  # noqa: F401
    BARE_DOMAIN_START_RE,
    DEFAULT_SOURCE_LABEL,
    EXPLICIT_URL_FIELDS,
    HTTP_LIKE_START_RE,
    OFFICIAL_MANUAL_TEXT_FIELDS,
    SOURCE_ANOMALY_LABEL,
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
    _format_source_label,
    _has_valid_value,
    _is_estimated_allowlisted_entry,
    _is_https_url_evidence,
    _is_placeholder_numeric,
    _is_url_evidence_terminator,
    _iter_http_like_evidence,
    _iter_url_like_evidence,
    _issue_signature,
    _merge_same_value_report_fields,
    _merge_quality_issues,
    _normalize_parseable_http_url,
    _pct_change,
    _policy_rules,
    _same_numeric_value,
    _update_metadata_only,
)
from datasource.engines.stage2_5.manual_official import (  # noqa: F401
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
from datasource.engines.stage2_5.fund_flow import (  # noqa: F401
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
from datasource.engines.stage2_5.schema_coercion import (  # noqa: F401
    _coerce_stage2_results_to_schema,
    _copy_payload_metadata_fields,
    _copy_source_url,
    _normalize_keyed_list,
    _normalize_monetary_payload,
)
from datasource.engines.stage2_5.gap_sync import (  # noqa: F401
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
# C5 compatibility re-exports.
from datasource.engines.stage2_5.trend_backfill import (  # noqa: F401
    _TREND_CONF_RANK,
    _backfill_cdb_proxy_changes_from_cn10y,
    _backfill_trend_changes,
    _calc_change_from_event_history,
    _calc_change_from_trend_history,
    _calc_daily_change_from_trend_history,
    _calc_prev_from_event_history,
    _copy_valid_forex_120d_change_evidence,
    _copy_valid_forex_daily_change_evidence,
    _derive_trend_confidence,
    _has_forex_120d_change_computed_marker,
    _has_forex_120d_change_evidence,
    _has_forex_daily_change_computed_marker,
    _has_forex_daily_change_evidence,
    _infer_asset_trend,
    _infer_trend,
    _is_forex_daily_change_absence_text,
    _is_valid_forex_change_base_price,
    _is_valid_forex_daily_change_base_date,
    _is_valid_forex_daily_change_source_url,
    _is_zero_change_value,
    _is_zero_derived_forex_trend,
    _load_event_history,
    _load_series_records,
    _merge_trend_confidence,
    _parse_date,
    _record_backfill_issue,
    _remove_note_markers,
    _run_post_write_trend_backfill,
    _should_backfill_forex_120d_change,
    _should_backfill_forex_daily_change,
    _should_backfill_numeric,
    _sync_backfill_issues_to_logs,
    _usable_forex_change_value,
    _usable_forex_raw_trend,
)
from datasource.engines.stage2_5.entry_mergers import (  # noqa: F401
    _apply_fund_flow_entry,
    _apply_macro_entry,
    _apply_monetary_entry,
    _build_forex_entry,
    _build_fund_flow_note,
    _build_stock_index_entry,
    _contains_ytd_marker,
    _create_macro_placeholder,
    _create_monetary_placeholder,
    _is_suspicious_fund_flow_pair,
    _merge_bond_entry,
    _merge_commodity_entry,
    _merge_forex_entry,
    _merge_stock_index_entry,
)
from datasource.engines.stage2_5.core import (  # noqa: F401
    FUND_FLOW_KEY_MAP,
    MACRO_KEY_MAP,
    MONETARY_KEY_MAP,
    InjectionSummary,
    _append_non_blocking_warning,
    _cleanup_monetary_aliases,
    _collect_gc_non_blocking_warnings,
    _derive_date_compact,
    _enforce_quality_blockers,
    _post_injection_validation,
    _write_unified_quality_artifacts,
    inject_websearch_data,
    inject_websearch_results,
)
from datasource.engines.stage2_5.cli import (  # noqa: F401
    _default_cli_paths,
    main,
    parse_args,
)

if __name__ == "__main__":
    main()
