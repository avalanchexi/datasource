#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Archived direct fund-flow updater.

Fund-flow supplements must now be written to Stage2.5 manual/WebSearch JSON and
applied through scripts/stage2_5_injector.py. This legacy command remains only
to fail old direct-write invocations loudly.
"""

import argparse
import sys


DEPRECATION_MESSAGE = (
    "manual_fund_flow_updater.py direct writes are disabled. "
    "Write websearch_results_manual.json and run scripts/stage2_5_injector.py."
)


def update_fund_flow(
    market_data_path: str,
    flow_type: str,
    recent_5d: str,
    total_120d: str,
    trend: str,
    source: str,
    note: str = "",
    *,
    infer_trend: bool = True,
) -> None:
    """Deprecated direct updater; use Stage2.5 manual JSON injection instead."""
    raise RuntimeError(DEPRECATION_MESSAGE)


def main() -> int:
    parser = argparse.ArgumentParser(description="Archived direct fund-flow updater")
    parser.add_argument("--market-data", required=True, help="market_data.json path")
    parser.add_argument(
        "--flow-type",
        required=True,
        choices=["northbound", "southbound", "etf", "margin"],
        help="fund-flow type",
    )
    parser.add_argument("--recent-5d", required=True, help="legacy argument; ignored")
    parser.add_argument("--total-120d", required=True, help="legacy argument; ignored")
    parser.add_argument("--trend", default="", help="legacy argument; ignored")
    parser.add_argument(
        "--source",
        default="Stage2.5 manual_required",
        help="legacy argument; ignored",
    )
    parser.add_argument("--note", default="", help="legacy argument; ignored")
    parser.add_argument(
        "--trend-mode",
        choices=["auto", "manual"],
        default="auto",
        help="legacy argument; ignored",
    )
    parser.parse_args()

    print(
        "[ARCHIVED] scripts/utility/manual_fund_flow_updater.py is disabled: "
        "direct market_data.json writes are prohibited. Use "
        "websearch_results_manual.json plus scripts/stage2_5_injector.py.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
