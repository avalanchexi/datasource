import json

import pytest

from datasource.utils.json_io import dump_json, load_json_optional, load_json_strict


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


def test_dump_json_creates_parent_and_backup(tmp_path):
    path = tmp_path / "nested" / "payload.json"
    dump_json({"a": 1}, path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
    dump_json({"a": 2}, path, backup=True)
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2}
    assert (path.with_name(path.name + ".bak")).exists()
