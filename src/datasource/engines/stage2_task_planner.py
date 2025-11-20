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
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from datasource.config.search_profiles import SEARCH_PROFILES

PLACEHOLDER_SENTINELS = {None, 0, 0.0, 7.13}


class Stage2TaskPlanner:
    """扫描占位并生成 Tavily/DeepSeek 搜索任务"""

    def __init__(
        self,
        stage_phase: str = "all",
        search_backend: str = "tavily",
        task_file: Path = Path("reports/search_tasks_stage2.jsonl"),
        fund_flow_backend: str = "tavily",
    ) -> None:
        self.stage_phase = stage_phase
        self.search_backend = search_backend
        self.task_file = task_file
        self.fund_flow_backend = fund_flow_backend

    @staticmethod
    def _is_placeholder(value: Any) -> bool:
        if value in PLACEHOLDER_SENTINELS:
            return True
        try:
            num = float(value)
        except Exception:
            return False
        return abs(num - 7.13) < 1e-6

    def _from_missing_items(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        tasks: List[Dict[str, Any]] = []
        for item in payload.get("missing_items", []):
            if isinstance(item, dict):
                indicator_key = item.get("key") or item
                phase = item.get("stage_phase") or self._infer_phase(indicator_key)
            else:
                indicator_key = item
                phase = self._infer_phase(indicator_key)
            tasks.append(self._new_task(indicator_key, phase))
        return tasks

    def _infer_phase(self, indicator_key: str) -> str:
        key = (indicator_key or "").lower()
        if key in {"cpi", "ppi", "pmi", "pmi_new_orders", "industrial_output", "gdp", "m1", "m2"}:
            return "essential"
        return "assets"

    def _scan_placeholders(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        tasks: List[Dict[str, Any]] = []
        macro = payload.get("macro_indicators", {})
        for indicator_key, indicator_payload in macro.items():
            if self._is_placeholder(indicator_payload.get("current_value")):
                tasks.append(self._new_task(indicator_key, "essential"))

        monetary = payload.get("monetary_policy", {})
        for policy_key, policy_payload in monetary.items():
            if self._is_placeholder(policy_payload.get("current_value")):
                tasks.append(self._new_task(policy_key, "essential"))

        fund_flow = payload.get("fund_flow", {})
        for flow_key, flow_payload in fund_flow.items():
            if self._is_placeholder(flow_payload.get("recent_5d")) or self._is_placeholder(
                flow_payload.get("total_120d")
            ):
                source_hint = None
                backend = self.fund_flow_backend
                tasks.append(self._new_task(flow_key, "assets", source_hint=source_hint, backend=backend))
        return tasks

    def _new_task(
        self,
        indicator_key: str,
        phase: str,
        source_hint: Optional[str] = None,
        backend: Optional[str] = None,
    ) -> Dict[str, Any]:
        profile = SEARCH_PROFILES.get(indicator_key, {})
        return {
            "task_id": str(uuid.uuid4()),
            "stage_phase": phase,
            "indicator_key": indicator_key,
            "search_backend": self.search_backend,
            "fund_flow_backend": backend,
            "query_template_id": indicator_key,
            "preferred_domains": profile.get("preferred_domains", []),
            "time_range": profile.get("time_range"),
            "query": profile.get("query"),
            "unit": profile.get("unit"),
            "issuer": profile.get("issuer"),
            "source_hint": source_hint,
            "retry_count": 0,
            "created_at": int(time.time()),
        }

    def build_tasks(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        tasks = self._from_missing_items(payload) + self._scan_placeholders(payload)
        # 去重（按 indicator_key）
        seen = set()
        unique_tasks = []
        for task in tasks:
            key = (task["indicator_key"], task["stage_phase"])
            if key in seen:
                continue
            seen.add(key)
            unique_tasks.append(task)
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
