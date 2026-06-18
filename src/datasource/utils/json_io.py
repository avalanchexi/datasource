"""JSON IO helpers with strict and diagnostic read modes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


def load_json_strict(path: Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as fp:
        return json.load(fp)


def load_json_optional(path: Path) -> Optional[Any]:
    target = Path(path)
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def atomic_write_json(payload: Any, path: Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, target)


def atomic_write_text(text: str, path: Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def dump_json(payload: Any, path: Path) -> None:
    atomic_write_json(payload, path)
