import asyncio
import json
import sys
from types import SimpleNamespace

from datasource.engines import deepseek_reasoner
from datasource.engines.deepseek_reasoner import DeepSeekExtractionAgent
from datasource.generators import simple_report
from scripts import stage2_unified_enhancer


def test_deepseek_extraction_agent_defaults_to_v4_pro() -> None:
    agent = DeepSeekExtractionAgent(api_key="test-key")

    assert agent.model == "deepseek-v4-pro"


def test_stage2_cli_deepseek_model_defaults_to_v4_pro(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["stage2_unified_enhancer.py", "--market-data", "market_data.json"],
    )

    args = stage2_unified_enhancer._parse_args()

    assert args.deepseek_model == "deepseek-v4-pro"


def test_stage2_cli_deepseek_timeouts_match_v4_pro_latency(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["stage2_unified_enhancer.py", "--market-data", "market_data.json"],
    )

    args = stage2_unified_enhancer._parse_args()

    assert args.deepseek_timeout == 30.0
    assert args.llm_hard_timeout == 35.0


def test_stage2_cli_uses_parallel_deepseek_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["stage2_unified_enhancer.py", "--market-data", "market_data.json"],
    )

    args = stage2_unified_enhancer._parse_args()

    assert args.use_queue is True
    assert args.queue_concurrency == 3
    assert args.deepseek_max_concurrency == 3


def test_deepseek_agent_uses_configurable_extract_max_tokens(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_EXTRACT_MAX_TOKENS", raising=False)
    agent = DeepSeekExtractionAgent(api_key="test-key")
    assert agent.extract_max_tokens == 900

    monkeypatch.setenv("DEEPSEEK_EXTRACT_MAX_TOKENS", "1200")
    agent = DeepSeekExtractionAgent(api_key="test-key")
    assert agent.extract_max_tokens == 1200

    agent = DeepSeekExtractionAgent(api_key="test-key", extract_max_tokens=0)
    assert agent.extract_max_tokens == 300


def test_deepseek_agent_disables_environment_proxy_by_default(monkeypatch) -> None:
    created_http_clients: list[object] = []
    created_openai_kwargs: list[dict[str, object]] = []

    class FakeAsyncHttpxClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created_http_clients.append(self)

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            created_openai_kwargs.append(kwargs)

    monkeypatch.setattr(deepseek_reasoner, "DefaultAsyncHttpxClient", FakeAsyncHttpxClient)
    monkeypatch.setattr(deepseek_reasoner, "AsyncOpenAI", FakeAsyncOpenAI)

    agent = DeepSeekExtractionAgent(api_key="test-key")
    asyncio.run(agent._ensure_client())

    assert created_http_clients[0].kwargs["trust_env"] is False
    assert created_openai_kwargs[0]["http_client"] is created_http_clients[0]


def test_deepseek_agent_allows_explicit_environment_proxy_mode(monkeypatch) -> None:
    created_http_clients: list[object] = []

    class FakeAsyncHttpxClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created_http_clients.append(self)

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(deepseek_reasoner, "DefaultAsyncHttpxClient", FakeAsyncHttpxClient)
    monkeypatch.setattr(deepseek_reasoner, "AsyncOpenAI", FakeAsyncOpenAI)

    agent = DeepSeekExtractionAgent(api_key="test-key", trust_env=True)
    asyncio.run(agent._ensure_client())

    assert created_http_clients[0].kwargs["trust_env"] is True


def test_deepseek_schema_hint_keeps_non_fund_flow_core_small() -> None:
    hint = DeepSeekExtractionAgent._schema_hint(is_fund_flow=False)
    assert "recent_5d" not in hint
    assert "total_120d" not in hint
    assert "value" in hint
    assert "source_url" in hint
    assert "manual_required" in hint


def test_deepseek_schema_hint_includes_requested_compare_fields() -> None:
    hint = DeepSeekExtractionAgent._schema_hint(
        is_fund_flow=False,
        required_output_fields=[
            "previous_value",
            "change_rate",
            "change_from_120d",
            "value_type",
            "yoy_month",
            "yoy_ytd",
            "rrr_type",
            "unsupported_field",
        ],
    )

    assert '"previous_value": float|null' in hint
    assert '"change_rate": float|null' in hint
    assert '"change_from_120d": float|null' in hint
    assert '"value_type": str|null' in hint
    assert '"yoy_month": float|null' in hint
    assert '"yoy_ytd": float|null' in hint
    assert '"rrr_type": str|null' in hint
    assert "unsupported_field" not in hint


def test_deepseek_extract_returns_requested_compare_fields(monkeypatch) -> None:
    seen_messages: list[object] = []

    class FakeCompletions:
        async def create(self, **kwargs):
            seen_messages.extend(kwargs["messages"])
            message = SimpleNamespace(
                content=json.dumps(
                    {
                        "value": "4.1",
                        "unit": "%",
                        "source_url": "https://www.stats.gov.cn/example.html",
                        "as_of_date": None,
                        "report_period": "2026-04",
                        "manual_required": False,
                        "manual_reason": None,
                        "previous_value": "5.7",
                        "change_rate": "-28.07",
                        "change_from_120d": "0.0",
                        "value_type": "yoy_month",
                        "yoy_month": "4.1",
                        "yoy_ytd": None,
                        "rrr_type": "weighted",
                    }
                )
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self):
            self.chat = FakeChat()

        def with_options(self, **kwargs):
            return self

    async def fake_ensure_client(self):
        return FakeClient()

    monkeypatch.setattr(DeepSeekExtractionAgent, "_ensure_client", fake_ensure_client)
    agent = DeepSeekExtractionAgent(api_key="test-key")

    result = asyncio.run(
        agent.extract(
            [{"url": "https://www.stats.gov.cn/example.html", "content": "工业增加值同比4.1%"}],
            "industrial",
            unit_hint="%",
            required_output_fields=[
                "previous_value",
                "change_rate",
                "change_from_120d",
                "value_type",
                "yoy_month",
                "yoy_ytd",
                "rrr_type",
            ],
        )
    )

    assert result["previous_value"] == 5.7
    assert result["change_rate"] == -28.07
    assert result["change_from_120d"] == 0.0
    assert result["value_type"] == "yoy_month"
    assert result["yoy_month"] == 4.1
    assert result["yoy_ytd"] is None
    assert result["rrr_type"] == "weighted"
    assert "requested compare/window fields" in seen_messages[0]["content"]


def test_deepseek_classifies_unterminated_json_as_truncated() -> None:
    exc = json.JSONDecodeError("Unterminated string starting at", '{"value": "abc', 10)
    assert DeepSeekExtractionAgent._json_error_reason(exc) == "deepseek_json_truncated"


def test_deepseek_classifies_missing_closing_json_as_truncated() -> None:
    try:
        json.loads('{"value": 1')
    except json.JSONDecodeError as exc:
        assert DeepSeekExtractionAgent._json_error_reason(exc) == "deepseek_json_truncated"
    else:
        raise AssertionError("incomplete JSON should fail to decode")


def test_deepseek_classifies_eof_missing_value_as_truncated() -> None:
    try:
        json.loads('{"value": ')
    except json.JSONDecodeError as exc:
        assert DeepSeekExtractionAgent._json_error_reason(exc) == "deepseek_json_truncated"
    else:
        raise AssertionError("incomplete JSON should fail to decode")


def test_deepseek_classifies_non_eof_missing_value_as_parse_error() -> None:
    try:
        json.loads('{"value": }')
    except json.JSONDecodeError as exc:
        assert DeepSeekExtractionAgent._json_error_reason(exc) == "deepseek_json_parse_error"
    else:
        raise AssertionError("malformed JSON should fail to decode")


def test_stage2_cli_can_disable_queue_explicitly(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stage2_unified_enhancer.py",
            "--market-data",
            "market_data.json",
            "--no-use-queue",
        ],
    )

    args = stage2_unified_enhancer._parse_args()

    assert args.use_queue is False
    assert args.queue_concurrency == 3
    assert args.deepseek_max_concurrency == 3


