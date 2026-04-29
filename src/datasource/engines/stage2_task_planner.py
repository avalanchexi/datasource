#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage2TaskPlanner
-----------------
从 Stage1 产出的 market_data 占位或 missing_items 生成统一的 SearchTaskContract 队列。
输出 JSONL 供 Stage2 Unified Pipeline 消费。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from datasource.config.search_profiles import SEARCH_PROFILES, get_profile_key
from datasource.utils.coercion import is_stage2_task_placeholder
from datasource.utils.run_paths import build_run_paths_from_reference

PLACEHOLDER_SENTINELS = {None, 0, 0.0, 7.13}


class Stage2TaskPlanner:
    """扫描占位并生成 Tavily/DeepSeek 搜索任务"""

    def __init__(
        self,
        stage_phase: str = "all",
        search_backend: str = "tavily",
        task_file: Optional[Path] = None,
        fund_flow_backend: str = "tavily",
    ) -> None:
        self.stage_phase = stage_phase
        self.search_backend = search_backend
        self.task_file = task_file
        backend = str(fund_flow_backend or "tavily").lower()
        if backend != "tavily":
            logger.warning(f"[Stage2TaskPlanner] 不再支持 fund_flow_backend={backend}，已自动改为 tavily")
        self.fund_flow_backend = "tavily"
        self.query_context: Dict[str, object] = {}

    @staticmethod
    def _parse_date_value(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(value, fmt)
            except Exception:
                continue
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _build_query_context(self, payload: Dict[str, Any]) -> Dict[str, object]:
        meta = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        date_val = meta.get("date") or meta.get("end_date") or meta.get("start_date")
        dt = self._parse_date_value(str(date_val)) if date_val else None
        if not dt:
            dt = datetime.now()
        ref_year = dt.year
        ref_month = dt.month
        # 宏观月度数据通常为上月发布
        if ref_month == 1:
            report_year, report_month = ref_year - 1, 12
        else:
            report_year, report_month = ref_year, ref_month - 1
        return {
            "ref_year": ref_year,
            "ref_month": ref_month,
            "ref_month2": f"{ref_month:02d}",
            "ref_ym": f"{ref_year}{ref_month:02d}",
            "report_year": report_year,
            "report_month": report_month,
            "report_month2": f"{report_month:02d}",
            "report_ym": f"{report_year}{report_month:02d}",
            "expected_year": report_year,
            "expected_month": report_month,
            "expected_month2": f"{report_month:02d}",
            "expected_ym": f"{report_year}{report_month:02d}",
            "expected_period_label": f"{report_year}年{report_month}月",
            "expected_period_range_label": f"{report_year}年1-{report_month}月",
        }

    def _context_for_expected_period(self, expected_period: Optional[str]) -> Dict[str, object]:
        context = dict(self.query_context or {})
        if not expected_period:
            return context
        match = re.search(r"(20\d{2})[-/年]?(\d{1,2})", str(expected_period))
        if not match:
            return context
        year = int(match.group(1))
        month = int(match.group(2))
        if not 1 <= month <= 12:
            return context
        context.update(
            {
                "expected_year": year,
                "expected_month": month,
                "expected_month2": f"{month:02d}",
                "expected_ym": f"{year}{month:02d}",
                "expected_period_label": f"{year}年{month}月",
                "expected_period_range_label": f"{year}年1-{month}月",
                "report_year": year,
                "report_month": month,
                "report_month2": f"{month:02d}",
                "report_ym": f"{year}{month:02d}",
            }
        )
        return context

    def _apply_query_templates(self, text: Optional[str], context: Optional[Dict[str, object]] = None) -> Optional[str]:
        active_context = context or self.query_context
        if not text or not active_context:
            return text
        try:
            return text.format(**active_context)
        except Exception:
            return text

    def _render_query_families(
        self,
        families: Optional[List[Dict[str, Any]]],
        context: Dict[str, object],
    ) -> List[Dict[str, Any]]:
        rendered: List[Dict[str, Any]] = []
        for family in families or []:
            queries = [self._apply_query_templates(q, context) for q in (family.get("queries") or [])]
            queries = [q for q in queries if q]
            if not queries:
                continue
            rendered.append({**family, "queries": queries})
        return rendered

    def _render_field_queries(
        self,
        field_queries: Optional[Dict[str, List[str]]],
        context: Dict[str, object],
    ) -> Dict[str, List[str]]:
        rendered: Dict[str, List[str]] = {}
        for field_name, queries in (field_queries or {}).items():
            values = [self._apply_query_templates(q, context) for q in (queries or [])]
            values = [q for q in values if q]
            if values:
                rendered[field_name] = values
        return rendered

    @staticmethod
    def _is_placeholder(value: Any) -> bool:
        return is_stage2_task_placeholder(value)

    def _from_missing_items(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        tasks: List[Dict[str, Any]] = []
        for item in payload.get("missing_items", []):
            if isinstance(item, dict):
                indicator_key = item.get("key") or item.get("indicator_key")
                if not indicator_key:
                    continue
                phase = item.get("stage_phase") or self._infer_phase(indicator_key)
                reason = str(item.get("reason") or "").lower()
                trigger_reason = "stale_data" if "stale_data" in reason else "missing"
                expected_period = item.get("expected_period")
            else:
                indicator_key = item
                phase = self._infer_phase(indicator_key)
                trigger_reason = "missing"
                expected_period = None
            tasks.append(
                self._new_task(
                    indicator_key,
                    phase,
                    trigger_reason=trigger_reason,
                    expected_period=expected_period,
                )
            )
        return tasks

    def _infer_phase(self, indicator_key: str) -> str:
        key = (indicator_key or "").lower()
        if key in {"cpi", "ppi", "pmi", "pmi_new_orders", "gdp", "m1", "m2"}:
            return "essential"
        return "assets"

    def _scan_placeholders(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        tasks: List[Dict[str, Any]] = []
        macro = payload.get("macro_indicators", {})
        for indicator_key, indicator_payload in macro.items():
            if self._is_placeholder(indicator_payload.get("current_value")):
                tasks.append(self._new_task(indicator_key, "essential", trigger_reason="placeholder"))

        monetary = payload.get("monetary_policy", {})
        for policy_key, policy_payload in monetary.items():
            if self._is_placeholder(policy_payload.get("current_value")):
                tasks.append(self._new_task(policy_key, "essential", trigger_reason="placeholder"))

        fund_flow = payload.get("fund_flow", {})
        for flow_key, flow_payload in fund_flow.items():
            if self._is_placeholder(flow_payload.get("recent_5d")) or self._is_placeholder(
                flow_payload.get("total_120d")
            ):
                source_hint = None
                backend = self.fund_flow_backend
                tasks.append(
                    self._new_task(
                        flow_key,
                        "assets",
                        source_hint=source_hint,
                        backend=backend,
                        trigger_reason="placeholder",
                    )
                )
        return tasks

    def _scan_estimated_fund_flow(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        tasks: List[Dict[str, Any]] = []
        fund_flow = payload.get("fund_flow", {})
        for flow_key, flow_payload in fund_flow.items():
            if not isinstance(flow_payload, dict) or not bool(flow_payload.get("is_estimated")):
                continue
            tasks.append(
                self._new_task(
                    flow_key,
                    "assets",
                    backend=self.fund_flow_backend,
                    trigger_reason="estimated_fallback",
                )
            )
        return tasks

    def _scan_stale_entries(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        tasks: List[Dict[str, Any]] = []
        macro = payload.get("macro_indicators", {})
        for indicator_key, indicator_payload in macro.items():
            if isinstance(indicator_payload, dict) and bool(indicator_payload.get("is_stale")):
                tasks.append(
                    self._new_task(
                        indicator_key,
                        "essential",
                        trigger_reason="stale_data",
                        expected_period=indicator_payload.get("expected_period"),
                    )
                )

        monetary = payload.get("monetary_policy", {})
        for policy_key, policy_payload in monetary.items():
            if isinstance(policy_payload, dict) and bool(policy_payload.get("is_stale")):
                tasks.append(
                    self._new_task(
                        policy_key,
                        "essential",
                        trigger_reason="stale_data",
                        expected_period=policy_payload.get("expected_period"),
                    )
                )
        return tasks

    def _new_task(
        self,
        indicator_key: str,
        phase: str,
        source_hint: Optional[str] = None,
        backend: Optional[str] = None,
        trigger_reason: str = "missing",
        expected_period: Optional[str] = None,
    ) -> Dict[str, Any]:
        profile_key = get_profile_key(indicator_key)
        profile = SEARCH_PROFILES.get(profile_key, {})
        task_context = self._context_for_expected_period(expected_period)
        query = self._apply_query_templates(profile.get("query"), task_context)
        queries = [self._apply_query_templates(q, task_context) for q in (profile.get("queries") or [])]
        queries = [q for q in queries if q]
        query_families = self._render_query_families(profile.get("query_families"), task_context)
        field_queries = self._render_field_queries(profile.get("field_queries"), task_context)
        expected_period_tokens = [
            str(task_context.get("expected_period_label") or "").strip(),
            str(task_context.get("expected_period_range_label") or "").strip(),
            f"{task_context.get('expected_year')}年{task_context.get('expected_month2')}月",
            f"{task_context.get('expected_year')}-{task_context.get('expected_month2')}",
        ]
        expected_period_tokens = [token for token in expected_period_tokens if token and "None" not in token]
        return {
            "task_id": str(uuid.uuid4()),
            "stage_phase": phase,
            "indicator_key": indicator_key,
            "search_backend": self.search_backend,
            "fund_flow_backend": backend,
            "query_template_id": profile_key,
            "preferred_domains": profile.get("preferred_domains", []),
            "exclude_domains": profile.get("exclude_domains", []),
            "time_range": profile.get("time_range"),
            "max_age_days": profile.get("max_age_days"),
            "query": query,
            "queries": queries,
            "query_families": query_families,
            "query_candidates_expanded": [q for family in query_families for q in family.get("queries", [])],
            "field_queries": field_queries,
            "unit": profile.get("unit"),
            "issuer": profile.get("issuer"),
            "issuer_aliases": profile.get("issuer_aliases", []),
            "required_keywords": profile.get("required_keywords", []),
            "exclude_keywords": profile.get("exclude_keywords", []),
            "strict_required_keywords": profile.get("strict_required_keywords", False),
            "strict_issuer_match": profile.get("strict_issuer_match", False),
            "required_output_fields": profile.get("required_output_fields", []),
            "evidence_keywords": profile.get("evidence_keywords", []),
            "good_url_patterns": profile.get("good_url_patterns", []),
            "bad_url_patterns": profile.get("bad_url_patterns", []),
            "report_usage": profile.get("report_usage"),
            "language": profile.get("language"),
            "topic": profile.get("topic"),
            "max_results": profile.get("max_results"),
            "search_depth": profile.get("search_depth"),
            "chunks_per_source": profile.get("chunks_per_source"),
            "auto_parameters": profile.get("auto_parameters"),
            "days": profile.get("days"),
            "low_score_threshold": profile.get("low_score_threshold"),
            "allow_low_score_extract": profile.get("allow_low_score_extract", False),
            "extract_policy": profile.get("extract_policy", {}),
            "source_hint": source_hint,
            "trigger_reason": trigger_reason,
            "force_refresh": trigger_reason == "stale_data",
            "expected_period": expected_period,
            "expected_period_tokens": expected_period_tokens,
            "retry_count": 0,
            "created_at": int(time.time()),
        }

    def build_tasks(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        if self.task_file is None:
            self.task_file = build_run_paths_from_reference(
                payload=payload,
                fallback_to_today=True,
            ).search_tasks_stage2
        self.query_context = self._build_query_context(payload)
        tasks = (
            self._from_missing_items(payload)
            + self._scan_placeholders(payload)
            + self._scan_estimated_fund_flow(payload)
            + self._scan_stale_entries(payload)
        )
        # 去重：同一 indicator_key 只保留一条，避免 basic/advanced 双倍调用
        seen: Dict[str, int] = {}
        priority = {"stale_data": 4, "placeholder": 3, "missing": 2, "estimated_fallback": 1}
        unique_tasks: List[Dict[str, Any]] = []
        for task in tasks:
            key = task.get("query_template_id") or task["indicator_key"]
            reason = str(task.get("trigger_reason") or "missing")
            score = priority.get(reason, 0)
            if key not in seen:
                seen[key] = score
                unique_tasks.append(task)
                continue
            should_replace = score > seen[key] or (
                score == seen[key] and task.get("indicator_key") == task.get("query_template_id")
            )
            if should_replace:
                seen[key] = score
                for idx, old_task in enumerate(unique_tasks):
                    old_key = old_task.get("query_template_id") or old_task.get("indicator_key")
                    if old_key == key:
                        unique_tasks[idx] = task
                        break
        if self.stage_phase != "all":
            unique_tasks = [t for t in unique_tasks if t["stage_phase"] == self.stage_phase]
        logger.info(f"[Stage2TaskPlanner] 生成 {len(unique_tasks)} 条任务")
        return unique_tasks

    def write_jsonl(self, tasks: List[Dict[str, Any]]) -> Path:
        self.task_file.parent.mkdir(parents=True, exist_ok=True)
        with self.task_file.open("w", encoding="utf-8") as f:
            for task in tasks:
                f.write(json.dumps(task, ensure_ascii=False) + "\n")
        logger.info(f"[Stage2TaskPlanner] 已写入 {self.task_file}")
        return self.task_file


__all__ = ["Stage2TaskPlanner"]
