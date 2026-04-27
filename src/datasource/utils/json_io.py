"""JSON IO helpers with strict and diagnostic read modes."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
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


def dump_json(payload: Any, path: Path, backup: bool = False) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup and target.exists():
        backup_path = target.with_name(target.name + ".bak")
        timestamp_path = target.with_name(f"{target.stem}_{datetime.now():%Y%m%d%H%M%S%f}{target.suffix}")
        shutil.copy2(target, backup_path)
        shutil.copy2(target, timestamp_path)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
