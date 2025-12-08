#!/usr/bin/env python3
"""
国际金融数据适配器
专门处理汇率、国债收益率等国际金融数据
支持120背景扫描方案的完整数据需求
"""

import asyncio
import pandas as pd
import tushare as ts
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from loguru import logger

from ..models.base import BaseDataSource, DataResponse, DataSourceConfig
from ..config.indices_config import (
    FOREX_PAIRS, BOND_YIELDS, BACKGROUND_SCAN_120D_CONFIG, DATA_PRIORITY_CONFIG
)
from ..utils.yahoo_finance import fetch_price_history
from ..utils.rate_limiter import RateLimiter
from ..cache.memory_cache import MemoryCache


class InternationalFinanceConfig(DataSourceConfig):
    """国际金融数据源配置"""
    forex_pairs: Dict[str, Dict[str, Any]] = None
    bond_yields: Dict[str, Dict[str, Any]] = None
    use_yahoo_fallback: bool = True
    use_websearch_fallback: bool = True
    time_window: int = 60  # 添加缺失的time_window字段

    def __init__(self, **kwargs):
        # 设置默认值
        if 'forex_pairs' not in kwargs:
            kwargs['forex_pairs'] = FOREX_PAIRS
        if 'bond_yields' not in kwargs:
            kwargs['bond_yields'] = BOND_YIELDS
        if 'name' not in kwargs:
            kwargs['name'] = 'international_finance'

        super().__init__(**kwargs)


