#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared path helpers for per-run outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any, Optional


_COMPACT_DATE_RE = re.compile(r"(20\d{6})")
_DASHED_DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


def normalize_run_date(value: str) -> str:
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"无法解析日期: {value}")


def to_compact_date(value: str) -> str:
    return normalize_run_date(value).replace("-", "")


def infer_date_from_payload(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
    for key in ("date", "end_date", "start_date"):
        value = metadata.get(key)
        if not value:
            continue
        try:
            return normalize_run_date(str(value))
        except ValueError:
            continue
    return None


def infer_date_from_path(path: Path | str) -> Optional[str]:
    text = str(path)
    match = _DASHED_DATE_RE.search(text)
    if match:
        return match.group(1)
    match = _COMPACT_DATE_RE.search(text)
    if match:
        return normalize_run_date(match.group(1))
    return None


def infer_run_date(
    *,
    date: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    path: Optional[Path | str] = None,
    fallback_to_today: bool = False,
) -> Optional[str]:
    if date:
        return normalize_run_date(date)
    derived = infer_date_from_payload(payload)
    if derived:
        return derived
    if path is not None:
        derived = infer_date_from_path(path)
        if derived:
            return derived
    if fallback_to_today:
        return datetime.now().strftime("%Y-%m-%d")
    return None


@dataclass(frozen=True)
class RunPaths:
    date: str

    @property
    def compact(self) -> str:
        return self.date.replace("-", "")

    @property
    def data_dir(self) -> Path:
        return Path("data") / "runs" / self.compact

    @property
    def log_dir(self) -> Path:
        return Path("logs") / "runs" / self.compact

    @property
    def market_data(self) -> Path:
        return self.data_dir / "market_data.json"

    @property
    def market_data_stage2(self) -> Path:
        return self.data_dir / "market_data_stage2.json"

    @property
    def market_data_complete(self) -> Path:
        return self.data_dir / "market_data_complete.json"

    @property
    def pring_result(self) -> Path:
        return self.data_dir / "pring_result.json"

    @property
    def search_tasks_stage2(self) -> Path:
        return self.data_dir / "search_tasks_stage2.jsonl"

    @property
    def websearch_results_auto(self) -> Path:
        return self.data_dir / "websearch_results_auto.json"

    @property
    def websearch_results_manual(self) -> Path:
        return self.data_dir / "websearch_results_manual.json"

    @property
    def gap_monitor(self) -> Path:
        return self.data_dir / "gap_monitor.json"

    @property
    def quality_metrics(self) -> Path:
        return self.data_dir / "quality_metrics.json"

    @property
    def policy_evaluation(self) -> Path:
        return self.data_dir / "policy_evaluation.json"

    @property
    def run_snapshot(self) -> Path:
        return self.data_dir / "run_snapshot.json"

    @property
    def recap_facts(self) -> Path:
        return self.data_dir / "recap_facts.json"

    @property
    def trend_history_gap(self) -> Path:
        return self.data_dir / "trend_history_gap.json"

    @property
    def stage2_log(self) -> Path:
        return self.log_dir / "stage2_unified_log.json"

    @property
    def stage2_task_log(self) -> Path:
        return self.log_dir / "stage_task_log.jsonl"

    @property
    def observability(self) -> Path:
        return self.log_dir / "observability.json"

    @property
    def stage3_log(self) -> Path:
        return self.log_dir / "pring_stage3_log.json"

    @property
    def report_markdown(self) -> Path:
        return Path("reports") / f"{self.date}-背景扫描120.md"

    @property
    def cache_path(self) -> Path:
        return Path("data") / "cache" / "tavily_cache.sqlite"


def build_run_paths(date: str) -> RunPaths:
    return RunPaths(date=normalize_run_date(date))


def build_run_paths_from_reference(
    *,
    date: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    path: Optional[Path | str] = None,
    fallback_to_today: bool = False,
) -> RunPaths:
    resolved = infer_run_date(
        date=date,
        payload=payload,
        path=path,
        fallback_to_today=fallback_to_today,
    )
    if not resolved:
        raise ValueError("无法推导运行日期")
    return build_run_paths(resolved)
