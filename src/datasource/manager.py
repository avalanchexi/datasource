import os
from typing import Dict, List, Optional, Union, Any
from enum import Enum
from loguru import logger
from dotenv import load_dotenv

from .models.base import BaseDataSource, DataResponse, DataRequest
from .adapters.tushare_adapter import TuShareAdapter, TuShareConfig
from .adapters.international_finance_adapter import InternationalFinanceAdapter, InternationalFinanceConfig


def _get_env_bool(var_name: str, default: bool) -> bool:
    """Parse boolean environment variables with graceful fallback."""
    value = os.getenv(var_name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_env_int(var_name: str, default: int) -> int:
    """Parse integer environment variables with graceful fallback."""
    value = os.getenv(var_name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning(f"Invalid integer for {var_name}: {value}, using default {default}")
        return default


class DataSourceType(Enum):
    """数据源类型枚举"""
    TUSHARE = "tushare"
    INTERNATIONAL_FINANCE = "international_finance"


class DataSourceManager:
    """统一数据源管理器"""
    
    def __init__(self, config_file: Optional[str] = None):
        """
        初始化数据源管理器
        
        Args:
            config_file: 配置文件路径，默认为 .env
        """
        # 加载环境配置
        if config_file:
            load_dotenv(config_file)
        else:
            load_dotenv()
        
        self.data_sources: Dict[str, BaseDataSource] = {}
        self.primary_source: Optional[str] = None
        self.fallback_sources: List[str] = []
        
        logger.info("DataSourceManager initialized")
    
    def add_data_source(self, source_type: Union[DataSourceType, str], config: Optional[dict] = None) -> bool:
        """
        添加数据源
        
        Args:
            source_type: 数据源类型
            config: 数据源配置
            
        Returns:
            是否添加成功
        """
        try:
            if isinstance(source_type, str):
                source_type = DataSourceType(source_type)
                
            source_name = source_type.value
            
            if source_type == DataSourceType.TUSHARE:
                if isinstance(config, dict):
                    config_dict = dict(config)
                elif config is not None and hasattr(config, "dict"):
                    config_dict = config.dict()
                else:
                    config_dict = {}

                source_config = TuShareConfig(**config_dict)
                if "cache_enabled" not in config_dict:
                    source_config.cache_enabled = _get_env_bool("CACHE_ENABLED", source_config.cache_enabled)
                if "cache_ttl" not in config_dict:
                    source_config.cache_ttl = _get_env_int("CACHE_TTL", source_config.cache_ttl)
                source_config.rate_limit = _get_env_int("TUSHARE_RATE_LIMIT", source_config.rate_limit)
                source_config.token = os.getenv("TUSHARE_TOKEN", source_config.token)
                self.data_sources[source_name] = TuShareAdapter(source_config)

            elif source_type == DataSourceType.INTERNATIONAL_FINANCE:
                if isinstance(config, dict):
                    config_dict = dict(config)
                elif config is not None and hasattr(config, "dict"):
                    config_dict = config.dict()
                else:
                    config_dict = {}

                source_config = InternationalFinanceConfig(**config_dict)
                if "cache_enabled" not in config_dict:
                    source_config.cache_enabled = _get_env_bool("CACHE_ENABLED", source_config.cache_enabled)
                if "cache_ttl" not in config_dict:
                    source_config.cache_ttl = _get_env_int("CACHE_TTL", source_config.cache_ttl)
                # 国际金融数据源使用默认的rate_limit设置
                self.data_sources[source_name] = InternationalFinanceAdapter(source_config)

            else:
                logger.error(f"Unsupported data source type: {source_type}")
                return False
            
            logger.info(f"Added data source: {source_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add data source {source_type}: {e}")
            return False
    
    def set_primary_source(self, source_name: str) -> bool:
        """
        设置主数据源
        
        Args:
            source_name: 数据源名称
            
        Returns:
            是否设置成功
        """
        if source_name not in self.data_sources:
            logger.error(f"Data source {source_name} not found")
            return False
        
        self.primary_source = source_name
        logger.info(f"Primary data source set to: {source_name}")
        return True
    
    def add_fallback_source(self, source_name: str) -> bool:
        """
        添加备用数据源
        
        Args:
            source_name: 数据源名称
            
        Returns:
            是否添加成功
        """
        if source_name not in self.data_sources:
            logger.error(f"Data source {source_name} not found")
            return False
        
        if source_name not in self.fallback_sources:
            self.fallback_sources.append(source_name)
            logger.info(f"Added fallback data source: {source_name}")
        
        return True
    
    def get_data_source(self, source_name: str) -> Optional[BaseDataSource]:
        """获取指定数据源"""
        return self.data_sources.get(source_name)
    
    def list_data_sources(self) -> List[str]:
        """获取所有数据源名称"""
        return list(self.data_sources.keys())
    
    async def check_availability(self) -> Dict[str, bool]:
        """检查所有数据源可用性"""
        availability = {}
        for name, source in self.data_sources.items():
            try:
                availability[name] = await source.is_available()
                logger.info(f"Data source {name} availability: {availability[name]}")
            except Exception as e:
                availability[name] = False
                logger.error(f"Failed to check availability for {name}: {e}")
        
        return availability
    
    async def _execute_with_fallback(self, method_name: str, *args, **kwargs) -> DataResponse:
        """
        使用主数据源执行方法，失败时尝试备用数据源
        
        Args:
            method_name: 方法名称
            *args, **kwargs: 方法参数
            
        Returns:
            数据响应
        """
        # 确定数据源顺序
        sources_to_try = []
        if self.primary_source and self.primary_source in self.data_sources:
            sources_to_try.append(self.primary_source)
        
        for fallback in self.fallback_sources:
            if fallback != self.primary_source and fallback in self.data_sources:
                sources_to_try.append(fallback)
        
        # 如果没有配置主数据源，使用所有可用的数据源
        if not sources_to_try:
            sources_to_try = list(self.data_sources.keys())
        
        last_error = None
        
        for source_name in sources_to_try:
            try:
                source = self.data_sources[source_name]
                method = getattr(source, method_name)
                
                logger.debug(f"Trying {method_name} with {source_name}")
                response = await method(*args, **kwargs)
                
                if response.error is None:
                    logger.info(f"Successfully got data from {source_name}")
                    return response
                else:
                    logger.warning(f"Data source {source_name} returned error: {response.error}")
                    last_error = response.error
                    
            except Exception as e:
                logger.error(f"Failed to execute {method_name} with {source_name}: {e}")
                last_error = str(e)
        
        # 所有数据源都失败了
        logger.error(f"All data sources failed for {method_name}")
        return DataResponse(
            data=None,
            source="manager",
            error=f"All data sources failed. Last error: {last_error}",
            metadata={"method": method_name, "attempted_sources": sources_to_try}
        )
    
    async def get_stock_basic(self, **kwargs) -> DataResponse:
        """获取股票基本信息"""
        return await self._execute_with_fallback("get_stock_basic", **kwargs)
    
    async def get_stock_daily(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取股票日线数据"""
        return await self._execute_with_fallback("get_stock_daily", symbol, start_date, end_date, **kwargs)

    async def get_fund_daily(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取基金/ETF日线数据"""
        return await self._execute_with_fallback("get_fund_daily", symbol, start_date, end_date, **kwargs)

    async def get_stock_realtime(self, symbols: List[str], **kwargs) -> DataResponse:
        """获取股票实时数据"""
        return await self._execute_with_fallback("get_stock_realtime", symbols, **kwargs)

    async def get_repo_rate(self, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取回购利率（日频）"""
        return await self._execute_with_fallback("get_repo_rate", start_date, end_date, **kwargs)

    async def get_money_supply(self, start_month: str, end_month: str, **kwargs) -> DataResponse:
        """获取货币供应量（月度）"""
        return await self._execute_with_fallback("get_money_supply", start_month, end_month, **kwargs)

    async def get_social_financing(self, start_month: str, end_month: str, **kwargs) -> DataResponse:
        """获取社会融资规模（月度）"""
        return await self._execute_with_fallback("get_social_financing", start_month, end_month, **kwargs)

    async def get_gdp_data(self, start_quarter: str, end_quarter: str, **kwargs) -> DataResponse:
        """获取国内生产总值（季度）"""
        return await self._execute_with_fallback("get_gdp_data", start_quarter, end_quarter, **kwargs)

    async def get_pmi_data(self, start_month: str, end_month: str, **kwargs) -> DataResponse:
        """获取PMI及分项数据"""
        return await self._execute_with_fallback("get_pmi_data", start_month, end_month, **kwargs)

    async def get_ppi_data(self, start_month: str, end_month: str, **kwargs) -> DataResponse:
        """获取PPI数据"""
        return await self._execute_with_fallback("get_ppi_data", start_month, end_month, **kwargs)

    async def get_cpi_data(self, start_month: str, end_month: str, **kwargs) -> DataResponse:
        """获取CPI数据"""
        return await self._execute_with_fallback("get_cpi_data", start_month, end_month, **kwargs)
    
    async def get_index_daily(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取指数日线数据"""
        return await self._execute_with_fallback("get_index_daily", symbol, start_date, end_date, **kwargs)
    
    async def get_financial_data(self, symbol: str, **kwargs) -> DataResponse:
        """获取财务数据"""
        return await self._execute_with_fallback("get_financial_data", symbol, **kwargs)
    
    async def batch_get_stock_daily(self, symbols: List[str], start_date: str, end_date: str, **kwargs) -> Dict[str, DataResponse]:
        """批量获取股票日线数据"""
        results = {}
        
        for symbol in symbols:
            try:
                response = await self.get_stock_daily(symbol, start_date, end_date, **kwargs)
                results[symbol] = response
                logger.debug(f"Got daily data for {symbol}")
            except Exception as e:
                logger.error(f"Failed to get daily data for {symbol}: {e}")
                results[symbol] = DataResponse(
                    data=None,
                    source="manager",
                    error=str(e),
                    metadata={"method": "batch_get_stock_daily", "symbol": symbol}
                )
        
        return results

    async def get_forex_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        **kwargs
    ) -> DataResponse:
        """获取汇率数据

        专门用于获取国际汇率数据，支持美元指数DXY、USD/CNY、USD/CNH等

        Args:
            symbol: 汇率代码 (如 'DXY', 'USDCNY', 'USDCNH')
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD

        Returns:
            DataResponse: 汇率数据响应
        """
        # 优先使用国际金融数据源
        if "international_finance" in self.data_sources:
            try:
                source = self.data_sources["international_finance"]
                response = await source.get_forex_data(symbol, start_date, end_date, **kwargs)
                if response.data is not None:
                    return response
                logger.warning(f"国际金融数据源获取汇率 {symbol} 失败: {response.error}")
            except Exception as e:
                logger.error(f"国际金融数据源异常: {e}")

        # 回退到常规股票数据接口（某些汇率ETF）
        return await self.get_stock_daily(symbol, start_date, end_date, **kwargs)

    async def get_bond_yield_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        **kwargs
    ) -> DataResponse:
        """获取国债收益率数据

        支持美国10年期国债、中国10年期国债、中国国开债等

        Args:
            symbol: 国债代码 (如 'US10Y', 'CN10Y', 'CN10Y_CDB')
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD

        Returns:
            DataResponse: 国债收益率数据响应
        """
        # 优先使用国际金融数据源
        if "international_finance" in self.data_sources:
            try:
                source = self.data_sources["international_finance"]
                response = await source.get_bond_yield_data(symbol, start_date, end_date, **kwargs)
                if response.data is not None:
                    return response
                logger.warning(f"国际金融数据源获取国债 {symbol} 失败: {response.error}")
            except Exception as e:
                logger.error(f"国际金融数据源异常: {e}")

        # 回退到债券ETF代理
        from datetime import datetime
        from .config.indices_config import BOND_YIELDS

        if symbol in [config["symbol"] for config in BOND_YIELDS.values()]:
            for bond_name, config in BOND_YIELDS.items():
                if config["symbol"] == symbol and "proxy_etf" in config:
                    proxy_etf = config["proxy_etf"]
                    logger.info(f"使用债券ETF代理获取 {symbol}: {proxy_etf}")
                    return await self.get_stock_daily(proxy_etf, start_date, end_date, **kwargs)

        return DataResponse(
            data=None,
            source="manager",
            error=f"无法获取国债收益率数据: {symbol}",
            timestamp=datetime.now()
        )

    async def batch_get_background_scan_120d_data(
        self,
        start_date: str,
        end_date: str,
        **kwargs
    ) -> Dict[str, DataResponse]:
        """批量获取120背景扫描所需的完整数据

        包括汇率、国债收益率、股票指数、商品数据等
        确保AI_EXECUTION_WORKFLOW.md要求的所有观察标的都能获取到

        Args:
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD

        Returns:
            Dict[str, DataResponse]: 各类资产的数据响应
        """
        import asyncio
        from datetime import datetime
        from .config.indices_config import BACKGROUND_SCAN_120D_CONFIG

        results = {}
        config = BACKGROUND_SCAN_120D_CONFIG["required_assets"]

        # 获取汇率数据
        forex_tasks = []
        for symbol in config["forex"]["priority_1"]:
            task = self.get_forex_data(symbol, start_date, end_date, **kwargs)
            forex_tasks.append((f"forex_{symbol}", task))

        # 获取国债收益率数据
        bond_tasks = []
        for symbol in config["bond_yields"]["priority_1"]:
            task = self.get_bond_yield_data(symbol, start_date, end_date, **kwargs)
            bond_tasks.append((f"bond_{symbol}", task))

        # 获取A股指数数据
        stock_tasks = []
        for symbol in config["indices"]["a_share"]:
            task = self.get_stock_daily(symbol, start_date, end_date, **kwargs)
            stock_tasks.append((f"stock_{symbol}", task))

        # 获取商品数据
        commodity_tasks = []
        def _is_etf_symbol(symbol: str) -> bool:
            normalized = symbol.replace('.SH', '').replace('.SZ', '')
            return normalized.isdigit()

        for metals_symbol in config["commodities"]["metals"]:
            if _is_etf_symbol(metals_symbol):
                task = self.get_fund_daily(metals_symbol, start_date, end_date, **kwargs)
            else:
                task = self.get_stock_daily(metals_symbol, start_date, end_date, **kwargs)
            commodity_tasks.append((f"commodity_{metals_symbol}", task))

        for energy_symbol in config["commodities"].get("energy", []):
            if _is_etf_symbol(energy_symbol):
                task = self.get_fund_daily(energy_symbol, start_date, end_date, **kwargs)
            else:
                task = self.get_stock_daily(energy_symbol, start_date, end_date, **kwargs)
            commodity_tasks.append((f"commodity_{energy_symbol}", task))

        for metal_symbol in config["commodities"].get("base_metals", []):
            if _is_etf_symbol(metal_symbol):
                task = self.get_fund_daily(metal_symbol, start_date, end_date, **kwargs)
            else:
                task = self.get_stock_daily(metal_symbol, start_date, end_date, **kwargs)
            commodity_tasks.append((f"commodity_{metal_symbol}", task))

        # 并发执行所有任务
        all_tasks = forex_tasks + bond_tasks + stock_tasks + commodity_tasks
        task_results = await asyncio.gather(
            *[task for _, task in all_tasks],
            return_exceptions=True
        )

        # 组织结果
        for (name, _), result in zip(all_tasks, task_results):
            if isinstance(result, Exception):
                results[name] = DataResponse(
                    data=None,
                    source="manager",
                    error=f"批量获取数据异常: {str(result)}",
                    timestamp=datetime.now()
                )
            else:
                results[name] = result

        return results

    async def get_hsgt_flow(self, symbol: str = '北向资金', **kwargs) -> DataResponse:
        """获取沪深港通资金流向数据

        Args:
            symbol: '北向资金' 或 '南向资金'

        Returns:
            DataResponse: 资金流向数据响应
        """
        # 暂无直接数据源，返回缺口提示（需 MCP/WebSearch 补齐）
        from datetime import datetime
        return DataResponse(
            data=None,
            source="manager",
            error=f"无法获取{symbol}数据，建议使用MCP WebSearch补充",
            timestamp=datetime.now(),
            metadata={"fallback_required": True, "mcp_search_query": f"{symbol} 净流入 2025"}
        )

    async def get_margin_summary(
        self,
        start_date: str,
        end_date: str,
        exchange: str = 'both',
        **kwargs
    ) -> DataResponse:
        """获取融资融券汇总数据

        Args:
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            exchange: 'sse'(上交所), 'szse'(深交所), 'both'(合并)

        Returns:
            DataResponse: 融资融券汇总数据响应
        """
        # 优先使用TuShare
        if "tushare" in self.data_sources:
            try:
                source = self.data_sources["tushare"]
                response = await source.get_margin_total(start_date, end_date, exchange, **kwargs)
                data = getattr(response, "data", None)
                if data is not None and (not hasattr(data, "empty") or not data.empty):
                    logger.info(f"Successfully fetched margin data from TuShare: {len(data)} records")
                    return response
                logger.warning("TuShare获取融资融券失败或返回空集")
            except Exception as e:
                logger.error(f"TuShare margin异常: {e}")

        # 若 TuShare 无数据，返回缺口提示（需 MCP/WebSearch 补充）
        from datetime import datetime
        return DataResponse(
            data=None,
            source="manager",
            error=f"无法获取融资融券数据，建议使用MCP WebSearch补充",
            timestamp=datetime.now(),
            metadata={"fallback_required": True, "mcp_search_query": f"A股融资融券余额 {end_date}"}
        )

    async def batch_get_fund_flow_data(
        self,
        start_date: str,
        end_date: str,
        **kwargs
    ) -> Dict[str, DataResponse]:
        """批量获取资金流向数据（北向、南向、融资融券）

        Args:
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD

        Returns:
            Dict[str, DataResponse]: 包含各类资金流向数据
        """
        import asyncio
        from datetime import datetime

        results = {}

        tasks = [
            ("northbound", self.get_hsgt_flow('北向资金', **kwargs)),
            ("southbound", self.get_hsgt_flow('南向资金', **kwargs)),
            ("margin", self.get_margin_summary(start_date, end_date, 'both', **kwargs))
        ]

        task_results = await asyncio.gather(
            *[task for _, task in tasks],
            return_exceptions=True
        )

        for (name, _), result in zip(tasks, task_results):
            if isinstance(result, Exception):
                results[name] = DataResponse(
                    data=None,
                    source="manager",
                    error=f"批量获取{name}数据异常: {str(result)}",
                    timestamp=datetime.now()
                )
            else:
                results[name] = result

        return results

    async def get_daily_market_info(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        exchange: str = '',
        trade_date: Optional[str] = None,
        **kwargs
    ) -> DataResponse:
        """获取交易所每日交易统计（TuShare daily_info）"""
        if "tushare" in self.data_sources:
            try:
                source = self.data_sources["tushare"]
                response = await source.get_daily_market_info(
                    start_date=start_date,
                    end_date=end_date,
                    exchange=exchange,
                    trade_date=trade_date,
                    **kwargs
                )
                data = getattr(response, "data", None)
                if data is not None and (not hasattr(data, "empty") or not data.empty):
                    return response
                logger.warning("TuShare daily_info 返回空数据")
            except Exception as e:
                logger.error(f"TuShare daily_info 调用异常: {e}")

        from datetime import datetime
        return DataResponse(
            data=None,
            source="manager",
            error="无法获取交易所成交统计，需MCP WebSearch或人工补数",
            timestamp=datetime.now(),
            metadata={"fallback_required": True, "mcp_search_query": f"上交所 深交所 成交额 {end_date or trade_date or ''}"}
        )

    def get_status(self) -> Dict[str, Any]:
        """获取管理器状态"""
        return {
            "data_sources": list(self.data_sources.keys()),
            "primary_source": self.primary_source,
            "fallback_sources": self.fallback_sources,
            "total_sources": len(self.data_sources)
        }


# 单例管理器实例
_manager_instance = None


def get_manager(config_file: Optional[str] = None) -> DataSourceManager:
    """获取数据源管理器单例"""
    global _manager_instance
    
    if _manager_instance is None:
        _manager_instance = DataSourceManager(config_file)
        
        # 根据环境变量灵活开关数据源
        disable_tushare = _get_env_bool("DISABLE_TUSHARE", False)
        disable_international = _get_env_bool("DISABLE_INTERNATIONAL_FINANCE", False)

        if not disable_tushare:
            _manager_instance.add_data_source(DataSourceType.TUSHARE)
        else:
            logger.warning("TuShare data source disabled via DISABLE_TUSHARE")

        if not disable_international:
            _manager_instance.add_data_source(
                DataSourceType.INTERNATIONAL_FINANCE,
                {"name": "international_finance"}
            )
        else:
            logger.warning("International finance data source disabled via DISABLE_INTERNATIONAL_FINANCE")

        # 设置主数据源和备用顺序（按优先级）
        preferred_order: List[str] = ["tushare", "international_finance"]
        available_sources = [name for name in preferred_order if name in _manager_instance.data_sources]

        if available_sources:
            _manager_instance.set_primary_source(available_sources[0])
            for fallback_source in available_sources[1:]:
                _manager_instance.add_fallback_source(fallback_source)
        else:
            logger.warning("No data sources configured; manager will operate without backends")

    return _manager_instance


async def initialize_default_manager(config_file: Optional[str] = None) -> DataSourceManager:
    """初始化默认管理器并检查可用性"""
    manager = get_manager(config_file)
    
    # 检查数据源可用性
    availability = await manager.check_availability()
    logger.info(f"Data sources availability: {availability}")
    
    return manager
