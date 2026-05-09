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
