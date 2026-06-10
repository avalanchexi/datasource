import json
import os
import re
import socket
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Union


class RunLockError(RuntimeError):
    """Raised when a daily run lock is held by another live owner."""


_DASHED_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COMPACT_DATE_RE = re.compile(r"^\d{8}$")
_CORRUPT_LOCK_MARKER = "__corrupt_lock__"
_REQUIRED_LOCK_KEYS = {"owner", "pid", "hostname", "created_at", "token"}


class _CorruptLockPayload(ValueError):
    pass


def run_dir_from_date(date_value: str, runs_root: Path = Path("data/runs")) -> Path:
    return Path(runs_root) / _compact_run_date(date_value)


def _compact_run_date(date_value: str) -> str:
    if _DASHED_DATE_RE.match(date_value):
        compact_date = date_value.replace("-", "")
    elif _COMPACT_DATE_RE.match(date_value):
        compact_date = date_value
    else:
        raise ValueError("date_value must use YYYY-MM-DD or YYYYMMDD")

    try:
        datetime.strptime(compact_date, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("date_value must use YYYY-MM-DD or YYYYMMDD") from exc

    return compact_date


def run_dir_from_artifact(path: Union[os.PathLike, str]) -> Path:
    artifact_path = Path(path)
    parts = artifact_path.parts

    for index in range(len(parts) - 3):
        if parts[index] == "data" and parts[index + 1] == "runs":
            run_date = parts[index + 2]
            has_artifact_name = len(parts) > index + 3
            if has_artifact_name:
                if not _COMPACT_DATE_RE.match(run_date):
                    break
                try:
                    _compact_run_date(run_date)
                except ValueError:
                    break
                return Path(*parts[: index + 3])
            break

    raise ValueError("artifact path must be inside data/runs/YYYYMMDD/<artifact>")


@dataclass
class DailyRunLock:
    run_dir: Union[os.PathLike, str]
    owner: str
    stale_after_seconds: int = 21600
    token: str = field(default_factory=lambda: uuid.uuid4().hex, init=False)
    _acquired: bool = field(default=False, init=False)

    @property
    def lock_path(self) -> Path:
        return Path(self.run_dir) / ".run.lock"

    @contextmanager
    def acquire(self) -> Iterator["DailyRunLock"]:
        self._acquire()
        try:
            yield self
        finally:
            self.release()

    def release(self) -> None:
        lock_path = self.lock_path
        try:
            payload = self._read_lock(lock_path)
        except FileNotFoundError:
            self._acquired = False
            return
        except (json.JSONDecodeError, _CorruptLockPayload, OSError):
            self._acquired = False
            return

        if payload.get("token") != self.token:
            self._acquired = False
            return

        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
        finally:
            self._acquired = False

    def _acquire(self) -> None:
        run_dir = Path(self.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.lock_path

        while True:
            payload = self._build_payload()
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                existing_payload = self._read_existing_lock(lock_path)
                if self._is_corrupt_lock(existing_payload):
                    if self._unlink_if_corrupt_identity_matches(
                        lock_path, existing_payload
                    ):
                        continue
                    continue
                if self._is_stale_or_dead(existing_payload):
                    if self._unlink_if_payload_matches(lock_path, existing_payload):
                        continue
                    continue
                raise self._lock_error(existing_payload)

            with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
                json.dump(payload, lock_file, ensure_ascii=False)
            self._acquired = True
            return

    def _build_payload(self) -> Dict[str, Any]:
        return {
            "owner": self.owner,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "created_at": time.time(),
            "token": self.token,
        }

    def _read_existing_lock(self, lock_path: Path) -> Dict[str, Any]:
        try:
            return self._read_lock(lock_path)
        except FileNotFoundError:
            return {
                "owner": "<released>",
                "pid": None,
                "hostname": None,
                "created_at": 0,
                "token": None,
            }
        except (json.JSONDecodeError, _CorruptLockPayload) as exc:
            try:
                raw_text = lock_path.read_text(encoding="utf-8")
                mtime = lock_path.stat().st_mtime
            except FileNotFoundError:
                return {
                    "owner": "<released>",
                    "pid": None,
                    "hostname": None,
                    "created_at": 0,
                    "token": None,
                }
            except OSError as os_exc:
                raise RunLockError(
                    f"{self.owner} cannot inspect corrupt run lock: {os_exc}"
                ) from os_exc

            if time.time() - mtime > self.stale_after_seconds:
                return {
                    "owner": "<corrupt>",
                    "pid": None,
                    "hostname": None,
                    "created_at": mtime,
                    "token": None,
                    _CORRUPT_LOCK_MARKER: True,
                    "raw_text": raw_text,
                    "mtime": mtime,
                }
            raise RunLockError(
                f"{self.owner} cannot acquire run lock; corrupt existing run lock is fresh: {exc}"
            ) from exc
        except OSError as exc:
            raise RunLockError(f"{self.owner} cannot read existing run lock: {exc}") from exc

    @staticmethod
    def _read_lock(lock_path: Path) -> Dict[str, Any]:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise _CorruptLockPayload("run lock payload must be a JSON object")
        if not _REQUIRED_LOCK_KEYS.issubset(payload):
            raise _CorruptLockPayload("run lock payload is missing required fields")
        return payload

    @staticmethod
    def _is_corrupt_lock(payload: Dict[str, Any]) -> bool:
        return bool(payload.get(_CORRUPT_LOCK_MARKER))

    def _unlink_if_payload_matches(
        self, lock_path: Path, expected: Dict[str, Any]
    ) -> bool:
        try:
            current = self._read_lock(lock_path)
        except (FileNotFoundError, json.JSONDecodeError, _CorruptLockPayload, OSError):
            return False
        if current != expected:
            return False
        try:
            lock_path.unlink()
        except FileNotFoundError:
            return False
        return True

    @staticmethod
    def _unlink_if_corrupt_identity_matches(
        lock_path: Path, expected: Dict[str, Any]
    ) -> bool:
        try:
            current_text = lock_path.read_text(encoding="utf-8")
            current_mtime = lock_path.stat().st_mtime
        except (FileNotFoundError, OSError):
            return False
        if current_text != expected.get("raw_text"):
            return False
        if current_mtime != expected.get("mtime"):
            return False
        try:
            lock_path.unlink()
        except FileNotFoundError:
            return False
        return True

    def _is_stale_or_dead(self, payload: Dict[str, Any]) -> bool:
        hostname = payload.get("hostname")
        pid = self._as_int(payload.get("pid"))
        if hostname == socket.gethostname():
            if pid is None or pid <= 0:
                return False
            return not self._pid_is_alive(pid)

        created_at = self._as_float(payload.get("created_at"))
        return (
            created_at is not None
            and time.time() - created_at > self.stale_after_seconds
        )

    def _lock_error(self, payload: Dict[str, Any]) -> RunLockError:
        existing_owner = payload.get("owner", "<unknown>")
        existing_pid = payload.get("pid", "<unknown>")
        return RunLockError(
            f"{self.owner} cannot acquire run lock; existing owner "
            f"{existing_owner} is live (pid={existing_pid})"
        )

    @staticmethod
    def _pid_is_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _as_float(value: object) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_int(value: object) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
