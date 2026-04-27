import json
from datetime import datetime
from pathlib import Path

import pytest

import scripts.fix_estimated_verified as fixer


def test_fix_estimated_verified_updates_all_layers(tmp_path: Path, monkeypatch):
    today = datetime.now().strftime("%Y-%m-%d")
    market_path = tmp_path / "market.json"
    gap_path = tmp_path / "gap.json"
    policy_path = tmp_path / "policy.json"

    market_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "date": "2026-03-05",
                    "missing_items": {"macro_indicators": [{"key": "bdi", "reason": "estimated_not_allowed"}]},
                },
                "missing_items": ["bdi"],
                "macro_indicators": {
                    "bdi": {
                        "current_value": 2233.0,
                        "unit": "points",
                        "date": today,
                        "source_url": "https://www.tradingeconomics.com/commodity/baltic",
                        "is_estimated": True,
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    gap_path.write_text(
        json.dumps({"manual_required": ["bdi", "USDCNY"], "pending_tasks": ["bdi"]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    policy_path.write_text(
        json.dumps(
            {
                "block_stage3": True,
                "redlist": [{"key": "bdi", "category": "macro_indicators"}],
                "stale_redlist": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fix_estimated_verified.py",
            "--market-data",
            str(market_path),
            "--key",
            "bdi",
            "--gap-monitor",
            str(gap_path),
            "--policy-path",
            str(policy_path),
        ],
    )
    rc = fixer.main()
    assert rc == 0

    fixed_market = json.loads(market_path.read_text(encoding="utf-8"))
    assert fixed_market["macro_indicators"]["bdi"]["is_estimated"] is False
    assert fixed_market["missing_items"] == []
    assert fixed_market["metadata"]["missing_items"] == {}

    fixed_gap = json.loads(gap_path.read_text(encoding="utf-8"))
    assert "bdi" not in (fixed_gap.get("manual_required") or [])
    assert "bdi" not in (fixed_gap.get("pending_tasks") or [])

    fixed_policy = json.loads(policy_path.read_text(encoding="utf-8"))
    assert fixed_policy.get("redlist") == []
    assert fixed_policy.get("block_stage3") is False


def test_fix_estimated_verified_blocks_untrusted_bdi(tmp_path: Path, monkeypatch):
    market_path = tmp_path / "market.json"
    market_path.write_text(
        json.dumps(
            {
                "metadata": {"date": "2026-03-05", "missing_items": {}},
                "missing_items": ["bdi"],
                "macro_indicators": {
                    "bdi": {
                        "current_value": 2233.0,
                        "unit": "points",
                        "date": "2026-03-05",
                        "source_url": "https://example.com/bdi",
                        "is_estimated": True,
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["fix_estimated_verified.py", "--market-data", str(market_path), "--key", "bdi"])
    with pytest.raises(RuntimeError):
        fixer.main()
