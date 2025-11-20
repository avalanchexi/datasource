"""Yahoo Finance data fetching utilities - V2.0待MCP替代
⚠️ DEPRECATED: 此模块将被MCP工具(WebFetch)替代
📍 替代模块: src.datasource.utils.mcp_tools.MCPDataFetcher
🔧 迁移方式: 使用 webfetch_yahoo_finance() 替代此模块所有功能
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Optional
import json
import pandas as pd

try:
    from urllib.request import Request, urlopen
except ImportError:  # pragma: no cover - urllib is part of stdlib
    Request = None
    urlopen = None


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


YAHOO_SYMBOL_MAP: Dict[str, str] = {
    # A股指数
    "000001": "000001.SS",
    "000016": "000016.SS",
    "000300": "000300.SS",
    "399001": "399001.SZ",
    "399006": "399006.SZ",
    "000905": "000905.SS",
    "000688": "000688.SS",

    # 商品基准 (期货/ETF)
    "510300": "510300.SS",
    "CL": "CL=F",           # WTI原油主力
    "OIL": "BZ=F",          # Brent原油主力
    "HG": "HG=F",           # COMEX铜
    "XAU": "XAUUSD=X",      # 现货黄金
    "GSG": "GSG",           # BCOM代理ETF

    # 债券ETF
    "511010": "511010.SS",  # 5年期国债ETF
    "019649": "019649.SS",  # 十年期国债
    "019950": "019950.SS",  # 国开债

    # 汇率数据 - 120背景扫描方案完整覆盖
    "DXY": "DX-Y.NYB",           # 美元指数DXY外汇数据
    "USDCNY": "USDCNY=X",        # USD/CNY在岸SAFE数据
    "USDCNH": "USDCNH=X",        # USD/CNH离岸CFETS数据
    "EURUSD": "EURUSD=X",        # EUR/USD
    "GBPUSD": "GBPUSD=X",        # GBP/USD
    "USDJPY": "USDJPY=X",        # USD/JPY
    "AUDUSD": "AUDUSD=X",        # AUD/USD

    # 国债收益率数据
    "US10Y": "^TNX",             # US10Y国债收益率FRED数据
    "^TNX": "^TNX",              # 美国10年期国债收益率
    "CN10Y": "511010.SS",        # 中国10年期代理（国债ETF）
    "CN10Y_CDB": "019950.SS",    # 中国国开债代理

    # 直接映射（已存在的符号）
    "USD/CNY": "USDCNY=X",
    "USD/CNH": "USDCNH=X",
    "DX-Y.NYB": "DX-Y.NYB",
    "USDCNY=X": "USDCNY=X",
    "USDCNH=X": "USDCNH=X",
    "^GSPC": "^GSPC",
    "^IXIC": "^IXIC",
}


# 国际金融数据特殊处理映射
INTERNATIONAL_FINANCE_SYMBOLS = {
    "forex": {
        "DXY": {"yahoo": "DX-Y.NYB", "type": "index", "description": "美元指数DXY外汇数据"},
        "USDCNY": {"yahoo": "USDCNY=X", "type": "forex", "description": "USD/CNY在岸SAFE数据"},
        "USDCNH": {"yahoo": "USDCNH=X", "type": "forex", "description": "USD/CNH离岸CFETS数据"},
        "EURUSD": {"yahoo": "EURUSD=X", "type": "forex", "description": "EUR/USD外汇数据"},
        "GBPUSD": {"yahoo": "GBPUSD=X", "type": "forex", "description": "GBP/USD外汇数据"},
        "USDJPY": {"yahoo": "USDJPY=X", "type": "forex", "description": "USD/JPY外汇数据"},
    },
    "bond_yields": {
        "US10Y": {"yahoo": "^TNX", "type": "yield", "description": "US10Y国债收益率FRED数据"},
        "CN10Y": {"proxy_etf": "511010.SS", "type": "yield_proxy", "description": "CN10Y国债收益率中债估值"},
        "CN10Y_CDB": {"proxy_etf": "019950.SS", "type": "yield_proxy", "description": "CN10Y国开债收益率中债AAA代理"},
    }
}


def _resolve_symbol(symbol: str) -> Optional[str]:
    """Translate internal symbols to Yahoo symbols."""

    if not symbol:
        return None

    if symbol in YAHOO_SYMBOL_MAP:
        return YAHOO_SYMBOL_MAP[symbol]

    # Already looks like a Yahoo ticker (contains suffix or FX pattern)
    lowered = symbol.lower()
    if any(x in lowered for x in ["=x", ".ss", ".sz", ".hk", ".nyb", ".us"]):
        return symbol

    return None


def fetch_price_history(
    symbol: str, start_date: str, end_date: str, *, buffer_days: int = 0
) -> Optional[pd.DataFrame]:
    """
    ⚠️ DEPRECATED - 将被MCP WebFetch替代

    V2.0迁移说明:
    from datasource.utils.mcp_tools import mcp_fetcher
    data = await mcp_fetcher.webfetch_yahoo_finance(symbol, start_date, end_date)

    Fetch historical price data from Yahoo Finance as a fallback.

    Args:
        symbol: Internal symbol (e.g. "000300") or direct Yahoo symbol.
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        buffer_days: Extra days added before ``start_date`` to enlarge history.

    Returns:
        Pandas DataFrame with columns ``date`` (datetime), ``close``, ``open``,
        ``high``, ``low`` and ``volume``. ``None`` when data is unavailable.
    """

    if Request is None or urlopen is None:
        return None

    resolved = _resolve_symbol(symbol)
    if resolved is None:
        return None

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        if buffer_days:
            start_dt = start_dt - timedelta(days=buffer_days)
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)

        period1 = int(start_dt.timestamp())
        period2 = int(end_dt.timestamp())

        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{resolved}"
            f"?period1={period1}&period2={period2}&interval=1d&includePrePost=false"
        )

        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        chart = payload.get("chart", {})
        results = chart.get("result")
        if not results:
            return None

        result = results[0]
        timestamps = result.get("timestamp")
        indicators = result.get("indicators", {})
        quotes = (indicators.get("quote") or [{}])[0]
        adjclose = (indicators.get("adjclose") or [{}])[0]

        if not timestamps or "close" not in quotes:
            return None

        closes = quotes.get("close")
        opens = quotes.get("open") or adjclose.get("adjclose")
        highs = quotes.get("high")
        lows = quotes.get("low")
        volumes = quotes.get("volume")

        dates = pd.to_datetime(timestamps, unit="s", utc=True)
        dates = dates.tz_convert("Asia/Shanghai").tz_localize(None)

        df = pd.DataFrame(
            {
                "date": dates,
                "close": closes,
                "open": opens,
                "high": highs,
                "low": lows,
                "volume": volumes,
            }
        )

        df = df.dropna(subset=["close"])
        if df.empty:
            return None

        df = df.sort_values("date")
        return df

    except Exception:
        return None


def get_international_finance_data(
    symbol: str,
    start_date: str,
    end_date: str,
    data_type: str = "auto"
) -> Optional[Dict[str, Any]]:
    """获取国际金融数据（汇率、国债收益率）

    Args:
        symbol: 内部符号代码
        start_date: 开始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        data_type: 数据类型 ("forex", "bond_yield", "auto")

    Returns:
        包含数据和元信息的字典，失败时返回None
    """
    try:
        # 自动检测数据类型
        if data_type == "auto":
            if symbol in INTERNATIONAL_FINANCE_SYMBOLS["forex"]:
                data_type = "forex"
            elif symbol in INTERNATIONAL_FINANCE_SYMBOLS["bond_yields"]:
                data_type = "bond_yield"
            else:
                # 尝试直接映射
                resolved = _resolve_symbol(symbol)
                if resolved:
                    data = fetch_price_history(symbol, start_date, end_date)
                    if data is not None:
                        return {
                            "data": data,
                            "symbol": symbol,
                            "yahoo_symbol": resolved,
                            "data_type": "unknown",
                            "source": "yahoo_finance"
                        }
                return None

        # 获取汇率数据
        if data_type == "forex":
            forex_config = INTERNATIONAL_FINANCE_SYMBOLS["forex"].get(symbol)
            if not forex_config:
                return None

            yahoo_symbol = forex_config["yahoo"]
            data = fetch_price_history(yahoo_symbol, start_date, end_date)
            if data is not None:
                return {
                    "data": data,
                    "symbol": symbol,
                    "yahoo_symbol": yahoo_symbol,
                    "data_type": "forex",
                    "description": forex_config["description"],
                    "source": "yahoo_finance"
                }

        # 获取国债收益率数据
        elif data_type == "bond_yield":
            bond_config = INTERNATIONAL_FINANCE_SYMBOLS["bond_yields"].get(symbol)
            if not bond_config:
                return None

            # 直接收益率数据
            if "yahoo" in bond_config:
                yahoo_symbol = bond_config["yahoo"]
                data = fetch_price_history(yahoo_symbol, start_date, end_date)
                if data is not None:
                    return {
                        "data": data,
                        "symbol": symbol,
                        "yahoo_symbol": yahoo_symbol,
                        "data_type": "bond_yield",
                        "description": bond_config["description"],
                        "source": "yahoo_finance"
                    }

            # 债券ETF代理数据
            elif "proxy_etf" in bond_config:
                proxy_symbol = bond_config["proxy_etf"]
                data = fetch_price_history(proxy_symbol, start_date, end_date)
                if data is not None:
                    return {
                        "data": data,
                        "symbol": symbol,
                        "proxy_etf": proxy_symbol,
                        "data_type": "bond_yield_proxy",
                        "description": bond_config["description"],
                        "source": "yahoo_finance",
                        "note": "需要转换ETF价格为收益率数据"
                    }

        return None

    except Exception:
        return None


def batch_get_background_scan_forex(start_date: str, end_date: str) -> Dict[str, Any]:
    """批量获取120背景扫描需要的汇率数据

    Args:
        start_date: 开始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD

    Returns:
        包含所有汇率数据的字典
    """
    required_forex = ["DXY", "USDCNY", "USDCNH", "EURUSD", "GBPUSD", "USDJPY"]
    results = {}

    for symbol in required_forex:
        try:
            result = get_international_finance_data(symbol, start_date, end_date, "forex")
            if result:
                results[symbol] = result
            else:
                results[symbol] = {
                    "error": f"无法获取{symbol}数据",
                    "symbol": symbol,
                    "data_type": "forex"
                }
        except Exception as e:
            results[symbol] = {
                "error": str(e),
                "symbol": symbol,
                "data_type": "forex"
            }

    return results


def batch_get_background_scan_bonds(start_date: str, end_date: str) -> Dict[str, Any]:
    """批量获取120背景扫描需要的国债收益率数据

    Args:
        start_date: 开始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD

    Returns:
        包含所有国债收益率数据的字典
    """
    required_bonds = ["US10Y", "CN10Y", "CN10Y_CDB"]
    results = {}

    for symbol in required_bonds:
        try:
            result = get_international_finance_data(symbol, start_date, end_date, "bond_yield")
            if result:
                results[symbol] = result
            else:
                results[symbol] = {
                    "error": f"无法获取{symbol}数据",
                    "symbol": symbol,
                    "data_type": "bond_yield"
                }
        except Exception as e:
            results[symbol] = {
                "error": str(e),
                "symbol": symbol,
                "data_type": "bond_yield"
            }

    return results


def validate_international_finance_support() -> Dict[str, bool]:
    """验证国际金融数据支持情况

    Returns:
        各类数据的支持状态
    """
    support_status = {
        "forex_symbols": {},
        "bond_yield_symbols": {},
        "overall_support": True
    }

    # 测试汇率数据支持
    for symbol, config in INTERNATIONAL_FINANCE_SYMBOLS["forex"].items():
        yahoo_symbol = config["yahoo"]
        resolved = _resolve_symbol(yahoo_symbol)
        support_status["forex_symbols"][symbol] = resolved is not None

    # 测试国债收益率数据支持
    for symbol, config in INTERNATIONAL_FINANCE_SYMBOLS["bond_yields"].items():
        if "yahoo" in config:
            yahoo_symbol = config["yahoo"]
            resolved = _resolve_symbol(yahoo_symbol)
            support_status["bond_yield_symbols"][symbol] = resolved is not None
        elif "proxy_etf" in config:
            proxy_symbol = config["proxy_etf"]
            resolved = _resolve_symbol(proxy_symbol)
            support_status["bond_yield_symbols"][symbol] = resolved is not None
        else:
            support_status["bond_yield_symbols"][symbol] = False

    # 检查整体支持情况
    all_forex_supported = all(support_status["forex_symbols"].values())
    all_bonds_supported = all(support_status["bond_yield_symbols"].values())
    support_status["overall_support"] = all_forex_supported and all_bonds_supported

    return support_status
