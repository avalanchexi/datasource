def test_audit_flags_bak_and_timestamp(tmp_path, monkeypatch):
    import scripts.tools.run_dir_audit as audit

    d = tmp_path / "data" / "runs" / "20260610"
    d.mkdir(parents=True)
    (d / "market_data.json").write_text("{}", encoding="utf-8")
    (d / "market_data.json.bak").write_text("{}", encoding="utf-8")
    (d / "market_data_20260610085557.json").write_text("{}", encoding="utf-8")

    stray = audit.find_stray_files("2026-06-10", base=tmp_path)

    assert set(stray) == {
        "market_data.json.bak",
        "market_data_20260610085557.json",
    }


def test_audit_clean_dir_returns_empty(tmp_path):
    import scripts.tools.run_dir_audit as audit

    d = tmp_path / "data" / "runs" / "20260610"
    d.mkdir(parents=True)
    (d / "market_data.json").write_text("{}", encoding="utf-8")
    (d / "gap_monitor.json").write_text("{}", encoding="utf-8")

    assert audit.find_stray_files("20260610", base=tmp_path) == []


def test_audit_missing_run_dir_returns_empty(tmp_path):
    import scripts.tools.run_dir_audit as audit

    assert audit.find_stray_files("2026-06-10", base=tmp_path) == []


def test_cli_dirty_default_exits_zero_and_prints_stray(
    tmp_path, monkeypatch, capsys
):
    import scripts.tools.run_dir_audit as audit

    d = tmp_path / "data" / "runs" / "20260610"
    d.mkdir(parents=True)
    (d / "market_data.json.bak").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert audit.main(["--date", "2026-06-10"]) == 0
    assert "STRAY: market_data.json.bak" in capsys.readouterr().out


def test_cli_strict_exits_nonzero_for_stray(tmp_path, monkeypatch, capsys):
    import scripts.tools.run_dir_audit as audit

    d = tmp_path / "data" / "runs" / "20260610"
    d.mkdir(parents=True)
    (d / "market_data.json.bak").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert audit.main(["--date", "2026-06-10", "--strict"]) == 1
    assert "STRAY: market_data.json.bak" in capsys.readouterr().out


def test_cli_invalid_date_uses_argparse_error(capsys):
    import pytest
    import scripts.tools.run_dir_audit as audit

    with pytest.raises(SystemExit) as exc:
        audit.main(["--date", "2026/06/10"])

    assert exc.value.code == 2
    assert "无法解析日期: 2026/06/10" in capsys.readouterr().err
