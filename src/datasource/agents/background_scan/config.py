"""
Background Scan Agent Configuration
120日背景扫描代理配置模块
"""

from typing import Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class BackgroundScanConfig:
    """120日背景扫描配置类"""
    
    # 基础配置
    scan_period_days: int = 120
    report_title: str = "120日市场背景扫描报告"
    
    # 数据源配置
    primary_data_source: str = "tushare"
    fallback_data_source: str = "websearch"
    web_search_enabled: bool = True
    
    # 标的配置
    a_share_indices: Dict[str, Dict[str, str]] = field(default_factory=lambda: {
        "沪深300": {"symbol": "000300", "display": "沪深300(000300)", "market": "A股"},
        "上证50": {"symbol": "000016", "display": "上证50(000016)", "market": "A股"},
        "创业板指": {"symbol": "399006", "display": "创业板指(399006)", "market": "A股"},
        "中证500": {"symbol": "000905", "display": "中证500(000905)", "market": "A股"},
        "上证指数": {"symbol": "000001", "display": "上证指数(000001)", "market": "A股"},
        "深证成指": {"symbol": "399001", "display": "深证成指(399001)", "market": "A股"}
    })
    
    commodities: Dict[str, Dict[str, str]] = field(default_factory=lambda: {
        "WTI原油": {"symbol": "CL", "display": "WTI原油(美元/桶)", "type": "能源"},
        "Brent原油": {"symbol": "BZ", "display": "Brent原油(美元/桶)", "type": "能源"},
        "COMEX铜": {"symbol": "HG", "display": "COMEX铜(美元/磅)", "type": "工业金属"},
        "COMEX黄金": {"symbol": "GC", "display": "COMEX黄金(美元/盎司)", "type": "贵金属"},
        "CBOT大豆": {"symbol": "ZS", "display": "CBOT大豆(美分/蒲式耳)", "type": "农产品"}
    })
    
    currencies: Dict[str, Dict[str, str]] = field(default_factory=lambda: {
        "美元指数": {"symbol": "DXY", "display": "美元指数(DXY)", "type": "指数"},
        "USD/CNH": {"symbol": "USDCNH", "display": "USD/CNH离岸", "type": "汇率"},
        "USD/CNY": {"symbol": "USDCNY", "display": "USD/CNY在岸", "type": "汇率"},
        "EUR/USD": {"symbol": "EURUSD", "display": "EUR/USD", "type": "汇率"},
        "GBP/USD": {"symbol": "GBPUSD", "display": "GBP/USD", "type": "汇率"},
        "AUD/USD": {"symbol": "AUDUSD", "display": "AUD/USD", "type": "汇率"}
    })
    
    bonds: Dict[str, Dict[str, str]] = field(default_factory=lambda: {
        "美国10年期": {"symbol": "US10Y", "display": "美国10年期国债", "type": "国债"},
        "中国10年期": {"symbol": "CN10Y", "display": "中国10年期国债", "type": "国债"},
        "中国10年期国开": {"symbol": "CN10Y_CDB", "display": "中国10年期国开债", "type": "政策性金融债"},
        "德国10年期": {"symbol": "DE10Y", "display": "德国10年期国债", "type": "国债"},
        "日本10年期": {"symbol": "JP10Y", "display": "日本10年期国债", "type": "国债"}
    })
    
    # 技术指标配置
    technical_params: Dict[str, Any] = field(default_factory=lambda: {
        "ma_periods": [20, 50, 200],
        "volatility_window": 30,
        "slope_period": 10,
        "trend_score_thresholds": {
            "bullish": 1,
            "bearish": -1
        }
    })
    
    # 普林格分析配置
    pring_config: Dict[str, Any] = field(default_factory=lambda: {
        "bond_weight": 0.3,
        "stock_weight": 0.4,
        "commodity_weight": 0.3,
        "confidence_threshold": 0.7
    })
    
    # 输出配置
    output_config: Dict[str, Any] = field(default_factory=lambda: {
        "decimal_places": {
            "percentage": 2,
            "basis_points": 1,
            "price": 2,
            "slope": 4
        },
        "na_indicators": {
            "insufficient_data": "N/A(样本不足)",
            "calculation_error": "N/A(计算错误)",
            "data_unavailable": "N/A(数据不可用)"
        }
    })
    
    # 文件路径配置
    paths: Dict[str, str] = field(default_factory=lambda: {
        "templates_dir": "src/datasource/agents/background_scan/templates",
        "output_dir": "reports",
        "cache_dir": "data/cache"
    })
    
    def get_date_range(self, end_date: str = None) -> tuple:
        """
        获取数据时间范围
        
        Args:
            end_date: 结束日期，格式YYYY-MM-DD，默认为今天
            
        Returns:
            (start_date, end_date) 元组
        """
        if end_date is None:
            end_dt = datetime.now()
        else:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        start_dt = end_dt - timedelta(days=self.scan_period_days)
        
        return start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")
    
    def get_all_symbols(self) -> List[str]:
        """获取所有需要分析的标的代码"""
        symbols = []
        
        # A股指数
        symbols.extend([config["symbol"] for config in self.a_share_indices.values()])
        
        # 其他资产类别可以根据需要添加
        # symbols.extend([config["symbol"] for config in self.commodities.values()])
        # symbols.extend([config["symbol"] for config in self.currencies.values()])
        # symbols.extend([config["symbol"] for config in self.bonds.values()])
        
        return symbols
    
    def get_output_filename(self, date: str = None) -> str:
        """
        生成输出文件名
        
        Args:
            date: 日期字符串，格式YYYY-MM-DD
            
        Returns:
            输出文件名
        """
        if date is None:
            date = datetime.now().strftime("%Y%m%d")
        else:
            date = date.replace("-", "")
        
        return f"{date}背景扫描120日.md"