class InternationalFinanceAdapter(BaseDataSource):
    """国际金融数据适配器

    支持的数据类型：
    1. 汇率数据：美元指数DXY、USD/CNY、USD/CNH等
    2. 国债收益率：美国10年期、中国10年期等
    3. 多级数据源：Yahoo Finance -> AKShare -> WebSearch
    """

    def __init__(self, config: Optional[InternationalFinanceConfig] = None):
        self.config = config or InternationalFinanceConfig()
        self.rate_limiter = RateLimiter(self.config.rate_limit)
        self.cache = MemoryCache(default_ttl=self.config.cache_ttl)
        self.name = "international_finance"

        logger.info(f"初始化国际金融数据适配器，配置: {self.config}")

    async def is_available(self) -> bool:
        """检查数据源可用性"""
        try:
            # 测试Yahoo Finance访问
            test_data = fetch_price_history("DX-Y.NYB", "2023-01-01", "2023-01-02")
            return test_data is not None
        except Exception as e:
            logger.warning(f"国际金融数据源不可用: {e}")
            return False

    async def get_forex_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        **kwargs
    ) -> DataResponse:
        """获取汇率数据

        Args:
            symbol: 汇率代码 (如 'DXY', 'USDCNY', 'USDCNH')
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD

        Returns:
            DataResponse: 包含汇率历史数据
        """
        cache_key = f"forex_{symbol}_{start_date}_{end_date}"

        # 检查缓存
        cached_data = self.cache.get(cache_key)
        if cached_data is not None:
            return DataResponse(
                data=cached_data,
                source=self.name,
                timestamp=datetime.now(),
                metadata={"cache_hit": True, "symbol": symbol}
            )

        await self.rate_limiter.acquire()

        try:
            # 获取配置中的汇率信息
            forex_config = None
            for name, config in FOREX_PAIRS.items():
                if config["symbol"] == symbol:
                    forex_config = config
                    break

            if not forex_config:
                return DataResponse(
                    data=None,
                    source=self.name,
                    error=f"汇率代码 {symbol} 未在配置中找到",
                    timestamp=datetime.now()
                )

            # 尝试从Yahoo Finance获取数据
            yahoo_symbol = forex_config.get("yahoo_symbol")
            if yahoo_symbol:
                data = fetch_price_history(yahoo_symbol, start_date, end_date)
                if data is not None and not data.empty:
                    # 格式化数据
                    formatted_data = self._format_forex_data(data, symbol, forex_config)

                    # 缓存数据
                    self.cache.set(cache_key, formatted_data)

                    return DataResponse(
                        data=formatted_data,
                        source=self.name,
                        timestamp=datetime.now(),
                        metadata={
                            "source_type": "yahoo_finance",
                            "symbol": symbol,
                            "yahoo_symbol": yahoo_symbol,
                            "data_source": forex_config.get("data_source", "外汇数据")
                        }
                    )

            # 如果Yahoo Finance失败，尝试其他数据源
            logger.warning(f"Yahoo Finance获取 {symbol} 数据失败，尝试其他数据源")

            return DataResponse(
                data=None,
                source=self.name,
                error=f"无法获取汇率数据: {symbol}",
                timestamp=datetime.now(),
                metadata={"attempted_sources": ["yahoo_finance"], "symbol": symbol}
            )

        except Exception as e:
            logger.error(f"获取汇率数据失败 {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=f"获取汇率数据异常: {str(e)}",
                timestamp=datetime.now()
            )

    async def get_bond_yield_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        **kwargs
    ) -> DataResponse:
        """获取国债收益率数据

        Args:
            symbol: 国债代码 (如 'US10Y', 'CN10Y', 'CN10Y_CDB')
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD

        Returns:
            DataResponse: 包含国债收益率数据
        """
        cache_key = f"bond_yield_{symbol}_{start_date}_{end_date}"

        # 检查缓存
        cached_data = self.cache.get(cache_key)
        if cached_data is not None:
            return DataResponse(
                data=cached_data,
                source=self.name,
                timestamp=datetime.now(),
                metadata={"cache_hit": True, "symbol": symbol}
            )

        await self.rate_limiter.acquire()

        try:
            # 获取配置中的国债信息
            bond_config = None
            for name, config in BOND_YIELDS.items():
                if config["symbol"] == symbol:
                    bond_config = config
                    break

            if not bond_config:
                return DataResponse(
                    data=None,
                    source=self.name,
                    error=f"国债代码 {symbol} 未在配置中找到",
                    timestamp=datetime.now()
                )

            # 优先尝试 TuShare us_tycr 获取美国国债收益率（官方数据）
            if symbol == "US10Y":
                try:
                    pro = ts.pro_api()
                    start = start_date.replace("-", "")
                    end = end_date.replace("-", "")
                    # y10 字段为10年期国债收益率（%）
                    df = pro.us_tycr(start_date=start, end_date=end, fields="date,y10")
                    if df is not None and not df.empty:
                        df = df.rename(columns={"y10": "close"})
                        df["date"] = pd.to_datetime(df["date"])
                        df = df.sort_values("date")
                        formatted_data = self._format_bond_yield_data(df, symbol, bond_config)
                        self.cache.set(cache_key, formatted_data)
                        return DataResponse(
                            data=formatted_data,
                            source=self.name,
                            timestamp=datetime.now(),
                            metadata={
                                "source_type": "tushare_us_tycr",
                                "symbol": symbol,
                                "data_source": "TuShare us_tycr"
                            }
                        )
                    else:
                        logger.warning("TuShare us_tycr 返回空数据，回退到其他数据源")
                except Exception as ts_err:
                    logger.error(f"TuShare us_tycr 获取 {symbol} 失败: {ts_err}")

            # 对于中国国债，使用债券ETF代理
            if symbol in ["CN10Y", "CN10Y_CDB"]:
                proxy_etf = bond_config.get("proxy_etf")
                if proxy_etf:
                    # 从DataSourceManager获取债券ETF数据
                    etf_data = await self._get_bond_etf_proxy_data(proxy_etf, start_date, end_date)
                    if etf_data is not None:
                        # 基于ETF价格反推收益率变化
                        yield_data = self._convert_etf_to_yield(etf_data, symbol, bond_config)
                        self.cache.set(cache_key, yield_data)

                        return DataResponse(
                            data=yield_data,
                            source=self.name,
                            timestamp=datetime.now(),
                            metadata={
                                "source_type": "bond_etf_proxy",
                                "symbol": symbol,
                                "proxy_etf": proxy_etf,
                                "data_source": bond_config.get("data_source", "中债估值"),
                                "calculation_method": "基于债券ETF价格反推收益率变化"
                            }
                        )

            return DataResponse(
                data=None,
                source=self.name,
                error=f"无法获取国债收益率数据: {symbol}",
                timestamp=datetime.now(),
                metadata={"symbol": symbol, "bond_config": bond_config}
            )

        except Exception as e:
            logger.error(f"获取国债收益率数据失败 {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=f"获取国债收益率数据异常: {str(e)}",
                timestamp=datetime.now()
            )

    async def batch_get_background_scan_data(
        self,
        start_date: str,
        end_date: str,
        **kwargs
    ) -> Dict[str, DataResponse]:
        """批量获取120背景扫描所需的国际金融数据

        Args:
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD

        Returns:
            Dict[str, DataResponse]: 各类资产的数据响应
        """
        results = {}
        config = BACKGROUND_SCAN_120D_CONFIG["required_assets"]

        # 获取优先级1的汇率数据
        forex_tasks = []
        for symbol in config["forex"]["priority_1"]:
            task = self.get_forex_data(symbol, start_date, end_date)
            forex_tasks.append((f"forex_{symbol}", task))

        # 获取优先级1的国债收益率数据
        bond_tasks = []
        for symbol in config["bond_yields"]["priority_1"]:
            task = self.get_bond_yield_data(symbol, start_date, end_date)
            bond_tasks.append((f"bond_{symbol}", task))

        # 并发执行所有任务
        all_tasks = forex_tasks + bond_tasks
        task_results = await asyncio.gather(
            *[task for _, task in all_tasks],
            return_exceptions=True
        )

        # 组织结果
        for (name, _), result in zip(all_tasks, task_results):
            if isinstance(result, Exception):
                results[name] = DataResponse(
                    data=None,
                    source=self.name,
                    error=f"批量获取数据异常: {str(result)}",
                    timestamp=datetime.now()
                )
            else:
                results[name] = result

        return results

    def _format_forex_data(self, data: pd.DataFrame, symbol: str, config: Dict) -> pd.DataFrame:
        """格式化汇率数据"""
        if data is None or data.empty:
            return data

        # 确保必要的列存在
        required_columns = ['date', 'close']
        for col in required_columns:
            if col not in data.columns:
                logger.error(f"汇率数据缺少必要列: {col}")
                return data

        # 添加标准化列
        formatted_data = data.copy()
        formatted_data['symbol'] = symbol
        formatted_data['display_name'] = config.get('display_name', symbol)
        formatted_data['data_source'] = config.get('data_source', '外汇数据')

        # 计算技术指标
        if len(formatted_data) > 1:
            formatted_data['change_1d'] = formatted_data['close'].pct_change()
            formatted_data['change_1d_pct'] = formatted_data['change_1d'] * 100

        if len(formatted_data) >= 5:
            formatted_data['change_5d_pct'] = (
                formatted_data['close'] / formatted_data['close'].shift(5) - 1
            ) * 100

        if len(formatted_data) >= 120:
            formatted_data['change_120d_pct'] = (
                formatted_data['close'] / formatted_data['close'].shift(120) - 1
            ) * 100

        return formatted_data

    def _format_bond_yield_data(self, data: pd.DataFrame, symbol: str, config: Dict) -> pd.DataFrame:
        """格式化国债收益率数据"""
        if data is None or data.empty:
            return data

        formatted_data = data.copy()
        formatted_data['symbol'] = symbol
        formatted_data['display_name'] = config.get('display_name', symbol)
        formatted_data['data_source'] = config.get('data_source', 'FRED数据')
        formatted_data['country'] = config.get('country', '未知')
        formatted_data['duration'] = config.get('duration', '10年')

        # 收益率数据的close列就是收益率（%）
        formatted_data['yield_rate'] = formatted_data['close']

        # 计算收益率变化（基点，bp）
        if len(formatted_data) > 1:
            formatted_data['yield_change_1d_bp'] = (
                formatted_data['yield_rate'].diff() * 100
            )

        if len(formatted_data) >= 5:
            formatted_data['yield_change_5d_bp'] = (
                formatted_data['yield_rate'] - formatted_data['yield_rate'].shift(5)
            ) * 100

        if len(formatted_data) >= 30:
            formatted_data['yield_change_30d_bp'] = (
                formatted_data['yield_rate'] - formatted_data['yield_rate'].shift(30)
            ) * 100

        return formatted_data

    async def _get_bond_etf_proxy_data(self, etf_symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """获取债券ETF代理数据

        注意：这里需要访问DataSourceManager来获取ETF数据
        为了避免循环导入，这里返回None，实际使用时需要在更高层处理
        """
        logger.info(f"需要从DataSourceManager获取债券ETF数据: {etf_symbol}")
        return None

    def _convert_etf_to_yield(self, etf_data: pd.DataFrame, symbol: str, config: Dict) -> pd.DataFrame:
        """将债券ETF价格数据转换为收益率数据

        使用久期模型：价格变化1%约对应收益率变化10bp（对于10年期债券）
        """
        if etf_data is None or etf_data.empty:
            return etf_data

        yield_data = etf_data.copy()

        # 计算价格变化率
        yield_data['price_change_1d_pct'] = yield_data['close'].pct_change() * 100

        # 基于久期模型估算收益率变化（基点）
        # 价格上涨对应收益率下降，所以取负值
        duration = 10  # 假设久期为10年
        yield_data['yield_change_1d_bp'] = -yield_data['price_change_1d_pct'] * duration

        if len(yield_data) >= 5:
            price_change_5d = (yield_data['close'] / yield_data['close'].shift(5) - 1) * 100
            yield_data['yield_change_5d_bp'] = -price_change_5d * duration

        if len(yield_data) >= 30:
            price_change_30d = (yield_data['close'] / yield_data['close'].shift(30) - 1) * 100
            yield_data['yield_change_30d_bp'] = -price_change_30d * duration

        # 添加元数据
        yield_data['symbol'] = symbol
        yield_data['display_name'] = config.get('display_name', symbol)
        yield_data['data_source'] = config.get('data_source', '中债估值')
        yield_data['calculation_method'] = "基于债券ETF价格反推收益率变化"
        yield_data['proxy_etf'] = config.get('proxy_etf')

        return yield_data

    # 实现BaseDataSource的抽象方法
    async def get_stock_basic(self, **kwargs) -> DataResponse:
        """获取股票基本信息 - 国际金融适配器不支持此功能"""
        return DataResponse(
            data=None,
            source=self.name,
            error="国际金融适配器不支持股票基本信息查询",
            timestamp=datetime.now()
        )

    async def get_stock_daily(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取股票日线数据 - 重定向到汇率或国债数据"""
        # 检查是否为汇率代码
        for forex_name, forex_config in FOREX_PAIRS.items():
            if forex_config["symbol"] == symbol:
                return await self.get_forex_data(symbol, start_date, end_date, **kwargs)

        # 检查是否为国债代码
        for bond_name, bond_config in BOND_YIELDS.items():
            if bond_config["symbol"] == symbol:
                return await self.get_bond_yield_data(symbol, start_date, end_date, **kwargs)

        return DataResponse(
            data=None,
            source=self.name,
            error=f"国际金融适配器不支持股票代码: {symbol}",
            timestamp=datetime.now()
        )

    async def get_stock_realtime(self, symbols: List[str], **kwargs) -> DataResponse:
        """获取实时数据 - 国际金融适配器不支持此功能"""
        return DataResponse(
            data=None,
            source=self.name,
            error="国际金融适配器不支持实时数据查询",
            timestamp=datetime.now()
        )

    async def get_index_daily(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取指数日线数据 - 重定向到汇率或国债数据"""
        # 检查是否为汇率代码
        for forex_name, forex_config in FOREX_PAIRS.items():
            if forex_config["symbol"] == symbol:
                return await self.get_forex_data(symbol, start_date, end_date, **kwargs)

        # 检查是否为国债代码
        for bond_name, bond_config in BOND_YIELDS.items():
            if bond_config["symbol"] == symbol:
                return await self.get_bond_yield_data(symbol, start_date, end_date, **kwargs)

        return DataResponse(
            data=None,
            source=self.name,
            error=f"国际金融适配器不支持指数代码: {symbol}",
            timestamp=datetime.now()
        )

    async def get_financial_data(self, symbol: str, **kwargs) -> DataResponse:
        """获取财务数据 - 国际金融适配器不支持此功能"""
        return DataResponse(
            data=None,
            source=self.name,
            error="国际金融适配器不支持财务数据查询",
            timestamp=datetime.now()
        )
