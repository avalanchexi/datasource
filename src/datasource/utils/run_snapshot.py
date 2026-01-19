#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run snapshot writer for auditability."""
from __future__ import annotations

import json
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any


def _run_cmd(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
    except Exception:
        return ""


def write_run_snapshot(output_path: Path, cli_args: str) -> None:
    snapshot: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "cli_args": cli_args,
        "python": platform.python_version(),
        "env": {
            "PYTHONPATH": os.getenv("PYTHONPATH"),
        },
        "git": {
            "rev": _run_cmd(["git", "rev-parse", "HEAD"]),
            "status": _run_cmd(["git", "status", "--porcelain"]),
        },
    }

    req_path = Path("requirements.txt")
    if req_path.exists():
        snapshot["requirements"] = req_path.read_text(encoding="utf-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
