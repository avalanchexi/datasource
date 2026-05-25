#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Write the pipeline rule inventory JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datasource.utils.pipeline_audit import build_rule_inventory


def main() -> None:
    parser = argparse.ArgumentParser(description="Write pipeline rule inventory JSON")
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(build_rule_inventory(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
