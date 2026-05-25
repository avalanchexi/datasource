#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit Stage3/Stage4 pipeline gate consistency."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from datasource.utils.pipeline_audit import build_pipeline_audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit pipeline gate consistency")
    parser.add_argument("--market-data", required=True, help="market_data JSON path")
    parser.add_argument("--pring-result", help="pring_result JSON path")
    parser.add_argument("--gap-monitor", help="gap_monitor JSON path")
    parser.add_argument(
        "--skip-fund-flow-check",
        action="store_true",
        help="Skip skippable fund_flow quality and gap blockers",
    )
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()

    audit = build_pipeline_audit(
        _load_required_json(Path(args.market_data)),
        pring_payload=_load_optional_json(args.pring_result),
        gap_payload=_load_optional_json(args.gap_monitor),
        skip_fund_flow_check=args.skip_fund_flow_check,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    if audit["errors"]:
        sys.exit(1)


def _load_required_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _load_optional_json(path_value: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path_value:
        return None
    return _load_required_json(Path(path_value))


if __name__ == "__main__":
    main()
