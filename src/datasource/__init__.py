"""
DataSource: 统一的金融数据源集成框架

- 适配器：TuShare（统一接口，带限流/缓存/重试/故障转移）
- 管理器：主/备源调度与状态查询
- 引擎/计算：技术指标、资金流向、债券收益率、普林格六阶段
"""

try:  # pragma: no cover - 运行环境可能缺失系统 DNS 配置
    from .utils.dns_patch import apply_dns_patch

    apply_dns_patch()
except Exception:
    pass

from .manager import DataSourceManager, DataSourceType, get_manager, initialize_default_manager
from .models.base import BaseDataSource, DataSourceConfig, DataRequest, DataResponse
from .adapters.tushare_adapter import TuShareAdapter, TuShareConfig
from .adapters.international_finance_adapter import InternationalFinanceAdapter, InternationalFinanceConfig

__version__ = "1.0.0"
__author__ = "DataSource Team"

__all__ = [
    "DataSourceManager",
    "DataSourceType",
    "get_manager",
    "initialize_default_manager",
    "BaseDataSource",
    "DataSourceConfig",
    "DataRequest",
    "DataResponse",
    "TuShareAdapter",
    "TuShareConfig",
    "InternationalFinanceAdapter",
    "InternationalFinanceConfig",
]
