#!/usr/bin/env python3
"""
Archived background scan report generator.

Current reports must be generated through the Stage1 -> Stage2 -> Stage2.5 ->
Stage3 -> Stage4 pipeline documented in AGENTS.md. This legacy entry point is
kept only to fail old direct invocations and to support explicit archive-path
smoke checks.
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_DIR = PROJECT_ROOT / "reports" / "archive"


def _is_under_archive(path: Path) -> bool:
    try:
        archive_root = str(ARCHIVE_DIR.resolve())
        candidate = str(path.resolve())
        return os.path.commonpath([archive_root, candidate]) == archive_root
    except (FileNotFoundError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Archived background scan report generator")
    parser.add_argument(
        "--run-archived",
        action="store_true",
        help="Run this archived smoke helper explicitly.",
    )
    parser.add_argument(
        "--output",
        default=str(ARCHIVE_DIR / "20250910_background_scan_archived.md"),
        help="Output path. Must be under reports/archive/.",
    )
    args = parser.parse_args()

    if not args.run_archived:
        print(
            "[ARCHIVED] scripts/utility/generate_background_scan.py is disabled. "
            "Use AGENTS.md Stage1 -> Stage2 -> Stage2.5 -> Stage3 -> Stage4.",
            file=sys.stderr,
        )
        return 2

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    if not _is_under_archive(output_path):
        print("[ARCHIVED] output must be under reports/archive/.", file=sys.stderr)
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(
            [
                "# Archived Background Scan Entry Point",
                "",
                f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
                "",
                "This legacy utility no longer runs the active report pipeline.",
                "Use the Stage1 -> Stage2 -> Stage2.5 -> Stage3 -> Stage4 flow.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"[ARCHIVED] wrote archive smoke output: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
