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


@pytest.mark.parametrize("date_value", ["2026-0610", "202-606-10"])
def test_run_dir_from_date_rejects_malformed_dates(tmp_path, date_value):
    with pytest.raises(ValueError, match="YYYY-MM-DD or YYYYMMDD"):
        run_dir_from_date(date_value, runs_root=tmp_path)


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


def test_daily_run_lock_does_not_unlink_changed_stale_lock(tmp_path, monkeypatch):
    run_dir = tmp_path / "data" / "runs" / "20260610"
    run_dir.mkdir(parents=True)
    lock_path = run_dir / ".run.lock"
    stale_payload = {
        "owner": "old-session",
        "pid": 99999999,
        "hostname": "old-host",
        "created_at": time.time() - 1000,
        "token": "old-token",
    }
    replacement_payload = {
        "owner": "replacement",
        "pid": os.getpid(),
        "hostname": "same-host",
        "created_at": time.time(),
        "token": "replacement-token",
    }
    lock_path.write_text(json.dumps(stale_payload), encoding="utf-8")

    original_read_lock = DailyRunLock._read_lock
    read_count = 0

    def replace_after_first_read(path):
        nonlocal read_count
        payload = original_read_lock(path)
        read_count += 1
        if read_count == 1:
            lock_path.write_text(json.dumps(replacement_payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(DailyRunLock, "_read_lock", staticmethod(replace_after_first_read))

    with pytest.raises(RunLockError) as exc_info:
        with DailyRunLock(run_dir, owner="new-session", stale_after_seconds=1).acquire():
            pass

    assert "replacement" in str(exc_info.value)
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    assert payload["owner"] == "replacement"


def test_daily_run_lock_rejects_fresh_corrupt_lock(tmp_path):
    run_dir = tmp_path / "data" / "runs" / "20260610"
    run_dir.mkdir(parents=True)
    lock_path = run_dir / ".run.lock"
    lock_path.write_text("", encoding="utf-8")

    with pytest.raises(RunLockError, match="corrupt"):
        with DailyRunLock(run_dir, owner="new-session", stale_after_seconds=60).acquire():
            pass

    assert lock_path.exists()


def test_daily_run_lock_removes_stale_corrupt_lock(tmp_path):
    run_dir = tmp_path / "data" / "runs" / "20260610"
    run_dir.mkdir(parents=True)
    lock_path = run_dir / ".run.lock"
    lock_path.write_text("", encoding="utf-8")
    old_timestamp = time.time() - 1000
    os.utime(lock_path, (old_timestamp, old_timestamp))

    with DailyRunLock(run_dir, owner="new-session", stale_after_seconds=1).acquire():
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["owner"] == "new-session"

    assert not lock_path.exists()


def test_daily_run_lock_does_not_unlink_same_text_replaced_corrupt_lock(
    tmp_path, monkeypatch
):
    run_dir = tmp_path / "data" / "runs" / "20260610"
    run_dir.mkdir(parents=True)
    lock_path = run_dir / ".run.lock"
    lock_path.write_text("", encoding="utf-8")
    stale_timestamp = time.time() - 1000
    fresh_timestamp = time.time()
    os.utime(lock_path, (stale_timestamp, stale_timestamp))

    original_read_existing_lock = DailyRunLock._read_existing_lock

    def replace_after_inspection(self, path):
        payload = original_read_existing_lock(self, path)
        lock_path.write_text("", encoding="utf-8")
        os.utime(lock_path, (fresh_timestamp, fresh_timestamp))
        return payload

    monkeypatch.setattr(DailyRunLock, "_read_existing_lock", replace_after_inspection)

    with pytest.raises(RunLockError, match="corrupt"):
        with DailyRunLock(run_dir, owner="new-session", stale_after_seconds=1).acquire():
            pass

    assert lock_path.exists()
    assert lock_path.read_text(encoding="utf-8") == ""
    assert lock_path.stat().st_mtime > stale_timestamp


@pytest.mark.parametrize("payload_text", ["[]", '"x"'])
def test_daily_run_lock_rejects_fresh_schema_invalid_lock(tmp_path, payload_text):
    run_dir = tmp_path / "data" / "runs" / "20260610"
    run_dir.mkdir(parents=True)
    lock_path = run_dir / ".run.lock"
    lock_path.write_text(payload_text, encoding="utf-8")

    with pytest.raises(RunLockError, match="corrupt"):
        with DailyRunLock(run_dir, owner="new-session", stale_after_seconds=60).acquire():
            pass

    assert lock_path.read_text(encoding="utf-8") == payload_text


@pytest.mark.parametrize("payload_text", ["[]", '"x"'])
def test_daily_run_lock_reclaims_stale_schema_invalid_lock(tmp_path, payload_text):
    run_dir = tmp_path / "data" / "runs" / "20260610"
    run_dir.mkdir(parents=True)
    lock_path = run_dir / ".run.lock"
    lock_path.write_text(payload_text, encoding="utf-8")
    old_timestamp = time.time() - 1000
    os.utime(lock_path, (old_timestamp, old_timestamp))

    with DailyRunLock(run_dir, owner="new-session", stale_after_seconds=1).acquire():
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["owner"] == "new-session"

    assert not lock_path.exists()


def test_daily_run_lock_release_ignores_schema_invalid_replacement(tmp_path):
    run_dir = tmp_path / "data" / "runs" / "20260610"
    replacement_payload = "[]"

    with DailyRunLock(run_dir, owner="stage3_pring_analyzer").acquire():
        lock_path = run_dir / ".run.lock"
        lock_path.write_text(replacement_payload, encoding="utf-8")

    assert lock_path.read_text(encoding="utf-8") == replacement_payload
