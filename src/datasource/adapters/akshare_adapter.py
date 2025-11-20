import asyncio
from typing import List, Optional
import pandas as pd
import akshare as ak
from loguru import logger

from ..models.base import BaseDataSource, DataSourceConfig, DataResponse
from ..utils.rate_limiter import RateLimiter
from ..utils.retry import async_retry
from ..cache.memory_cache import MemoryCache, cache_key


class AKShareConfig(DataSourceConfig):
    """AKShare 数据源配置"""
    name: str = "akshare"
    rate_limit: int = 10
    timeout: int = 30
    retry_count: int = 3
    cache_enabled: bool = True
    cache_ttl: int = 300


class AKShareAdapter(BaseDataSource):
    """AKShare 数据源适配器"""
    
    def __init__(self, config: Optional[AKShareConfig] = None):
        if config is None:
            config = AKShareConfig()
        super().__init__(config)
        
        self.rate_limiter = RateLimiter(config.rate_limit)
        self.cache = MemoryCache(config.cache_ttl) if config.cache_enabled else None
        
        logger.info(f"AKShare adapter initialized with rate limit: {config.rate_limit}/s")
    
    async def _execute_with_cache_and_rate_limit(self, func, cache_key_str: str, *args, **kwargs):
        """执行函数并处理缓存和速率限制"""
        
        # 检查缓存
        if self.cache:
            cached_result = self.cache.get(cache_key_str)
            if cached_result is not None:
                logger.debug(f"Cache hit for {cache_key_str}")
                return cached_result
        
        # 速率限制
        await self.rate_limiter.acquire()
        
        # 执行函数
        try:
            # 在线程池中执行同步函数
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: func(*args, **kwargs))
            
            # 缓存结果
            if self.cache and result is not None:
                self.cache.set(cache_key_str, result, self.config.cache_ttl)
            
            return result
        except Exception as e:
            logger.error(f"AKShare function execution failed: {e}")
            raise e
    
    @async_retry(max_attempts=3, delay=1.0)
    async def get_stock_basic(self, **kwargs) -> DataResponse:
        """获取股票基本信息"""
        try:
            cache_key_str = cache_key("stock_basic", **kwargs)
            
            data = await self._execute_with_cache_and_rate_limit(
                ak.stock_info_a_code_name, cache_key_str
            )
            
            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "stock_info_a_code_name", "params": kwargs}
            )
            
        except Exception as e:
            logger.error(f"Failed to get stock basic info: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "stock_info_a_code_name", "params": kwargs}
            )
    
    @async_retry(max_attempts=3, delay=1.0)
    async def get_stock_daily(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取股票日线数据"""
        try:
            cache_key_str = cache_key("stock_daily", symbol, start_date, end_date, **kwargs)
            
            data = await self._execute_with_cache_and_rate_limit(
                ak.stock_zh_a_hist, cache_key_str,
                symbol=symbol,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq"  # 前复权
            )

            # 标准化列名
            if data is not None and not data.empty:
                data = self._standardize_index_columns(data)

            return DataResponse(
                data=data,
                source=self.name,
                metadata={
                    "method": "stock_zh_a_hist",
                    "params": {"symbol": symbol, "start_date": start_date, "end_date": end_date, **kwargs}
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to get stock daily data for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={
                    "method": "stock_zh_a_hist",
                    "params": {"symbol": symbol, "start_date": start_date, "end_date": end_date, **kwargs}
                }
            )
    
    @async_retry(max_attempts=3, delay=1.0)
    async def get_stock_realtime(self, symbols: List[str], **kwargs) -> DataResponse:
        """获取股票实时数据"""
        try:
            cache_key_str = cache_key("stock_realtime", symbols, **kwargs)
            
            data = await self._execute_with_cache_and_rate_limit(
                ak.stock_zh_a_spot_em, cache_key_str
            )
            
            # 如果指定了特定股票代码，则过滤结果
            if symbols and data is not None:
                data = data[data['代码'].isin(symbols)]
            
            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "stock_zh_a_spot_em", "params": {"symbols": symbols, **kwargs}}
            )
            
        except Exception as e:
            logger.error(f"Failed to get realtime data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "stock_zh_a_spot_em", "params": {"symbols": symbols, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_fund_daily(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取基金/ETF日线数据"""
        try:
            cache_key_str = cache_key("fund_daily", symbol, start_date, end_date, **kwargs)

            normalized_symbol = self._normalize_fund_symbol(symbol)
            data = await self._execute_with_cache_and_rate_limit(
                ak.fund_etf_hist_em, cache_key_str,
                symbol=normalized_symbol,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="hfq"
            )

            if data is not None and not data.empty:
                data = self._standardize_index_columns(data)

            return DataResponse(
                data=data,
                source=self.name,
                metadata={
                    "method": "fund_etf_hist_em",
                    "params": {"symbol": normalized_symbol, "start_date": start_date, "end_date": end_date, **kwargs}
                }
            )

        except Exception as e:
            logger.error(f"Failed to get fund daily data for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={
                    "method": "fund_etf_hist_em",
                    "params": {"symbol": symbol, "start_date": start_date, "end_date": end_date, **kwargs}
                }
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_index_daily(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取指数日线数据"""
        try:
            cache_key_str = cache_key("index_daily", symbol, start_date, end_date, **kwargs)
            
            data = await self._execute_with_cache_and_rate_limit(
                ak.index_zh_a_hist, cache_key_str,
                symbol=symbol,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", "")
            )

            # Standardize column names for better compatibility
            if data is not None and not data.empty:
                data = self._standardize_index_columns(data)

            return DataResponse(
                data=data,
                source=self.name,
                metadata={
                    "method": "index_zh_a_hist",
                    "params": {"symbol": symbol, "start_date": start_date, "end_date": end_date, **kwargs}
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to get index daily data for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={
                    "method": "index_zh_a_hist",
                    "params": {"symbol": symbol, "start_date": start_date, "end_date": end_date, **kwargs}
                }
            )
    
    @async_retry(max_attempts=3, delay=1.0)
    async def get_financial_data(self, symbol: str, **kwargs) -> DataResponse:
        """获取财务数据"""
        try:
            cache_key_str = cache_key("financial_data", symbol, **kwargs)
            
            # 获取财务指标数据
            data = await self._execute_with_cache_and_rate_limit(
                ak.stock_financial_abstract, cache_key_str,
                symbol=symbol
            )
            
            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "stock_financial_abstract", "params": {"symbol": symbol, **kwargs}}
            )
            
        except Exception as e:
            logger.error(f"Failed to get financial data for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "stock_financial_abstract", "params": {"symbol": symbol, **kwargs}}
            )

    def _standardize_index_columns(self, df):
        """标准化指数/ETF数据列名"""
        if df is None or df.empty:
            return df

        df = df.copy()

        rename_map = {
            '日期': 'date',
            'date': 'date',
            '交易日期': 'date',
            '开盘': 'open',
            'open': 'open',
            '最高': 'high',
            'high': 'high',
            '最低': 'low',
            'low': 'low',
            '收盘': 'close',
            'close': 'close',
            '成交量': 'volume',
            'vol': 'volume',
            '成交额': 'amount',
            'amount': 'amount',
            '涨跌幅': 'pct_chg',
            '涨跌额': 'change',
            '换手率': 'turnover',
            '振幅': 'amplitude'
        }

        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df = df.dropna(subset=['date']).sort_values('date')

        return df

    async def is_available(self) -> bool:
        """检查数据源是否可用"""
        try:
            # 尝试获取一个简单的数据来检查可用性
            response = await self.get_stock_basic()
            return response.error is None and response.data is not None
        except Exception as e:
            logger.error(f"AKShare availability check failed: {e}")
            return False

    def _normalize_fund_symbol(self, symbol: str) -> str:
        """将基金/ETF代码转换为akshare支持的格式"""
        if symbol.endswith(('.SH', '.SZ')):
            return symbol.split('.')[0]
        return symbol

    @async_retry(max_attempts=3, delay=1.0)
    async def get_hsgt_flow(self, symbol: str = '北向资金', **kwargs) -> DataResponse:
        """获取沪深港通资金流向数据

        Args:
            symbol: '北向资金' 或 '南向资金'

        Returns:
            DataResponse包含历史资金流向数据

        数据源: 东方财富网 (data.eastmoney.com/hsgt/)
        """
        try:
            cache_key_str = cache_key("hsgt_flow", symbol, **kwargs)

            logger.info(f"Fetching HSGT flow data for {symbol}")
            data = await self._execute_with_cache_and_rate_limit(
                ak.stock_hsgt_hist_em, cache_key_str,
                symbol=symbol
            )

            if data is not None and not data.empty:
                logger.info(f"Successfully fetched {len(data)} records for {symbol}")
                return DataResponse(
                    data=data,
                    source=self.name,
                    metadata={
                        "method": "stock_hsgt_hist_em",
                        "params": {"symbol": symbol},
                        "data_source": "东方财富网",
                        "records": len(data)
                    }
                )
            else:
                logger.warning(f"Empty data returned for {symbol}")
                return DataResponse(
                    data=None,
                    source=self.name,
                    error="Empty data returned",
                    metadata={"method": "stock_hsgt_hist_em", "params": {"symbol": symbol}}
                )

        except Exception as e:
            logger.error(f"Failed to get HSGT flow data for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "stock_hsgt_hist_em", "params": {"symbol": symbol}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_margin_summary(self, start_date: str, end_date: str,
                                 exchange: str = 'both', **kwargs) -> DataResponse:
        """获取融资融券汇总数据

        Args:
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            exchange: 'sse'(上交所), 'szse'(深交所), 'both'(合并)

        Returns:
            DataResponse包含融资融券汇总数据

        数据源: 上海证券交易所、深圳证券交易所官网
        """
        try:
            cache_key_str = cache_key("margin_summary", start_date, end_date, exchange, **kwargs)

            logger.info(f"Fetching margin trading data: {start_date} to {end_date}, exchange={exchange}")

            result_data = None

            # 获取上交所数据
            if exchange in ['sse', 'both']:
                try:
                    sse_data = await self._execute_with_cache_and_rate_limit(
                        ak.stock_margin_sse, cache_key_str + "_sse",
                        start_date=start_date.replace('-', ''),
                        end_date=end_date.replace('-', '')
                    )
                    if sse_data is not None and not sse_data.empty:
                        sse_data['exchange'] = 'SSE'
                        result_data = sse_data
                        logger.info(f"SSE margin data: {len(sse_data)} records")
                except Exception as e:
                    logger.warning(f"Failed to get SSE margin data: {e}")

            # 获取深交所数据
            if exchange in ['szse', 'both']:
                try:
                    # 深交所接口只支持单日查询，需要循环
                    szse_data_list = []
                    date_range = pd.date_range(start=start_date, end=end_date, freq='D')

                    for date in date_range:
                        date_str = date.strftime('%Y%m%d')
                        try:
                            daily_data = await self._execute_with_cache_and_rate_limit(
                                ak.stock_margin_szse, cache_key_str + f"_szse_{date_str}",
                                date=date_str
                            )
                            if daily_data is not None and not daily_data.empty:
                                szse_data_list.append(daily_data)
                        except Exception as e:
                            logger.debug(f"No SZSE data for {date_str}: {e}")
                            continue

                    if szse_data_list:
                        szse_data = pd.concat(szse_data_list, ignore_index=True)
                        szse_data['exchange'] = 'SZSE'
                        logger.info(f"SZSE margin data: {len(szse_data)} records")

                        if result_data is not None:
                            result_data = pd.concat([result_data, szse_data], ignore_index=True)
                        else:
                            result_data = szse_data
                except Exception as e:
                    logger.warning(f"Failed to get SZSE margin data: {e}")

            if result_data is not None and not result_data.empty:
                return DataResponse(
                    data=result_data,
                    source=self.name,
                    metadata={
                        "method": "stock_margin_sse/szse",
                        "params": {"start_date": start_date, "end_date": end_date, "exchange": exchange},
                        "data_source": "上交所/深交所官网",
                        "records": len(result_data)
                    }
                )
            else:
                return DataResponse(
                    data=None,
                    source=self.name,
                    error="No margin data available for the specified date range",
                    metadata={
                        "method": "stock_margin_sse/szse",
                        "params": {"start_date": start_date, "end_date": end_date, "exchange": exchange}
                    }
                )

        except Exception as e:
            logger.error(f"Failed to get margin summary: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={
                    "method": "stock_margin_sse/szse",
                    "params": {"start_date": start_date, "end_date": end_date, "exchange": exchange}
                }
            )
