#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run snapshot writer for auditability."""
from __future__ import annotations

import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from datasource.utils.json_io import atomic_write_json


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

    atomic_write_json(snapshot, output_path)
