import json
import os
import time

import pytest

from datasource.utils.run_lock import (
    DailyRunLock,
    RunLockError,
    run_dir_from_artifact,
    run_dir_from_date,
)


def test_run_dir_from_date_accepts_dashed_and_compact_dates(tmp_path):
    assert run_dir_from_date("2026-06-10", runs_root=tmp_path) == tmp_path / "20260610"
    assert run_dir_from_date("20260610", runs_root=tmp_path) == tmp_path / "20260610"


def test_run_dir_from_artifact_uses_data_runs_parent(tmp_path):
    artifact = tmp_path / "data" / "runs" / "20260610" / "market_data_complete.json"
    assert run_dir_from_artifact(artifact) == artifact.parent


def test_run_dir_from_artifact_rejects_non_run_paths(tmp_path):
    artifact = tmp_path / "reports" / "2026-06-10-背景扫描120.md"
    with pytest.raises(ValueError, match="data/runs/YYYYMMDD"):
        run_dir_from_artifact(artifact)


def test_daily_run_lock_rejects_second_live_owner(tmp_path):
    run_dir = tmp_path / "data" / "runs" / "20260610"
    with DailyRunLock(run_dir, owner="stage2_5_injector").acquire():
        with pytest.raises(RunLockError) as exc_info:
            with DailyRunLock(run_dir, owner="stage4_report_generator").acquire():
                pass

    assert "stage2_5_injector" in str(exc_info.value)
    assert "stage4_report_generator" in str(exc_info.value)


def test_daily_run_lock_removes_stale_dead_pid_lock(tmp_path):
    run_dir = tmp_path / "data" / "runs" / "20260610"
    run_dir.mkdir(parents=True)
    lock_path = run_dir / ".run.lock"
    lock_path.write_text(
        json.dumps(
            {
                "owner": "old-session",
                "pid": 99999999,
                "hostname": "old-host",
                "created_at": time.time() - 1000,
                "token": "old-token",
            }
        ),
        encoding="utf-8",
    )

    with DailyRunLock(run_dir, owner="new-session", stale_after_seconds=1).acquire():
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["owner"] == "new-session"
        assert payload["pid"] == os.getpid()

    assert not lock_path.exists()


def test_daily_run_lock_does_not_remove_replaced_lock(tmp_path):
    run_dir = tmp_path / "data" / "runs" / "20260610"
    with DailyRunLock(run_dir, owner="stage3_pring_analyzer").acquire():
        lock_path = run_dir / ".run.lock"
        lock_path.write_text(
            json.dumps(
                {
                    "owner": "replacement",
                    "pid": os.getpid(),
                    "hostname": "same-host",
                    "created_at": time.time(),
                    "token": "replacement-token",
                }
            ),
            encoding="utf-8",
        )

    payload = json.loads((run_dir / ".run.lock").read_text(encoding="utf-8"))
    assert payload["owner"] == "replacement"
