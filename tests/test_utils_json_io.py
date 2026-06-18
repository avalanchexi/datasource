import inspect
from pathlib import Path

import pytest

from datasource.utils.json_io import (
    atomic_write_text,
    dump_json,
    load_json_optional,
    load_json_strict,
)


def test_load_json_strict_reads_dict(tmp_path):
    path = tmp_path / "payload.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    assert load_json_strict(path) == {"a": 1}


def test_load_json_strict_fails_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_json_strict(tmp_path / "missing.json")


def test_load_json_optional_returns_none_for_missing_or_invalid(tmp_path):
    assert load_json_optional(tmp_path / "missing.json") is None
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{bad", encoding="utf-8")
    assert load_json_optional(invalid) is None


def test_load_json_optional_propagates_non_optional_io_errors(
    tmp_path, monkeypatch
):
    def fake_exists(self):
        return False

    def fake_read_text(self, encoding):
        raise OSError("read failed")

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "read_text", fake_read_text)

    with pytest.raises(OSError):
        load_json_optional(tmp_path / "payload.json")


def test_atomic_write_json_writes_and_no_bak(tmp_path):
    from datasource.utils.json_io import atomic_write_json, load_json_strict

    p = tmp_path / "x.json"
    atomic_write_json({"a": 1}, p)
    atomic_write_json({"a": 2}, p)

    assert load_json_strict(p) == {"a": 2}
    assert not (p.with_name(p.name + ".bak")).exists()
    assert not list(tmp_path.glob("*.tmp"))
    assert sorted(q.name for q in tmp_path.iterdir()) == ["x.json"]


def test_dump_json_delegates_to_atomic_write_json_without_bak(tmp_path):
    path = tmp_path / "payload.json"
    dump_json({"a": 1}, path)
    dump_json({"a": 2}, path)

    assert load_json_strict(path) == {"a": 2}
    assert not (path.with_name(path.name + ".bak")).exists()
    assert not list(tmp_path.glob("*.tmp"))
    assert sorted(q.name for q in tmp_path.iterdir()) == ["payload.json"]


def test_dump_json_has_no_backup_parameter(tmp_path):
    assert "backup" not in inspect.signature(dump_json).parameters

    with pytest.raises(TypeError):
        dump_json({"a": 1}, tmp_path / "payload.json", backup=True)


def test_atomic_write_text_writes_replaces_and_leaves_no_tmp(tmp_path):
    path = tmp_path / "message.txt"
    atomic_write_text("first", path)
    atomic_write_text("second", path)

    assert path.read_text(encoding="utf-8") == "second"
    assert not list(tmp_path.glob("*.tmp"))
    assert sorted(q.name for q in tmp_path.iterdir()) == ["message.txt"]
