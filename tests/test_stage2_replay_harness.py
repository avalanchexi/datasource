"""Deterministic offline replay harness scaffold for stage2_unified_enhancer.

Fixtures: tests/fixtures/stage2_replay/ (built by _build_fixtures.py from real runs).
Recorded files double as oracle (result_type/extraction from a real run).
This file is scaffold-only until Tasks 3/4 append pytest coverage. The golden
refresh command becomes useful after those tests exist:
STAGE2_REPLAY_UPDATE_GOLDEN=1 pytest tests/test_stage2_replay_harness.py
"""

import json
import os
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "stage2_replay"
META = json.loads((FIXTURES / "fixture_meta.json").read_text(encoding="utf-8"))
PARSE_ERROR_KEY = META["parse_error_key"]  # 合成 parse_error,不参与 oracle


def load_recordings():
    """indicator_key -> recorded payload(含 raw_results/extraction/result_type)。"""
    by_key = {}
    paths_by_key = {}
    for path in sorted(FIXTURES.glob("recorded/*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        key = rec["task"]["indicator_key"]
        if key in by_key:
            raise AssertionError(
                "duplicate replay recording indicator_key: "
                f"{key!r} in {paths_by_key[key]} and {path}"
            )
        by_key[key] = rec
        paths_by_key[key] = path
    return by_key


def _record_id(rec):
    task = rec.get("task") if isinstance(rec.get("task"), dict) else {}
    return rec.get("task_id") or task.get("task_id") or task.get("indicator_key")


def _append_query(queries, value):
    if isinstance(value, str) and value:
        queries.append(value)


def _append_field_queries(queries, field_queries):
    if isinstance(field_queries, dict):
        if "query" in field_queries or "queries" in field_queries:
            for key in ("query", "queries"):
                value = field_queries.get(key)
                if isinstance(value, list):
                    for item in value:
                        _append_query(queries, item)
                else:
                    _append_query(queries, value)
            return
        for value in field_queries.values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        _append_field_queries(queries, item)
                    else:
                        _append_query(queries, item)
            elif isinstance(value, dict):
                _append_field_queries(queries, value)
            else:
                _append_query(queries, value)
        return

    if isinstance(field_queries, list):
        for item in field_queries:
            if isinstance(item, dict):
                _append_field_queries(queries, item)
            else:
                _append_query(queries, item)


def _task_queries(task):
    """Return every query source that stage2 task execution may search."""
    queries = []
    _append_query(queries, task.get("query"))
    for query in task.get("queries") or []:
        _append_query(queries, query)
    for family in task.get("query_families") or []:
        if not isinstance(family, dict):
            continue
        for query in family.get("queries") or []:
            _append_query(queries, query)
    _append_field_queries(queries, task.get("field_queries"))
    return queries


def _recordings_by_indicator_query():
    by_indicator_query = {}
    for rec in load_recordings().values():
        task = rec["task"]
        indicator_key = task["indicator_key"]
        for q in _task_queries(task):
            if q:
                key = (indicator_key, q)
                existing = by_indicator_query.get(key)
                if existing and _record_id(existing) != _record_id(rec):
                    raise AssertionError(
                        "duplicate replay recording for indicator/query: "
                        f"indicator={indicator_key!r}, query={q!r}, "
                        f"records={_record_id(existing)!r}/{_record_id(rec)!r}"
                    )
                by_indicator_query[key] = rec
    return by_indicator_query


def _query_candidates(by_indicator_query):
    candidates = {}
    for (_indicator_key, query), rec in by_indicator_query.items():
        candidates.setdefault(query, []).append(rec)
    return candidates


def _candidate_label(rec):
    task = rec.get("task") if isinstance(rec.get("task"), dict) else {}
    indicator = rec.get("indicator_key") or task.get("indicator_key")
    result_type = rec.get("result_type")
    return f"{indicator}:{result_type}"


def _candidate_labels(candidates):
    if not candidates:
        return "none"
    return ", ".join(sorted(_candidate_label(rec) for rec in candidates))


class ReplayTavilyClient:
    """以录制 raw_results 应答;无录制的 query 断言失败。

    Production Stage2 calls Tavily with only the query text. When multiple fixture
    records share text, prefer the real search/manual replay lane and fail loudly
    if the query still cannot be resolved deterministically.
    """

    def __init__(self):
        self._by_indicator_query = _recordings_by_indicator_query()
        self._query_candidates = _query_candidates(self._by_indicator_query)
        self.search_calls = 0

    def _indicator_from_kwargs(self, kwargs):
        for name in ("indicator_key", "indicator", "task_indicator"):
            value = kwargs.get(name)
            if value:
                return value
        task = kwargs.get("task")
        if isinstance(task, dict):
            return (
                task.get("indicator_key")
                or task.get("indicator")
                or task.get("task_indicator")
            )
        return None

    def _lookup_recording(self, query, kwargs):
        indicator = self._indicator_from_kwargs(kwargs)
        if indicator:
            rec = self._by_indicator_query.get((indicator, query))
            if rec:
                return rec
            candidates = self._query_candidates.get(query) or []
            raise AssertionError(
                "unrecorded replay Tavily query for explicit indicator: "
                f"indicator={indicator!r}, query={query!r}; "
                "candidate indicators/result_types for query: "
                f"{_candidate_labels(candidates)}"
            )
        candidates = self._query_candidates.get(query) or []
        if not candidates:
            raise AssertionError(f"unrecorded replay Tavily query: {query!r}")
        if len(candidates) == 1:
            return candidates[0]
        search_lane_types = {"search_success", "manual_required"}
        search_lane_candidates = [
            rec for rec in candidates if rec.get("result_type") in search_lane_types
        ]
        if len(search_lane_candidates) == 1:
            return search_lane_candidates[0]
        candidate_labels = ", ".join(sorted(_candidate_label(rec) for rec in candidates))
        raise AssertionError(
            "ambiguous replay Tavily query without indicator: "
            f"{query!r}; candidate indicators/result_types: {candidate_labels}. "
            "Pass indicator_key, indicator, or task_indicator to ReplayTavilyClient.search."
        )

    async def search(self, *args, **kwargs):
        self.search_calls += 1
        query = kwargs.get("query") or (args[0] if args else "")
        rec = self._lookup_recording(query, kwargs)
        raw = rec.get("raw_results") if rec else []
        return {"results": raw or []}

    async def extract(self, *args, **kwargs):
        return {"results": []}


class ReplayDeepSeek:
    """对录制任务回放其 extraction;其余返回 no_value。"""

    def __init__(self):
        self._by_key = load_recordings()

    async def extract(
        self,
        snippets,
        indicator,
        unit_hint=None,
        issuer_hint=None,
        request_timeout=None,
        required_output_fields=None,
    ):
        rec = self._by_key.get(indicator)
        if rec and rec.get("extraction"):
            return dict(rec["extraction"])
        return {"value": None, "note": "deepseek_no_value"}


class ReplayRegistry:
    """structured_responses.json 驱动;不在表内的 indicator 视为无 provider(逼走搜索链路)。"""

    def __init__(self):
        self._spec = json.loads(
            (FIXTURES / "structured_responses.json").read_text(encoding="utf-8")
        )
        self.calls = 0

    def provider_for(self, indicator_key):
        return object() if indicator_key in self._spec else None

    async def fetch(self, task, market_payload, reference_date):
        from datasource.providers.stage2_structured import StructuredProviderError, StructuredResult

        self.calls += 1
        key = task["indicator_key"]
        spec = self._spec[key]
        if spec["behavior"] == "parse_error":
            raise StructuredProviderError(
                provider="replay-fixture",
                indicator_key=key,
                reason="parse_error",
                message="replay fixture parse error",
            )
        return StructuredResult(
            provider="replay-fixture",
            indicator_key=key,
            category=task.get("category"),
            payload=dict(spec["payload"]),
            source=spec["source"],
            source_url=spec["source_url"],
            source_tier=spec["source_tier"],
            as_of_date=reference_date,
            confidence=spec["confidence"],
        )


# 每项必须有实证来由(连跑两次 capture 的 diff),不许凭感觉加。
VOLATILE_FIELDS = set()  # Task 5 Step 1 实证后填充,如 {"created_at", "elapsed_ms", ...}


def _result_sort_key(item):
    if not isinstance(item, dict):
        return ("", "")
    task = item.get("task") if isinstance(item.get("task"), dict) else {}
    return (
        str(item.get("task_id") or task.get("task_id") or ""),
        str(item.get("indicator_key") or task.get("indicator_key") or ""),
    )


def sort_results(items):
    """对结果列表按 task_id/indicator 规范排序,消除并发完成顺序抖动。"""
    return sorted(items, key=_result_sort_key) if isinstance(items, list) else items


def normalize(obj):
    """递归剔除 VOLATILE_FIELDS、按 dict 键排序;不重排 list(保留 market_data 语义顺序)。"""
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in sorted(obj.items()) if k not in VOLATILE_FIELDS}
    if isinstance(obj, list):
        return [normalize(v) for v in obj]
    return obj


def assert_or_update_golden(payload, name):
    golden = FIXTURES / "golden" / name
    text = json.dumps(normalize(payload), ensure_ascii=False, indent=2, sort_keys=True)
    if os.environ.get("STAGE2_REPLAY_UPDATE_GOLDEN") == "1":
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(text, encoding="utf-8")
        return
    update_cmd = "STAGE2_REPLAY_UPDATE_GOLDEN=1 pytest tests/test_stage2_replay_harness.py"
    assert golden.exists(), f"golden missing: {golden}; update with: {update_cmd}"
    assert text == golden.read_text(encoding="utf-8"), (
        f"golden mismatch: {golden}; update with: {update_cmd}"
    )
