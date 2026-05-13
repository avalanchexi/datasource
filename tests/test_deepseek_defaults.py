import json
import sys
from types import SimpleNamespace

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


def test_deepseek_schema_hint_keeps_non_fund_flow_core_small() -> None:
    hint = DeepSeekExtractionAgent._schema_hint(is_fund_flow=False)
    assert "recent_5d" not in hint
    assert "total_120d" not in hint
    assert "value" in hint
    assert "source_url" in hint
    assert "manual_required" in hint


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
