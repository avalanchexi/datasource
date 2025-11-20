import asyncio
import os
from typing import Dict, List, Optional
import pandas as pd
import tushare as ts
from loguru import logger

from ..models.base import BaseDataSource, DataSourceConfig, DataResponse
from ..utils.rate_limiter import RateLimiter
from ..utils.retry import async_retry
from ..cache.memory_cache import MemoryCache, cache_key
from ..utils.tushare_patch import monkey_patch_tushare, safe_get_today_all


class TuShareConfig(DataSourceConfig):
    """TuShare 数据源配置"""
    name: str = "tushare"
    rate_limit: int = 5  # TuShare 限制更严格
    timeout: int = 30
    retry_count: int = 3
    cache_enabled: bool = True
    cache_ttl: int = 300
    token: Optional[str] = None


class TuShareAdapter(BaseDataSource):
    """TuShare 数据源适配器"""
    
    def __init__(self, config: Optional[TuShareConfig] = None):
        if config is None:
            config = TuShareConfig()
        super().__init__(config)

        # 应用兼容性补丁
        monkey_patch_tushare()

        # 设置 TuShare token
        token = config.token or os.getenv("TUSHARE_TOKEN")
        self.pro = None
        if not token:
            logger.warning("TuShare token not provided, some functions may not work")
        else:
            try:
                self.pro = ts.pro_api(token)
                logger.info("TuShare token configured via pro_api(token)")
            except Exception as err:
                logger.error(f"Failed to init TuShare via token: {err}")
                try:
                    ts.set_token(token)
                    self.pro = ts.pro_api()
                    logger.info("TuShare token configured via set_token fallback")
                except Exception as inner_err:
                    logger.error(f"Fallback set_token failed: {inner_err}")
                    self.pro = None
        self.rate_limiter = RateLimiter(config.rate_limit)
        self.cache = MemoryCache(config.cache_ttl) if config.cache_enabled else None

        logger.info(f"TuShare adapter initialized with rate limit: {config.rate_limit}/s")
    
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
            logger.error(f"TuShare function execution failed: {e}")
            raise e
    
    @async_retry(max_attempts=3, delay=1.0)
    async def get_stock_basic(self, **kwargs) -> DataResponse:
        """获取股票基本信息"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")
            
            cache_key_str = cache_key("stock_basic", **kwargs)
            
            data = await self._execute_with_cache_and_rate_limit(
                self.pro.stock_basic, cache_key_str,
                exchange='', list_status='L', fields='ts_code,symbol,name,area,industry,market,list_date'
            )
            
            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "stock_basic", "params": kwargs}
            )
            
        except Exception as e:
            logger.error(f"Failed to get stock basic info: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "stock_basic", "params": kwargs}
            )
    
    @async_retry(max_attempts=3, delay=1.0)
    async def get_stock_daily(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取股票日线数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")
            
            # 转换股票代码格式，确保包含交易所后缀
            if '.' not in symbol:
                if symbol.startswith('6'):
                    ts_code = f"{symbol}.SH"
                elif symbol.startswith(('0', '3')):
                    ts_code = f"{symbol}.SZ"
                else:
                    ts_code = symbol
            else:
                ts_code = symbol
            
            cache_key_str = cache_key("stock_daily", ts_code, start_date, end_date, **kwargs)
            
            data = await self._execute_with_cache_and_rate_limit(
                self.pro.daily, cache_key_str,
                ts_code=ts_code,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", "")
            )
            
            return DataResponse(
                data=data,
                source=self.name,
                metadata={
                    "method": "daily",
                    "params": {"symbol": symbol, "ts_code": ts_code, "start_date": start_date, "end_date": end_date, **kwargs}
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to get stock daily data for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={
                    "method": "daily",
                    "params": {"symbol": symbol, "start_date": start_date, "end_date": end_date, **kwargs}
                }
            )
    
    @async_retry(max_attempts=3, delay=1.0)
    async def get_stock_realtime(self, symbols: List[str], **kwargs) -> DataResponse:
        """获取股票实时数据"""
        try:
            cache_key_str = cache_key("stock_realtime", symbols, **kwargs)
            
            # TuShare 免费版可能不支持实时数据，使用最新交易日数据作为替代
            if self.pro:
                # 转换股票代码格式
                ts_codes = []
                for symbol in symbols:
                    if '.' not in symbol:
                        if symbol.startswith('6'):
                            ts_codes.append(f"{symbol}.SH")
                        elif symbol.startswith(('0', '3')):
                            ts_codes.append(f"{symbol}.SZ")
                        else:
                            ts_codes.append(symbol)
                    else:
                        ts_codes.append(symbol)
                
                # 获取最新交易日数据
                data = await self._execute_with_cache_and_rate_limit(
                    self.pro.daily, cache_key_str,
                    ts_code=','.join(ts_codes[:20])  # 限制查询数量
                )
                
                # 按日期排序，获取最新数据
                if data is not None and not data.empty:
                    data = data.sort_values('trade_date', ascending=False).groupby('ts_code').first().reset_index()
            else:
                # 使用免费接口 - 使用安全版本
                data = await self._execute_with_cache_and_rate_limit(
                    safe_get_today_all, cache_key_str
                )
                
                # 过滤指定股票
                if symbols and data is not None:
                    data = data[data['code'].isin(symbols)]
            
            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "realtime", "params": {"symbols": symbols, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get realtime stock data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "realtime", "params": {"symbols": symbols, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_repo_rate(self, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取债券回购日行情，用于DR007等利率指标"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            cache_key_str = cache_key("repo_daily", start_date, end_date, **kwargs)
            data = await self._execute_with_cache_and_rate_limit(
                self.pro.repo_daily,
                cache_key_str,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                **kwargs
            )
            return DataResponse(
                data=data,
                source=self.name,
                metadata={
                    "method": "repo_daily",
                    "params": {"start_date": start_date, "end_date": end_date, **kwargs}
                }
            )
        except Exception as e:
            logger.error(f"Failed to get repo rate data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "repo_daily", "params": {"start_date": start_date, "end_date": end_date, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_money_supply(self, start_month: str, end_month: str, **kwargs) -> DataResponse:
        """获取货币供应量（月度）"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            cache_key_str = cache_key("cn_m", start_month, end_month, **kwargs)
            data = await self._execute_with_cache_and_rate_limit(
                self.pro.cn_m,
                cache_key_str,
                start_m=start_month,
                end_m=end_month,
                **kwargs
            )
            return DataResponse(
                data=data,
                source=self.name,
                metadata={
                    "method": "cn_m",
                    "params": {"start_m": start_month, "end_m": end_month, **kwargs}
                }
            )
        except Exception as e:
            logger.error(f"Failed to get money supply data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "cn_m", "params": {"start_m": start_month, "end_m": end_month, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_social_financing(self, start_month: str, end_month: str, **kwargs) -> DataResponse:
        """获取月度社会融资数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            cache_key_str = cache_key("sf_month", start_month, end_month, **kwargs)
            data = await self._execute_with_cache_and_rate_limit(
                self.pro.sf_month,
                cache_key_str,
                start_m=start_month,
                end_m=end_month,
                **kwargs
            )
            return DataResponse(
                data=data,
                source=self.name,
                metadata={
                    "method": "sf_month",
                    "params": {"start_m": start_month, "end_m": end_month, **kwargs}
                }
            )
        except Exception as e:
            logger.error(f"Failed to get social financing data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "sf_month", "params": {"start_m": start_month, "end_m": end_month, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_gdp_data(self, start_quarter: str, end_quarter: str, **kwargs) -> DataResponse:
        """获取国内生产总值（季度）"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            cache_key_str = cache_key("cn_gdp", start_quarter, end_quarter, **kwargs)
            data = await self._execute_with_cache_and_rate_limit(
                self.pro.cn_gdp,
                cache_key_str,
                start_q=start_quarter,
                end_q=end_quarter,
                **kwargs
            )
            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "cn_gdp", "params": {"start_q": start_quarter, "end_q": end_quarter, **kwargs}}
            )
        except Exception as e:
            logger.error(f"Failed to get GDP data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "cn_gdp", "params": {"start_q": start_quarter, "end_q": end_quarter, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_pmi_data(self, start_month: str, end_month: str, **kwargs) -> DataResponse:
        """获取PMI及其分项数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            cache_key_str = cache_key("cn_pmi", start_month, end_month, **kwargs)
            data = await self._execute_with_cache_and_rate_limit(
                self.pro.cn_pmi,
                cache_key_str,
                start_m=start_month,
                end_m=end_month,
                **kwargs
            )
            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "cn_pmi", "params": {"start_m": start_month, "end_m": end_month, **kwargs}}
            )
        except Exception as e:
            logger.error(f"Failed to get PMI data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "cn_pmi", "params": {"start_m": start_month, "end_m": end_month, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_ppi_data(self, start_month: str, end_month: str, **kwargs) -> DataResponse:
        """获取PPI数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            cache_key_str = cache_key("cn_ppi", start_month, end_month, **kwargs)
            data = await self._execute_with_cache_and_rate_limit(
                self.pro.cn_ppi,
                cache_key_str,
                start_m=start_month,
                end_m=end_month,
                **kwargs
            )
            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "cn_ppi", "params": {"start_m": start_month, "end_m": end_month, **kwargs}}
            )
        except Exception as e:
            logger.error(f"Failed to get PPI data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "cn_ppi", "params": {"start_m": start_month, "end_m": end_month, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_cpi_data(self, start_month: str, end_month: str, **kwargs) -> DataResponse:
        """获取CPI数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            cache_key_str = cache_key("cn_cpi", start_month, end_month, **kwargs)
            data = await self._execute_with_cache_and_rate_limit(
                self.pro.cn_cpi,
                cache_key_str,
                start_m=start_month,
                end_m=end_month,
                **kwargs
            )
            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "cn_cpi", "params": {"start_m": start_month, "end_m": end_month, **kwargs}}
            )
        except Exception as e:
            logger.error(f"Failed to get CPI data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "cn_cpi", "params": {"start_m": start_month, "end_m": end_month, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_margin_total(self, start_date: str, end_date: str, exchange: str = "both", **kwargs) -> DataResponse:
        """获取融资融券汇总数据（优先TuShare）"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            exchanges: List[str]
            ex = (exchange or "both").upper()
            if ex == "BOTH":
                exchanges = ["SSE", "SZSE"]
            elif ex in {"SSE", "SZSE"}:
                exchanges = [ex]
            else:
                exchanges = ["SSE", "SZSE"]

            frames = []
            start_fmt = start_date.replace("-", "")
            end_fmt = end_date.replace("-", "")
            for ex_item in exchanges:
                cache_key_str = cache_key("margin_total", ex_item, start_fmt, end_fmt, **kwargs)
                data = await self._execute_with_cache_and_rate_limit(
                    self.pro.margin,
                    cache_key_str,
                    exchange_id=ex_item,
                    start_date=start_fmt,
                    end_date=end_fmt,
                    **kwargs
                )
                if data is not None and not data.empty:
                    frames.append(data)

            combined = pd.concat(frames, ignore_index=True) if frames else None
            return DataResponse(
                data=combined,
                source=self.name,
                metadata={
                    "method": "margin",
                    "params": {"exchange_id": exchange, "start_date": start_fmt, "end_date": end_fmt, **kwargs}
                }
            )
        except Exception as e:
            logger.error(f"Failed to get margin total data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "margin", "params": {"exchange_id": exchange, "start_date": start_date, "end_date": end_date, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_daily_market_info(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        exchange: str = "",
        trade_date: Optional[str] = None,
        **kwargs
    ) -> DataResponse:
        """获取交易所每日交易统计（TuShare daily_info/sz/sh daily info）

        优先使用 trade_date（官方推荐），否则回退 start/end.
        """
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            trade_param = (trade_date or "").replace("-", "")
            start_param = (start_date or "").replace("-", "")
            end_param = (end_date or "").replace("-", "")
            cache_key_str = cache_key("daily_info", exchange or "all", trade_param or f"{start_param}-{end_param}", **kwargs)

            call_kwargs = {"exchange": (exchange or "")}
            if trade_param:
                call_kwargs["trade_date"] = trade_param
            else:
                call_kwargs["start_date"] = start_param
                call_kwargs["end_date"] = end_param

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.daily_info,
                cache_key_str,
                **call_kwargs
            )
            return DataResponse(
                data=data,
                source=self.name,
                metadata={
                    "method": "daily_info",
                    "params": {
                        "exchange": exchange,
                        "trade_date": trade_param,
                        "start_date": start_param,
                        "end_date": end_param,
                        **kwargs
                    }
                }
            )
        except Exception as e:
            logger.error(f"Failed to get daily market info: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={
                    "method": "daily_info",
                    "params": {
                        "exchange": exchange,
                        "trade_date": trade_param,
                        "start_date": start_param,
                        "end_date": end_param,
                        **kwargs
                    }
                }
            )
    
    @async_retry(max_attempts=3, delay=1.0)
    async def get_index_daily(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取指数日线数据"""
        try:
            cache_key_str = cache_key("index_daily", symbol, start_date, end_date, **kwargs)
            
            if self.pro:
                # 全球指数支持（如^GSPC、^IXIC、^DJI等）
                if symbol.startswith('^'):
                    ts_code = self._map_global_index_symbol(symbol)
                    if ts_code:
                        data = await self._execute_with_cache_and_rate_limit(
                            self.pro.index_global, cache_key_str,
                            ts_code=ts_code,
                            start_date=start_date.replace("-", ""),
                            end_date=end_date.replace("-", "")
                        )
                        if data is not None and not data.empty:
                            data = self._standardize_index_columns(data)
                        return DataResponse(
                            data=data,
                            source=self.name,
                            metadata={
                                "method": "index_global",
                                "params": {"symbol": symbol, "ts_code": ts_code, "start_date": start_date, "end_date": end_date, **kwargs}
                            }
                        )
                    # 找不到映射时继续使用默认处理

                # 转换指数代码格式
                if '.' not in symbol:
                    if symbol in ['000001', '000300', '000905']:  # 上证综指、沪深300、中证500
                        ts_code = f"{symbol}.SH"
                    elif symbol in ['399001', '399006']:  # 深证成指、创业板指
                        ts_code = f"{symbol}.SZ"
                    else:
                        ts_code = symbol
                else:
                    ts_code = symbol
                
                data = await self._execute_with_cache_and_rate_limit(
                    self.pro.index_daily, cache_key_str,
                    ts_code=ts_code,
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", "")
                )
            else:
                # 使用免费接口
                data = await self._execute_with_cache_and_rate_limit(
                    ts.get_k_data, cache_key_str,
                    code=symbol,
                    start=start_date,
                    end=end_date,
                    ktype='D',
                    index=True
                )
            
            return DataResponse(
                data=data,
                source=self.name,
                metadata={
                    "method": "index_daily",
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
                    "method": "index_daily",
                    "params": {"symbol": symbol, "start_date": start_date, "end_date": end_date, **kwargs}
                }
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_fund_daily(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取基金/ETF日线数据"""
        try:
            cache_key_str = cache_key("fund_daily", symbol, start_date, end_date, **kwargs)

            if not self.pro:
                return await super().get_fund_daily(symbol, start_date, end_date, **kwargs)

            ts_code = self._format_fund_code(symbol)
            data = await self._execute_with_cache_and_rate_limit(
                self.pro.fund_daily, cache_key_str,
                ts_code=ts_code,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", "")
            )

            if data is not None and not data.empty:
                data = self._standardize_fund_columns(data)

            return DataResponse(
                data=data,
                source=self.name,
                metadata={
                    "method": "fund_daily",
                    "params": {"symbol": symbol, "start_date": start_date, "end_date": end_date, **kwargs}
                }
            )

        except Exception as e:
            logger.error(f"Failed to get fund daily data for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={
                    "method": "fund_daily",
                    "params": {"symbol": symbol, "start_date": start_date, "end_date": end_date, **kwargs}
                }
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_financial_data(self, symbol: str, **kwargs) -> DataResponse:
        """获取财务数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            # 转换股票代码格式
            if '.' not in symbol:
                if symbol.startswith('6'):
                    ts_code = f"{symbol}.SH"
                elif symbol.startswith(('0', '3')):
                    ts_code = f"{symbol}.SZ"
                else:
                    ts_code = symbol
            else:
                ts_code = symbol

            cache_key_str = cache_key("financial_data", ts_code, **kwargs)

            # 获取财务指标数据
            data = await self._execute_with_cache_and_rate_limit(
                self.pro.fina_indicator, cache_key_str,
                ts_code=ts_code
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "fina_indicator", "params": {"symbol": symbol, "ts_code": ts_code, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get financial data for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "fina_indicator", "params": {"symbol": symbol, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_income_statement(self, symbol: str, **kwargs) -> DataResponse:
        """获取利润表数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            ts_code = self._format_stock_code(symbol)
            cache_key_str = cache_key("income_statement", ts_code, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.income, cache_key_str,
                ts_code=ts_code, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "income", "params": {"symbol": symbol, "ts_code": ts_code, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get income statement for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "income", "params": {"symbol": symbol, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_balance_sheet(self, symbol: str, **kwargs) -> DataResponse:
        """获取资产负债表数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            ts_code = self._format_stock_code(symbol)
            cache_key_str = cache_key("balance_sheet", ts_code, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.balancesheet, cache_key_str,
                ts_code=ts_code, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "balancesheet", "params": {"symbol": symbol, "ts_code": ts_code, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get balance sheet for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "balancesheet", "params": {"symbol": symbol, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_cash_flow(self, symbol: str, **kwargs) -> DataResponse:
        """获取现金流量表数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            ts_code = self._format_stock_code(symbol)
            cache_key_str = cache_key("cash_flow", ts_code, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.cashflow, cache_key_str,
                ts_code=ts_code, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "cashflow", "params": {"symbol": symbol, "ts_code": ts_code, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get cash flow for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "cashflow", "params": {"symbol": symbol, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_dividend_data(self, symbol: str, **kwargs) -> DataResponse:
        """获取分红送股数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            ts_code = self._format_stock_code(symbol)
            cache_key_str = cache_key("dividend_data", ts_code, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.dividend, cache_key_str,
                ts_code=ts_code, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "dividend", "params": {"symbol": symbol, "ts_code": ts_code, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get dividend data for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "dividend", "params": {"symbol": symbol, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_forecast_data(self, symbol: str, **kwargs) -> DataResponse:
        """获取业绩预告数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            ts_code = self._format_stock_code(symbol)
            cache_key_str = cache_key("forecast_data", ts_code, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.forecast, cache_key_str,
                ts_code=ts_code, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "forecast", "params": {"symbol": symbol, "ts_code": ts_code, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get forecast data for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "forecast", "params": {"symbol": symbol, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_express_data(self, symbol: str, **kwargs) -> DataResponse:
        """获取业绩快报数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            ts_code = self._format_stock_code(symbol)
            cache_key_str = cache_key("express_data", ts_code, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.express, cache_key_str,
                ts_code=ts_code, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "express", "params": {"symbol": symbol, "ts_code": ts_code, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get express data for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "express", "params": {"symbol": symbol, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_top10_holders(self, symbol: str, **kwargs) -> DataResponse:
        """获取前十大股东数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            ts_code = self._format_stock_code(symbol)
            cache_key_str = cache_key("top10_holders", ts_code, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.top10_holders, cache_key_str,
                ts_code=ts_code, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "top10_holders", "params": {"symbol": symbol, "ts_code": ts_code, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get top10 holders for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "top10_holders", "params": {"symbol": symbol, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_top10_floatholders(self, symbol: str, **kwargs) -> DataResponse:
        """获取前十大流通股东数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            ts_code = self._format_stock_code(symbol)
            cache_key_str = cache_key("top10_floatholders", ts_code, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.top10_floatholders, cache_key_str,
                ts_code=ts_code, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "top10_floatholders", "params": {"symbol": symbol, "ts_code": ts_code, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get top10 float holders for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "top10_floatholders", "params": {"symbol": symbol, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_weekly_data(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取周线数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            ts_code = self._format_stock_code(symbol)
            cache_key_str = cache_key("weekly_data", ts_code, start_date, end_date, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.weekly, cache_key_str,
                ts_code=ts_code,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "weekly", "params": {"symbol": symbol, "ts_code": ts_code, "start_date": start_date, "end_date": end_date, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get weekly data for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "weekly", "params": {"symbol": symbol, "start_date": start_date, "end_date": end_date, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_monthly_data(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取月线数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            ts_code = self._format_stock_code(symbol)
            cache_key_str = cache_key("monthly_data", ts_code, start_date, end_date, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.monthly, cache_key_str,
                ts_code=ts_code,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "monthly", "params": {"symbol": symbol, "ts_code": ts_code, "start_date": start_date, "end_date": end_date, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get monthly data for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "monthly", "params": {"symbol": symbol, "start_date": start_date, "end_date": end_date, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_adj_factor(self, symbol: str, **kwargs) -> DataResponse:
        """获取复权因子数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            ts_code = self._format_stock_code(symbol)
            cache_key_str = cache_key("adj_factor", ts_code, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.adj_factor, cache_key_str,
                ts_code=ts_code, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "adj_factor", "params": {"symbol": symbol, "ts_code": ts_code, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get adj factor for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "adj_factor", "params": {"symbol": symbol, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_daily_basic(self, symbol: str = None, trade_date: str = None, **kwargs) -> DataResponse:
        """获取每日指标数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            params = {}
            if symbol:
                params['ts_code'] = self._format_stock_code(symbol)
            if trade_date:
                params['trade_date'] = trade_date.replace("-", "")

            cache_key_str = cache_key("daily_basic", **params, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.daily_basic, cache_key_str,
                **params, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "daily_basic", "params": {**params, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get daily basic data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "daily_basic", "params": {"symbol": symbol, "trade_date": trade_date, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_index_basic(self, market: str = None, **kwargs) -> DataResponse:
        """获取指数基本信息"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            cache_key_str = cache_key("index_basic", market, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.index_basic, cache_key_str,
                market=market, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "index_basic", "params": {"market": market, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get index basic data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "index_basic", "params": {"market": market, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_index_weight(self, index_code: str, **kwargs) -> DataResponse:
        """获取指数成分和权重数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            cache_key_str = cache_key("index_weight", index_code, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.index_weight, cache_key_str,
                index_code=index_code, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "index_weight", "params": {"index_code": index_code, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get index weight for {index_code}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "index_weight", "params": {"index_code": index_code, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_index_members(self, index_code: str, is_new: Optional[str] = None, **kwargs) -> DataResponse:
        """获取指数成分股列表"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            params = {"index_code": index_code, **kwargs}
            if is_new is not None:
                params["is_new"] = is_new

            cache_key_str = cache_key("index_member", **params)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.index_member, cache_key_str,
                **params
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "index_member", "params": params}
            )

        except Exception as e:
            logger.error(f"Failed to get index members for {index_code}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "index_member", "params": {"index_code": index_code, "is_new": is_new, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_index_moneyflow(
        self,
        index_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        **kwargs,
    ) -> DataResponse:
        """获取指数资金流向数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            params = {"ts_code": index_code, **kwargs}
            if start_date:
                params["start_date"] = start_date.replace("-", "")
            if end_date:
                params["end_date"] = end_date.replace("-", "")

            cache_key_str = cache_key("index_moneyflow", **params)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.index_moneyflow, cache_key_str,
                **params
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "index_moneyflow", "params": params}
            )

        except Exception as e:
            logger.error(f"Failed to get index moneyflow for {index_code}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "index_moneyflow", "params": {"ts_code": index_code, "start_date": start_date, "end_date": end_date, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_trade_cal(self, exchange: str = 'SSE', start_date: str = None, end_date: str = None, **kwargs) -> DataResponse:
        """获取交易日历"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            params = {'exchange': exchange}
            if start_date:
                params['start_date'] = start_date.replace("-", "")
            if end_date:
                params['end_date'] = end_date.replace("-", "")

            cache_key_str = cache_key("trade_cal", **params, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.trade_cal, cache_key_str,
                **params, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "trade_cal", "params": {**params, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get trade calendar: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "trade_cal", "params": {"exchange": exchange, "start_date": start_date, "end_date": end_date, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_money_flow(self, symbol: str, **kwargs) -> DataResponse:
        """获取资金流向数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            ts_code = self._format_stock_code(symbol)
            cache_key_str = cache_key("money_flow", ts_code, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.moneyflow, cache_key_str,
                ts_code=ts_code, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "moneyflow", "params": {"symbol": symbol, "ts_code": ts_code, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get money flow for {symbol}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "moneyflow", "params": {"symbol": symbol, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_concept_data(self, **kwargs) -> DataResponse:
        """获取概念分类数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            cache_key_str = cache_key("concept_data", **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.concept, cache_key_str,
                **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "concept", "params": kwargs}
            )

        except Exception as e:
            logger.error(f"Failed to get concept data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "concept", "params": kwargs}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_concept_detail(self, concept_code: str, **kwargs) -> DataResponse:
        """获取概念成分股数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            cache_key_str = cache_key("concept_detail", concept_code, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.concept_detail, cache_key_str,
                id=concept_code, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "concept_detail", "params": {"concept_code": concept_code, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get concept detail for {concept_code}: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "concept_detail", "params": {"concept_code": concept_code, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_hs_const(self, hs_type: str = 'SH', **kwargs) -> DataResponse:
        """获取沪深港通成分股数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            cache_key_str = cache_key("hs_const", hs_type, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.hs_const, cache_key_str,
                hs_type=hs_type, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "hs_const", "params": {"hs_type": hs_type, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get hs_const data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "hs_const", "params": {"hs_type": hs_type, **kwargs}}
            )

    @async_retry(max_attempts=3, delay=1.0)
    async def get_stk_limit(self, trade_date: str = None, **kwargs) -> DataResponse:
        """获取涨跌停数据"""
        try:
            if not self.pro:
                raise ValueError("TuShare Pro API not initialized. Please provide token.")

            params = {}
            if trade_date:
                params['trade_date'] = trade_date.replace("-", "")

            cache_key_str = cache_key("stk_limit", **params, **kwargs)

            data = await self._execute_with_cache_and_rate_limit(
                self.pro.stk_limit, cache_key_str,
                **params, **kwargs
            )

            return DataResponse(
                data=data,
                source=self.name,
                metadata={"method": "stk_limit", "params": {**params, **kwargs}}
            )

        except Exception as e:
            logger.error(f"Failed to get stk_limit data: {e}")
            return DataResponse(
                data=None,
                source=self.name,
                error=str(e),
                metadata={"method": "stk_limit", "params": {"trade_date": trade_date, **kwargs}}
            )

    def _format_stock_code(self, symbol: str) -> str:
        """格式化股票代码，确保包含交易所后缀"""
        if '.' not in symbol:
            if symbol.startswith('6'):
                return f"{symbol}.SH"
            elif symbol.startswith(('0', '3')):
                return f"{symbol}.SZ"
            else:
                return symbol
        return symbol

    def _format_fund_code(self, symbol: str) -> str:
        """规范化基金/ETF代码，兼容纯数字和带交易所后缀的写法"""
        if '.' in symbol:
            return symbol
        if symbol.startswith(('5', '1')) and len(symbol) == 6:
            # 5开头大多在上交所，1开头常在深交所（如159xxx）
            return f"{symbol}.SH" if symbol.startswith('5') else f"{symbol}.SZ"
        return symbol

    def _map_global_index_symbol(self, symbol: str) -> Optional[str]:
        """将Yahoo风格指数代码映射为TuShare index_global代码"""
        mapping: Dict[str, str] = {
            "^GSPC": "SPX",
            "^SPX": "SPX",
            "^DJI": "DJI",
            "^IXIC": "IXIC",
            "^NDX": "NDX",
            "^STOXX50E": "SX5E",
            "^N225": "N225",
            "^HSI": "HSI",
            "^HSTECH": "HSTECH",
            "^FTSE": "FTSE",
        }

        symbol_upper = symbol.upper()
        if symbol_upper in mapping:
            return mapping[symbol_upper]
        if symbol_upper.startswith('^'):
            return symbol_upper[1:]
        return symbol_upper

    def _standardize_index_columns(self, df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        """统一指数数据列名"""
        if df is None or df.empty:
            return df

        rename_map = {
            'trade_date': 'date',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'vol': 'volume',
            'amount': 'amount'
        }

        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df = df.dropna(subset=['date']).sort_values('date')
        return df

    def _standardize_fund_columns(self, df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        """统一基金/ETF数据列名，填充缺失OHLC字段"""
        if df is None or df.empty:
            return df

        rename_map = {
            'trade_date': 'date',
            'nav_date': 'date',
            'close': 'close',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'vol': 'volume',
            'amount': 'amount',
            'acc_nav': 'acc_nav',
            'accum_nav': 'acc_nav',
            'adj_nav': 'close'
        }

        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

        # NAV 接口可能只有净值，补齐缺失的开高低
        if 'close' in df.columns:
            for column in ('open', 'high', 'low'):
                if column not in df.columns:
                    df[column] = df['close']

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df = df.dropna(subset=['date']).sort_values('date')

        return df
    
    async def is_available(self) -> bool:
        """检查数据源是否可用"""
        try:
            if self.pro:
                # 尝试获取股票基本信息来检查可用性
                response = await self.get_stock_basic()
                return response.error is None and response.data is not None
            else:
                # 免费版检查 - 使用安全版本
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, safe_get_today_all)
                return result is not None and len(result) > 0
        except Exception as e:
            logger.error(f"TuShare availability check failed: {e}")
            return False