def test_simple_report_summary_model_defaults_to_v4_pro(monkeypatch) -> None:
    seen: dict[str, str] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            seen["model"] = kwargs["model"]
            message = SimpleNamespace(content="asset conclusion")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

        def with_options(self, **kwargs):
            return self

    monkeypatch.setattr(simple_report, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("DEEPSEEK_SUMMARY_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    output, status, _ = simple_report._generate_asset_conclusion("Gold up")

    assert status == "success"
    assert output.startswith("asset conclusion")
    assert seen["model"] == "deepseek-v4-pro"


def test_simple_report_summary_model_prefers_summary_env(monkeypatch) -> None:
    seen: dict[str, str] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            seen["model"] = kwargs["model"]
            message = SimpleNamespace(content="asset conclusion")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

        def with_options(self, **kwargs):
            return self

    monkeypatch.setattr(simple_report, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-model-env")
    monkeypatch.setenv("DEEPSEEK_SUMMARY_MODEL", "deepseek-summary-env")

    simple_report._generate_asset_conclusion("Gold up")

    assert seen["model"] == "deepseek-summary-env"


def test_simple_report_summary_model_falls_back_to_model_env(monkeypatch) -> None:
    seen: dict[str, str] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            seen["model"] = kwargs["model"]
            message = SimpleNamespace(content="asset conclusion")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

        def with_options(self, **kwargs):
            return self

    monkeypatch.setattr(simple_report, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("DEEPSEEK_SUMMARY_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-model-env")

    simple_report._generate_asset_conclusion("Gold up")

    assert seen["model"] == "deepseek-model-env"
