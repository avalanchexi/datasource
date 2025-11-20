"""Fetch latest CSI index constituents and money flow data via TuShare."""

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from datasource.adapters.tushare_adapter import TuShareAdapter, TuShareConfig


LOGGER = logging.getLogger("csi_indices")


@dataclass
class IndexInfo:
    name: str
    ts_code: str


INDEXES: Tuple[IndexInfo, ...] = (
    IndexInfo(name="沪深300", ts_code="000300.SH"),
    IndexInfo(name="中证500", ts_code="000905.SH"),
    IndexInfo(name="中证1000", ts_code="000852.SH"),
)


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(asctime)s] %(levelname)s: %(message)s")


def ensure_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)


def normalize_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = value.replace("-", "")
    if len(digits) != 8 or not digits.isdigit():
        raise ValueError(f"Invalid date value: {value}. Expected YYYYMMDD.")
    return digits


def parse_args() -> argparse.Namespace:
    today = datetime.now().strftime("%Y%m%d")
    default_start = datetime.now().replace(month=1, day=1).strftime("%Y%m%d")

    parser = argparse.ArgumentParser(
        description="Fetch CSI index constituents and moneyflow using TuShare",
    )
    parser.add_argument("--start-date", default=default_start, help="Start date for fund flow in YYYYMMDD")
    parser.add_argument("--end-date", default=today, help="End date for fund flow in YYYYMMDD")
    parser.add_argument(
        "--trade-date",
        default=None,
        help="Specific trade date for index weights (YYYYMMDD). Defaults to end date if omitted.",
    )
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="Output directory for generated CSV files",
    )
    parser.add_argument(
        "--prefix",
        default="csi_index",
        help="File name prefix for generated CSV files",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args()


async def fetch_constituents(
    adapter: TuShareAdapter,
    index_info: IndexInfo,
    weight_date: str,
) -> Optional[pd.DataFrame]:
    response = await adapter.get_index_weight(index_info.ts_code, trade_date=weight_date)
    data = response.data

    if data is not None and not data.empty:
        frame = data.copy()
        frame["index_name"] = index_info.name
        frame["ts_code"] = index_info.ts_code
        return frame

    LOGGER.debug("index_weight empty for %s %s, falling back to index_member", index_info.name, weight_date)

    fallback = await adapter.get_index_members(index_info.ts_code, is_new="Y")
    members = fallback.data
    if members is None or members.empty:
        LOGGER.warning("Failed to fetch index members for %s: %s", index_info.name, fallback.error)
        return None

    frame = members.copy()
    frame["index_name"] = index_info.name
    frame["ts_code"] = index_info.ts_code
    return frame


async def fetch_moneyflow(
    adapter: TuShareAdapter,
    index_info: IndexInfo,
    start_date: Optional[str],
    end_date: Optional[str],
) -> Optional[pd.DataFrame]:
    response = await adapter.get_index_moneyflow(index_info.ts_code, start_date=start_date, end_date=end_date)
    if response.data is None or response.data.empty:
        LOGGER.warning("No moneyflow data for %s: %s", index_info.name, response.error)
        return None

    frame = response.data.copy()
    frame["index_name"] = index_info.name
    frame["ts_code"] = index_info.ts_code
    return frame


async def run(args: argparse.Namespace) -> Dict[str, Path]:
    start_date = normalize_date(args.start_date)
    end_date = normalize_date(args.end_date)
    weight_date = normalize_date(args.trade_date) if args.trade_date else end_date or datetime.now().strftime("%Y%m%d")

    ensure_output_dir(Path(args.output_dir))

    adapter = TuShareAdapter(TuShareConfig())
    available = await adapter.is_available()
    if not available:
        LOGGER.warning("TuShare availability check failed. Continuing to attempt requests.")

    constituents: List[pd.DataFrame] = []
    moneyflows: List[pd.DataFrame] = []

    for index_info in INDEXES:
        LOGGER.info("Fetching %s constituents", index_info.name)
        constituents_frame = await fetch_constituents(adapter, index_info, weight_date)
        if constituents_frame is not None:
            constituents.append(constituents_frame)

        LOGGER.info("Fetching %s moneyflow", index_info.name)
        moneyflow_frame = await fetch_moneyflow(adapter, index_info, start_date, end_date)
        if moneyflow_frame is not None:
            moneyflows.append(moneyflow_frame)

    outputs: Dict[str, Path] = {}

    if constituents:
        combined_constituents = pd.concat(constituents, ignore_index=True)
        constituents_path = Path(args.output_dir) / f"{args.prefix}_constituents_{weight_date}.csv"
        combined_constituents.to_csv(constituents_path, index=False)
        outputs["constituents"] = constituents_path
        LOGGER.info("Saved constituents to %s", constituents_path)
    else:
        LOGGER.warning("No constituent data collected. Check TuShare response or token configuration.")

    if moneyflows:
        combined_moneyflow = pd.concat(moneyflows, ignore_index=True)
        moneyflow_path = Path(args.output_dir) / f"{args.prefix}_moneyflow_{start_date or 'NA'}_{end_date or 'NA'}.csv"
        combined_moneyflow.to_csv(moneyflow_path, index=False)
        outputs["moneyflow"] = moneyflow_path
        LOGGER.info("Saved moneyflow to %s", moneyflow_path)
    else:
        LOGGER.warning("No money flow data collected. Check TuShare response or date window.")

    return outputs


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)

    try:
        outputs = asyncio.run(run(args))
    except Exception as exc:  # pragma: no cover - CLI runtime
        LOGGER.error("Execution failed: %s", exc)
        raise SystemExit(1) from exc

    if not outputs:
        LOGGER.warning("Script finished without generating any files.")


if __name__ == "__main__":  # pragma: no cover - script entry
    main()
