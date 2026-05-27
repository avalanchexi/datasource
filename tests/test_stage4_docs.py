import json
from pathlib import Path

import pytest

import scripts.stage4_report_generator as stage4
from datasource.generators.simple_report import _format_monetary_value_for_report


def test_claude_stage4_command_uses_named_args():
    text = Path("CLAUDE.md").read_text(encoding="utf-8")
    assert "scripts/stage4_report_generator.py" in text
    assert "--market-data" in text
    assert "--pring-result" in text
    assert "--output" in text
    assert "兼容入口：tests/scripts/generate_simple_report_test.py" in text


def test_stage4_mlf_non_unified_rate_display():
    entry = {
        "current_value": 2.0,
        "change_120d_bp": 0.0,
        "note": "MLF 多重价位中标利率参考值，口径不适用",
        "as_of_date": "2026-04-25",
    }
    current, change = _format_monetary_value_for_report("mlf", entry)
    assert current == "2.00%（参考）"
    assert change == "口径不适用"


def test_stage4_mlf_non_unified_rate_display_from_manual_reason():
    entry = {
        "current_value": 2.0,
        "change_from_120d": 0.0,
        "manual_reason": "\u591a\u91cd\u4ef7\u4f4d\u4e2d\u6807\u5229\u7387\u53c2\u8003\u503c\uff0c\u53e3\u5f84\u4e0d\u9002\u7528",
    }
    current, change = _format_monetary_value_for_report("mlf", entry)
    assert current == "2.00%\uff08\u53c2\u8003\uff09"
    assert change == "\u53e3\u5f84\u4e0d\u9002\u7528"


def test_stage4_regular_monetary_policy_display_is_not_reference():
    entry = {
        "current_value": 1.8,
        "change_from_120d": 0.1,
        "note": "公开市场操作利率",
        "as_of_date": "2026-04-25",
    }
    current, change = _format_monetary_value_for_report("dr007", entry)
    assert current == "1.80%"
    assert change == "+0.1pp"


def test_stage4_prefers_dated_gap_monitor(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "runs" / "20260409"
    reports_dir = tmp_path / "reports"
    data_dir.mkdir(parents=True)
    reports_dir.mkdir()

    market_path = data_dir / "market_data_complete.json"
    pring_path = data_dir / "pring_result.json"
    gap_path = data_dir / "gap_monitor.json"

    market_path.write_text('{"metadata": {"ai_websearch_enhanced": true}}', encoding="utf-8")
    pring_path.write_text("{}", encoding="utf-8")
    gap_path.write_text('{"manual_required": ["USDCNY"]}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_report_generator.py",
            "--market-data",
            str(market_path),
            "--pring-result",
            str(pring_path),
            "--output",
            str(reports_dir / "out.md"),
        ],
    )

    with pytest.raises(RuntimeError) as exc:
        stage4.main()

    assert "data/runs/20260409/gap_monitor.json" in str(exc.value).replace("\\", "/")


def test_stage4_ignores_stale_gap_when_live_quality_state_is_clean(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "runs" / "20260427"
    reports_dir = tmp_path / "reports"
    data_dir.mkdir(parents=True)
    reports_dir.mkdir()

    market_path = data_dir / "market_data_complete.json"
    pring_path = data_dir / "pring_result.json"
    gap_path = data_dir / "gap_monitor.json"
    output_path = reports_dir / "out.md"

    market_path.write_text(
        """
{
  "metadata": {"ai_websearch_enhanced": true, "date": "2026-04-27"},
  "macro_indicators": {
    "industrial": {
      "current_value": 5.2,
      "previous_value": 5.0,
      "change_rate": 4.0,
      "source": "websearch_manual(https://example.com/industrial)",
      "source_url": "https://example.com/industrial"
    }
  }
}
""".strip(),
        encoding="utf-8",
    )
    pring_path.write_text(
        '{"metadata": {"analysis_date": "2026-04-27"}}',
        encoding="utf-8",
    )
    gap_path.write_text('{"pending_tasks": [], "manual_required": ["industrial"]}', encoding="utf-8")

    called = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(stage4, "generate_report", lambda *args: called.append(args))
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_report_generator.py",
            "--market-data",
            str(market_path),
            "--pring-result",
            str(pring_path),
            "--output",
            str(output_path),
        ],
    )

    stage4.main()

    assert called == [(market_path, pring_path, output_path)]


