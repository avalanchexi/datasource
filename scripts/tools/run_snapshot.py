#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture run snapshot for auditability."""
from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime
from pathlib import Path

from datasource.utils.json_io import atomic_write_json


def _run_cmd(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
    except Exception:
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture run snapshot")
    parser.add_argument("--output", required=True, help="Output snapshot path")
    parser.add_argument("--args", help="CLI args string")
    args = parser.parse_args()

    snapshot = {
        "generated_at": datetime.now().isoformat(),
        "cli_args": args.args or "",
        "env": {
            "PYTHONPATH": os.getenv("PYTHONPATH"),
        },
        "git": {
            "rev": _run_cmd(["git", "rev-parse", "HEAD"]),
            "status": _run_cmd(["git", "status", "--porcelain"]),
        },
    }

    output_path = Path(args.output)
    atomic_write_json(snapshot, output_path)

    print(f"[OK] run snapshot saved: {output_path}")


if __name__ == "__main__":
    main()
