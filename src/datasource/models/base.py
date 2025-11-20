from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
import pandas as pd
from pydantic import BaseModel, Field


class DataSourceConfig(BaseModel):
    """数据源配置基类"""
    name: str
    rate_limit: int = 10
    timeout: int = 30
    retry_count: int = 3
    cache_enabled: bool = True
    cache_ttl: int = 300


class DataRequest(BaseModel):
    """数据请求模型"""
    symbol: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    period: Optional[str] = None
    fields: Optional[List[str]] = None
    extra_params: Dict[str, Any] = Field(default_factory=dict)


class DataResponse(BaseModel):
    """数据响应模型"""
    data: Optional[pd.DataFrame] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source: str
    timestamp: datetime = Field(default_factory=datetime.now)
    error: Optional[str] = None
    
    class Config:
        arbitrary_types_allowed = True


class BaseDataSource(ABC):
    """数据源基类"""
    
    def __init__(self, config: DataSourceConfig):
        self.config = config
        self.name = config.name
        
    @abstractmethod
    async def get_stock_basic(self, **kwargs) -> DataResponse:
        """获取股票基本信息"""
        pass
    
    @abstractmethod 
    async def get_stock_daily(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取股票日线数据"""
        pass

    async def get_fund_daily(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取基金/ETF日线数据，默认回退至股票日线接口"""
        return await self.get_stock_daily(symbol, start_date, end_date, **kwargs)

    @abstractmethod
    async def get_stock_realtime(self, symbols: List[str], **kwargs) -> DataResponse:
        """获取股票实时数据"""
        pass
    
    @abstractmethod
    async def get_index_daily(self, symbol: str, start_date: str, end_date: str, **kwargs) -> DataResponse:
        """获取指数日线数据"""
        pass
    
    @abstractmethod
    async def get_financial_data(self, symbol: str, **kwargs) -> DataResponse:
        """获取财务数据"""
        pass
    
    @abstractmethod
    async def is_available(self) -> bool:
        """检查数据源是否可用"""
        pass