@pytest.mark.parametrize(
    "manual_required",
    [
        [{"category": "commodities", "symbol": "GC=F"}],
        ["COMEX Gold"],
    ],
)
def test_stage4_ignores_stale_commodity_gap_by_symbol_or_name_when_live_quality_is_clean(
    tmp_path,
    monkeypatch,
    manual_required,
):
    data_dir = tmp_path / "data" / "runs" / "20260427"
    reports_dir = tmp_path / "reports"
    data_dir.mkdir(parents=True)
    reports_dir.mkdir()

    market_path = data_dir / "market_data_complete.json"
    pring_path = data_dir / "pring_result.json"
    gap_path = data_dir / "gap_monitor.json"
    output_path = reports_dir / "out.md"

    market_path.write_text(
        """
{
  "metadata": {"ai_websearch_enhanced": true, "date": "2026-04-27"},
  "commodities": [
    {
      "symbol": "GC=F",
      "name": "COMEX Gold",
      "current_price": 2650.5,
      "unit": "$/oz",
      "source": "websearch_manual(https://example.com/gold)",
      "source_url": "https://example.com/gold"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    pring_path.write_text(
        '{"metadata": {"analysis_date": "2026-04-27"}}',
        encoding="utf-8",
    )
    gap_path.write_text(
        '{"pending_tasks": [], "manual_required": %s}' % json.dumps(manual_required),
        encoding="utf-8",
    )

    called = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(stage4, "generate_report", lambda *args: called.append(args))
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_report_generator.py",
            "--market-data",
            str(market_path),
            "--pring-result",
            str(pring_path),
            "--output",
            str(output_path),
        ],
    )

    stage4.main()

    assert called == [(market_path, pring_path, output_path)]


def test_stage4_blocks_manual_websearch_commodity_without_source_url(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "runs" / "20260427"
    reports_dir = tmp_path / "reports"
    data_dir.mkdir(parents=True)
    reports_dir.mkdir()

    market_path = data_dir / "market_data_complete.json"
    pring_path = data_dir / "pring_result.json"
    gap_path = data_dir / "gap_monitor.json"

    market_path.write_text(
        """
{
  "metadata": {"ai_websearch_enhanced": true, "date": "2026-04-27"},
  "commodities": [
    {
      "symbol": "GC=F",
      "name": "COMEX黄金",
      "current_price": 2650.5,
      "source": "websearch_manual"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    pring_path.write_text(
        '{"metadata": {"analysis_date": "2026-04-27"}}',
        encoding="utf-8",
    )
    gap_path.write_text('{"pending_tasks": [], "manual_required": []}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_report_generator.py",
            "--market-data",
            str(market_path),
            "--pring-result",
            str(pring_path),
            "--output",
            str(reports_dir / "out.md"),
        ],
    )

    with pytest.raises(RuntimeError) as exc:
        stage4.main()

    assert "[unified_quality]" in str(exc.value)
    assert "commodities.GC=F missing_source_url" in str(exc.value)


def test_stage4_blocks_pring_date_mismatch(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "runs" / "20260427"
    reports_dir = tmp_path / "reports"
    data_dir.mkdir(parents=True)
    reports_dir.mkdir()

    market_path = data_dir / "market_data_complete.json"
    pring_path = data_dir / "pring_result.json"
    gap_path = data_dir / "gap_monitor.json"

    market_path.write_text(
        '{"metadata": {"ai_websearch_enhanced": true, "date": "2026-04-27"}}',
        encoding="utf-8",
    )
    pring_path.write_text(
        '{"metadata": {"analysis_date": "2026-04-26"}}',
        encoding="utf-8",
    )
    gap_path.write_text('{"pending_tasks": [], "manual_required": []}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_report_generator.py",
            "--market-data",
            str(market_path),
            "--pring-result",
            str(pring_path),
            "--output",
            str(reports_dir / "out.md"),
        ],
    )

    with pytest.raises(RuntimeError) as exc:
        stage4.main()

    message = str(exc.value)
    assert "2026-04-27" in message
    assert "2026-04-26" in message


def _write_stage4_payloads(tmp_path, *, market_extra, pring_extra=None, gap_payload=None):
    data_dir = tmp_path / "data" / "runs" / "20260527"
    reports_dir = tmp_path / "reports"
    data_dir.mkdir(parents=True)
    reports_dir.mkdir()
    market_path = data_dir / "market_data_complete.json"
    pring_path = data_dir / "pring_result.json"
    gap_path = data_dir / "gap_monitor.json"
    output_path = reports_dir / "out.md"

    market_payload = {
        "metadata": {"ai_websearch_enhanced": True, "date": "2026-05-27"},
        "macro_indicators": {},
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }
    market_payload.update(market_extra)
    pring_payload = {"metadata": {"analysis_date": "2026-05-27"}, "fallback_used": False}
    if pring_extra:
        pring_payload.update(pring_extra)
    if gap_payload is None:
        gap_payload = {"pending_tasks": [], "manual_required": []}

    market_path.write_text(json.dumps(market_payload, ensure_ascii=False), encoding="utf-8")
    pring_path.write_text(json.dumps(pring_payload, ensure_ascii=False), encoding="utf-8")
    gap_path.write_text(json.dumps(gap_payload, ensure_ascii=False), encoding="utf-8")
    return market_path, pring_path, output_path


def _estimated_etf_market_extra():
    return {
        "fund_flow": {
            "etf": {
                "recent_5d": -200.0,
                "total_120d": -1500.0,
                "trend": "流出",
                "source": "websearch_manual",
                "source_url": "https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml",
                "metric_basis": "news_net_flow",
                "source_tier": "tier3",
                "window_evidence": "news_summary",
                "is_estimated": True,
            }
        }
    }


def test_stage4_blocks_estimated_fund_flow_without_downgrade_flag(tmp_path, monkeypatch):
    market_path, pring_path, output_path = _write_stage4_payloads(
        tmp_path,
        market_extra=_estimated_etf_market_extra(),
        gap_payload={"pending_tasks": [], "manual_required": []},
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_report_generator.py",
            "--market-data",
            str(market_path),
            "--pring-result",
            str(pring_path),
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(RuntimeError) as exc:
        stage4.main()

    message = str(exc.value)
    assert "fund_flow.etf" in message
    assert "estimated_not_allowed" in message


def test_stage4_allows_estimated_fund_flow_with_downgrade_flag(tmp_path, monkeypatch):
    market_path, pring_path, output_path = _write_stage4_payloads(
        tmp_path,
        market_extra=_estimated_etf_market_extra(),
        gap_payload={
            "pending_tasks": [{"category": "fund_flow", "key": "etf"}],
            "manual_required": [{"category": "fund_flow", "key": "etf"}],
        },
    )
    called = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(stage4, "generate_report", lambda *args: called.append(args))
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_report_generator.py",
            "--market-data",
            str(market_path),
            "--pring-result",
            str(pring_path),
            "--output",
            str(output_path),
            "--allow-fund-flow-downgrade",
        ],
    )

    stage4.main()

    assert called == [(market_path, pring_path, output_path)]
    market_payload = json.loads(market_path.read_text(encoding="utf-8"))
    assert market_payload["fund_flow"]["etf"]["is_estimated"] is True


def test_stage4_downgrade_flag_still_blocks_non_fund_flow_quality_issue(tmp_path, monkeypatch):
    market_extra = _estimated_etf_market_extra()
    market_extra["macro_indicators"] = {
        "industrial": {
            "current_value": 5.2,
            "previous_value": None,
            "change_rate": None,
            "source_url": "https://example.com/industrial",
            "is_estimated": False,
        }
    }
    market_path, pring_path, output_path = _write_stage4_payloads(
        tmp_path,
        market_extra=market_extra,
        gap_payload={
            "pending_tasks": [
                {"category": "fund_flow", "key": "etf"},
                {"category": "macro_indicators", "key": "industrial"},
            ],
            "manual_required": [],
        },
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_report_generator.py",
            "--market-data",
            str(market_path),
            "--pring-result",
            str(pring_path),
            "--output",
            str(output_path),
            "--allow-fund-flow-downgrade",
        ],
    )

    with pytest.raises(RuntimeError) as exc:
        stage4.main()

    message = str(exc.value)
    assert "macro_indicators.industrial" in message
    assert "missing_compare_values" in message


def test_stage4_rejects_fallback_pring_result_by_default(tmp_path, monkeypatch):
    market_path, pring_path, output_path = _write_stage4_payloads(
        tmp_path,
        market_extra={},
        pring_extra={"fallback_used": True},
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_report_generator.py",
            "--market-data",
            str(market_path),
            "--pring-result",
            str(pring_path),
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(RuntimeError) as exc:
        stage4.main()

    assert "fallback_used=true" in str(exc.value)
