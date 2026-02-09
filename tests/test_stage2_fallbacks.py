import asyncio
from pathlib import Path
import pytest

from scripts.stage2_unified_enhancer import _execute_tasks


class FakeClient422:
    def __init__(self):
        self.extract_calls = 0

    async def search(self, **kwargs):
        # 返回一条高分 snippet，触发 extract 分支
        return {
            "results": [
                {
                    "url": "https://example.com/etf_flow",
                    "snippet": "ETF 资金净流入 10 亿元",
                    "score": 0.9,
                }
            ]
        }

    async def extract(self, **kwargs):
        self.extract_calls += 1
        return {"status": 422}


class FakeExtractorTimeout:
    def __init__(self):
        self.calls = 0

    async def extract(self, *args, **kwargs):  # pragma: no cover - 异常路径
        self.calls += 1
        raise asyncio.TimeoutError("deepseek timeout")

    def _fallback_extract(self, snips):
        # 提供一个数值兜底
        return 1.23, snips[0].get("url") if snips else None


@pytest.mark.anyio("asyncio")
async def test_extract_422_triggers_global_disable(tmp_path):
    client = FakeClient422()
    extractor = FakeExtractorTimeout()
    stats = {}
    market_payload = {"fund_flow": {"etf": {"type": "etf"}, "northbound": {"type": "northbound"}}}
    tasks = [
        {
            "task_id": "test-etf-422",
            "indicator_key": "etf",
            "stage_phase": "assets",
            "search_backend": "tavily",
            "fund_flow_backend": "tavily",
            "extraction_backend": "deepseek",
            "query": "A股 ETF 资金流 申购赎回 近5日 120日",
            "created_at": 1700000000,
            "preferred_domains": [],
        },
        {
            "task_id": "test-northbound-422",
            "indicator_key": "northbound",
            "stage_phase": "assets",
            "search_backend": "tavily",
            "fund_flow_backend": "tavily",
            "extraction_backend": "deepseek",
            "query": "北向资金 近5日 120日",
            "created_at": 1700000001,
            "preferred_domains": [],
        },
    ]

    completed, failures, websearch_results = await _execute_tasks(
        tasks,
        market_payload,
        client,
        None,
        extractor,
        task_log_path=tmp_path / "task_log.jsonl",
        cache_ttl=None,
        fund_flow_backend="tavily",
        forex_backend="tavily",
        deepseek_timeout=8,
        extraction_backend="deepseek",
        deepseek_max_concurrency=1,
        deepseek_serial_keys=None,
        stats=stats,
        use_queue=False,
        queue_concurrency=1,
        queue_maxsize=10,
        queue_retry_limit=0,
        disable_extract=False,
        auto_disable_extract_on_422=True,
        extract_422_threshold=1,
        extract_topk=1,
        llm_hard_timeout=10,
    )

    assert len(completed) + len(failures) == 2
    assert stats.get("tavily_extract_422_count", 0) >= 1
    assert stats.get("extract_globally_disabled") is True
    assert stats.get("extract_global_disable_reason") is not None
    # 第二个任务应走全局禁用后路径，不再触发 client.extract
    assert client.extract_calls == 1
    assert websearch_results
    assert any(
        result.get("task", {}).get("extract_skipped_reason") == "extract_globally_disabled"
        for result in websearch_results
    )


@pytest.mark.anyio("asyncio")
async def test_deepseek_timeout_records_error(tmp_path):
    client = FakeClient422()
    # 让 extract 完全跳过，直接走 DeepSeek（无 422）
    async def search_only(**kwargs):
        return {
            "results": [
                {
                    "url": "https://example.com/etf_flow",
                    "snippet": "ETF 资金净流入 10 亿元",
                    "score": 0.9,
                }
            ]
        }

    client.search = search_only  # type: ignore
    client.extract = None  # type: ignore

    extractor = FakeExtractorTimeout()
    stats = {}
    market_payload = {"fund_flow": {"etf": {"type": "etf"}}}
    task = {
        "task_id": "test-etf-timeout",
        "indicator_key": "etf",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "fund_flow_backend": "tavily",
        "extraction_backend": "deepseek",
        "query": "A股 ETF 资金流 申购赎回 近5日 120日",
        "created_at": 1700000000,
        "preferred_domains": [],
    }

    completed, failures, websearch_results = await _execute_tasks(
        [task],
        market_payload,
        client,
        None,
        extractor,
        task_log_path=tmp_path / "task_log.jsonl",
        cache_ttl=None,
        fund_flow_backend="tavily",
        forex_backend="tavily",
        deepseek_timeout=0.1,
        extraction_backend="deepseek",
        deepseek_max_concurrency=1,
        deepseek_serial_keys=None,
        stats=stats,
        use_queue=False,
        queue_concurrency=1,
        queue_maxsize=10,
        queue_retry_limit=0,
        disable_extract=True,
        extract_topk=1,
        llm_hard_timeout=0.2,
    )

    assert not completed
    assert len(failures) == 1
    record = failures[0]
    # Timeout 会被包装为 deepseek_error:... 并计入 llm_error
    assert "deepseek_error" in (record.get("note") or "") or "Timeout" in (record.get("llm_error") or "")
    assert stats.get("timeout_count", 0) >= 1
    assert stats.get("deepseek_timeouts", 0) >= 1
    # fallback_extract 提供的值应被写回 extraction
    extraction_note = websearch_results[0]["extraction"].get("note", "")
    assert "regex_fallback" in extraction_note or "deepseek_error" in extraction_note
@pytest.fixture
def anyio_backend():
    # 强制使用 asyncio，避免缺少 trio 依赖导致的参数化失败
    return "asyncio"
