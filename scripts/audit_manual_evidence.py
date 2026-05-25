#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit manual Stage2.5 JSON evidence URLs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from datasource.utils.manual_evidence_audit import audit_manual_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit manual evidence JSON")
    parser.add_argument("--manual-data", required=True, help="Manual JSON payload path")
    parser.add_argument("--market-data", help="Optional market data JSON path")
    parser.add_argument("--stage2-log", help="Optional Stage2 log JSON path")
    parser.add_argument("--output", required=True, help="Output audit JSON path")
    args = parser.parse_args()

    manual_payload = _read_json(args.manual_data)
    market_payload = _read_optional_json(args.market_data)
    stage2_log = _read_optional_json(args.stage2_log)

    audit = audit_manual_evidence(
        manual_payload,
        market_payload=market_payload,
        stage2_log=stage2_log,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return 1 if audit.get("errors") else 0


def _read_json(path: str) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    return payload if isinstance(payload, dict) else {}


def _read_optional_json(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    return _read_json(path)


if __name__ == "__main__":
    sys.exit(main())
