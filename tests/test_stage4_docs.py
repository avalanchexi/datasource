from pathlib import Path

import pytest

import scripts.stage4_report_generator as stage4


def test_claude_stage4_command_uses_named_args():
    text = Path("CLAUDE.md").read_text(encoding="utf-8")
    assert "scripts/stage4_report_generator.py" in text
    assert "--market-data" in text
    assert "--pring-result" in text
    assert "--output" in text
    assert "兼容入口：tests/scripts/generate_simple_report_test.py" in text


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

    assert "data/runs/20260409/gap_monitor.json" in str(exc.value)
