#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit per-run data directories for files outside the run-path contract."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from datasource.utils.run_paths import build_run_paths


def find_stray_files(date: str, base: Path | str = Path(".")) -> list[str]:
    """Return sorted data/run entries that are not in RunPaths whitelist."""

    run_paths = build_run_paths(date)
    run_dir = Path(base) / run_paths.data_dir
    if not run_dir.exists():
        return []

    allowed = run_paths.data_dir_whitelist()
    return sorted(entry.name for entry in run_dir.iterdir() if entry.name not in allowed)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit data/runs/YYYYMMDD for files outside RunPaths whitelist."
    )
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Run date, accepts YYYY-MM-DD or YYYYMMDD. Defaults to today.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero when stray files are found.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        run_paths = build_run_paths(args.date)
    except ValueError as exc:
        parser.error(str(exc))

    run_dir = run_paths.data_dir
    stray = find_stray_files(args.date)

    if stray:
        for name in stray:
            print(f"STRAY: {name}")
        return 1 if args.strict else 0

    file_count = sum(1 for _ in run_dir.iterdir()) if run_dir.exists() else 0
    print(f"OK: {file_count} files, all whitelisted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
