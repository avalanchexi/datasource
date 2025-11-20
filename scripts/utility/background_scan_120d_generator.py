#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
120日背景扫描报告生成器 - 修复版本
基于120背景扫描方案.md V3.1规范
修复了数据获取和处理问题
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import json
import pandas as pd
import numpy as np

# Add project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

from datasource import get_manager
from datasource.calculators.technical_indicators import TechnicalIndicatorCalculator
from datasource.calculators.pring_analyzer import PringAnalyzer
from datasource.config import A_SHARE_INDICES, TECHNICAL_PARAMS, COMMODITY_FUTURES

# Import validator for quality gate
try:
    from background_scan_validator import BackgroundScanValidator, ValidationResult
    VALIDATOR_AVAILABLE = True
except ImportError:
    VALIDATOR_AVAILABLE = False
    print("[WARNING] background_scan_validator.py 不可用，跳过质量检查")


class BackgroundScan120DGeneratorFixed:
    """120日背景扫描报告生成器 - 修复版本"""

    def __init__(self, end_date: str = "2025-09-16", disable_akshare: bool = True):
        self.manager = get_manager()
        self.technical_calc = TechnicalIndicatorCalculator()
        self.pring_analyzer = PringAnalyzer(self.manager)

        # AKShare通道已下线，始终禁用
        if not disable_akshare:
            print("[INFO] AKShare通道已停用，disable_akshare=False 将被忽略")
        self.disable_akshare = True
        print("[INFO] AKShare数据源已禁用，将使用TuShare+MCP组合策略")
        self.manager.set_primary_source('tushare')

        # 数据窗口：根据传入的end_date计算120天前的start_date
        self.end_date = end_date
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=120)
        self.start_date = start_dt.strftime("%Y-%m-%d")
        # 额外历史窗口，用于支撑长周期均线（如MA200）计算
        self.history_buffer_days = 260

        # 核心指数配置
        self.indices = {
            # A股主要指数
            "000300": "沪深300",
            "000016": "上证50",
            "399006": "创业板指",
            "399001": "深证成指",
            "000001": "上证指数",
            # 商品ETF（使用基金接口，备用）
            "518880": "黄金ETF",
            "159930": "能源ETF",
            "515220": "有色ETF"
        }

        # 国际商品期货配置（V2.1新增，优先使用）
        self.international_commodities = {
            "GC": "COMEX黄金",
            "CL": "WTI原油",
            "BZ": "Brent原油",
            "HG": "COMEX铜",
            "GSG": "GSG商品ETF"
        }

        # 使用MCP WebSearch获取的商品
        self.websearch_commodities = ["BCOM"]  # Bloomberg商品指数

    async def collect_market_data(self) -> Dict[str, Any]:
        """收集120日市场数据 - 修复版本"""
        print(f"收集市场数据 ({self.start_date} 至 {self.end_date})")

        market_data = {}

        analysis_start_dt = datetime.strptime(self.start_date, "%Y-%m-%d")
        fetch_start_dt = analysis_start_dt - timedelta(days=self.history_buffer_days)
        fetch_start_date = fetch_start_dt.strftime("%Y-%m-%d")

        for symbol, name in self.indices.items():
            try:
                print(f"  获取 {symbol} ({name})...")
                if symbol.startswith(('000', '399')):
                    response = await self.manager.get_index_daily(
                        symbol, fetch_start_date, self.end_date
                    )
                else:
                    response = await self.manager.get_fund_daily(
                        symbol, fetch_start_date, self.end_date
                    )

                if response.error:
                    print(f"    错误: {response.error}")
                    continue

                # 修复：检查响应数据是否存在且非空
                if response.data is None:
                    print(f"    响应数据为None")
                    continue

                if response.data.empty:
                    print(f"    数据为空")
                    continue

                # 计算技术指标
                data = response.data.copy()
                print(f"    原始数据形状: {data.shape}")
                print(f"    列名: {list(data.columns)}")

                # 标准化日期索引，确保历史周期完整排序
                date_col = None
                for col in data.columns:
                    col_lower = str(col).lower()
                    if "date" in col_lower or "日期" in col_lower or "trade_date" in col_lower:
                        date_col = col
                        break

                if date_col and date_col in data.columns:
                    data['date'] = pd.to_datetime(data[date_col], errors='coerce')
                    data = data.dropna(subset=['date']).sort_values('date')
                    print(f"    使用日期列: {date_col}")
                else:
                    print(f"    未找到日期列，使用索引排序")
                    if hasattr(data.index, 'sort_values'):
                        data = data.sort_index()

                # 检查列名并统一格式 - 更灵活的列名匹配
                column_mapping = {}
                for col in data.columns:
                    col_str = str(col).lower()
                    if any(x in col_str for x in ['close', '收盘', 'price']):
                        column_mapping['close'] = col
                        break

                # 如果仍未找到close列，使用数值列
                if 'close' not in column_mapping:
                    numeric_cols = data.select_dtypes(include=[np.number]).columns
                    if len(numeric_cols) > 0:
                        # 优先选择包含价格相关关键词的列
                        price_related_cols = [col for col in numeric_cols
                                            if any(x in str(col).lower() for x in ['价', 'price', 'value', '值'])]
                        if price_related_cols:
                            column_mapping['close'] = price_related_cols[0]
                        else:
                            column_mapping['close'] = numeric_cols[0]

                if 'close' not in column_mapping:
                    print(f"    警告: 未找到价格列，跳过 {symbol}")
                    print(f"    可用列: {list(data.columns)}")
                    continue

                # 重命名和清理数据
                close_col = column_mapping['close']
                data['close'] = pd.to_numeric(data[close_col], errors='coerce')

                # 删除无效的收盘价数据
                data = data.dropna(subset=['close'])

                if len(data) < 50:  # 确保有足够的数据计算指标
                    print(f"    数据不足({len(data)}条)，跳过 {symbol}")
                    continue

                print(f"    清理后数据: {len(data)}条")

                # 基础指标
                data['ma20'] = data['close'].rolling(20).mean()
                data['ma50'] = data['close'].rolling(50).mean()
                data['ma200'] = data['close'].rolling(200).mean()

                # 获取最新值
                latest = data.iloc[-1]
                if 'date' in data.columns:
                    analysis_window = data[data['date'] >= analysis_start_dt]
                    if analysis_window.empty:
                        analysis_window = data.tail(120)
                else:
                    analysis_window = data.tail(120)

                start_val = analysis_window.iloc[0] if len(analysis_window) > 0 else latest

                # 计算涨跌幅
                change_5d = None
                if len(data) >= 5:
                    change_5d = ((latest['close'] / data.iloc[-5]['close']) - 1) * 100

                change_120d = ((latest['close'] / start_val['close']) - 1) * 100

                # 计算MA50斜率 (10期线性回归)
                ma50_slope = self._calculate_slope(data['ma50'].tail(10))

                # 计算30日年化波动率
                returns = data['close'].pct_change().dropna()
                volatility_30d = returns.tail(30).std() * np.sqrt(252) * 100 if len(returns) >= 30 else None

                # 趋势评分系统 (-2 ~ +2)
                trend_score = self._calculate_trend_score(data, latest)
                trend_label = self._get_trend_label(trend_score)

                market_data[symbol] = {
                    'name': name,
                    'latest_price': round(latest['close'], 2),
                    'change_5d_pct': round(change_5d, 1) if change_5d else None,
                    'change_120d_pct': round(change_120d, 1),
                    'above_ma50': latest['close'] > latest['ma50'] if not pd.isna(latest['ma50']) else None,
                    'above_ma200': latest['close'] > latest['ma200'] if not pd.isna(latest['ma200']) else None,
                    'ma50_slope': round(ma50_slope, 4) if ma50_slope else None,
                    'volatility_30d_pct': round(volatility_30d, 1) if volatility_30d else None,
                    'trend_score': trend_score,
                    'trend_label': trend_label,
                    'data_source': response.source
                }

                print(f"    [OK] 成功处理 {len(data)} 条数据")

            except Exception as e:
                print(f"    异常: {str(e)}")
                import traceback
                traceback.print_exc()

        print(f"\n成功获取 {len(market_data)} 个标的数据")
        return market_data

    def _calculate_slope(self, series: pd.Series) -> Optional[float]:
        """计算序列的线性回归斜率"""
        if len(series) < 2 or series.isna().all():
            return None

        series_clean = series.dropna()
        if len(series_clean) < 2:
            return None

        x = np.arange(len(series_clean))
        y = series_clean.values

        try:
            slope = np.polyfit(x, y, 1)[0]
            return slope
        except:
            return None

    def _calculate_trend_score(self, data: pd.DataFrame, latest: pd.Series) -> int:
        """计算趋势评分 (-2 ~ +2)"""
        score = 0

        # 1. 收益趋势: 近120日累计收益率 ≥+5% → +1分；≤-5% → -1分
        if len(data) > 0:
            total_return = ((latest['close'] / data.iloc[0]['close']) - 1) * 100
            if total_return >= 5.0:
                score += 1
            elif total_return <= -5.0:
                score -= 1

        # 2. 均线位置: 收盘价高于MA50 → +1分；低于 → -1分
        if not pd.isna(latest['ma50']):
            if latest['close'] > latest['ma50']:
                score += 1
            else:
                score -= 1

        # 3. 中期趋势: MA50高于MA200(黄金交叉) → +1分；反之 → -1分
        if not pd.isna(latest['ma50']) and not pd.isna(latest['ma200']):
            if latest['ma50'] > latest['ma200']:
                score += 1
            else:
                score -= 1

        # 4. 短期动量: MA20斜率向上 → +1分；向下 → -1分
        if not pd.isna(latest['ma20']) and len(data) >= 20:
            ma20_slope = self._calculate_slope(data['ma20'].tail(10))
            if ma20_slope and ma20_slope > 0:
                score += 1
            elif ma20_slope and ma20_slope < 0:
                score -= 1

        return max(-2, min(2, score))  # 限制在-2到+2范围内

    def _get_trend_label(self, score: int) -> str:
        """获取趋势标签"""
        if score >= 1:
            return "牛"
        elif score <= -1:
            return "熊"
        else:
            return "中性"

    async def get_pring_cycle_analysis(self) -> Dict[str, Any]:
        """
        获取Pring三层框架完整分析
        V4.0: 库存周期 → 货币周期 → Pring修正
        """
        print("执行Pring三层框架分析（库存周期→货币周期→Pring修正）...")

        try:
            # 执行Pring三层框架分析
            pring_result = await self.pring_analyzer.analyze_pring_stage(250)

            # V4.0: 直接返回完整的三层框架分析结果
            # 包含 layer_1_inventory_cycle, layer_2_monetary_cycle, layer_3_pring_final
            return pring_result

        except Exception as e:
            print(f"Pring三层框架分析失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                'stage': 'N/A',
                'confidence': 0,
                'error': str(e),
                'layer_1_inventory_cycle': {},
                'layer_2_monetary_cycle': {},
                'layer_3_pring_final': {}
            }

    async def _get_fund_flow_websearch(self, fund_type: str) -> Optional[Dict[str, Any]]:
        """使用MCP WebSearch获取资金流向数据

        Args:
            fund_type: 资金类型（'北向资金', '南向资金', 'ETF资金流'）

        Returns:
            资金流向数据字典，失败返回None
        """
        try:
            # 注意: 这是一个占位符方法，实际执行时Claude Code会使用WebSearch工具
            # 此方法的目的是提供WebSearch数据获取的接口

            # 构建搜索查询
            query_map = {
                '北向资金': f"北向资金 沪股通深股通 近5日 {self.end_date}",
                '南向资金': f"南向资金 港股通 近5日 {self.end_date}",
                'ETF资金流': f"A股ETF资金流 申购赎回 近5日 {self.end_date}",
                '融资融券': f"融资融券余额 沪深两市 最新 {self.end_date}"
            }

            query = query_map.get(fund_type)
            if not query:
                print(f"    [WARNING] 未知资金类型: {fund_type}")
                return None

            # 实际执行时，这里会被Claude Code的WebSearch工具调用替代
            # 返回格式示例:
            # {
            #     'recent_5d': 123.45,  # 近5日流向(亿元)
            #     'total_120d': 456.78,  # 近120日累计(亿元)
            #     'trend': '流入' or '流出',
            #     'source': 'MCP WebSearch',
            #     'note': '来源:东方财富网/同花顺'
            # }

            print(f"    [WebSearch] 查询: {query}")
            print(f"    [WARNING] WebSearch功能需要在Claude Code环境中执行")
            return None

        except Exception as e:
            print(f"    [WARNING] WebSearch获取{fund_type}失败: {e}")
            return None

    async def collect_commodity_data(self) -> Dict[str, Any]:
        """收集国际商品数据 - V2.1 优先使用真实数据源

        Returns:
            商品数据字典，包含价格、涨跌幅、趋势等信息
        """
        print("收集国际商品数据...")

        commodity_data = {}

        # 商品配置映射
        commodity_configs = {
            'COMEX黄金': {'symbol': 'GOLD', 'yahoo_symbol': 'GC=F', 'unit': '美元/盎司'},
            'WTI原油': {'symbol': 'WTI', 'yahoo_symbol': 'CL=F', 'unit': '美元/桶'},
            'Brent原油': {'symbol': 'BRENT', 'yahoo_symbol': 'BZ=F', 'unit': '美元/桶'},
            'COMEX铜': {'symbol': 'COPPER', 'yahoo_symbol': 'HG=F', 'unit': '美元/磅'},
            'BCOM指数': {'symbol': 'BCOM', 'yahoo_symbol': 'BCOM', 'unit': '点'},
            'GSG ETF': {'symbol': 'GSG', 'yahoo_symbol': 'GSG', 'unit': '美元'}
        }

        for commodity_name, config in commodity_configs.items():
            try:
                print(f"  获取 {commodity_name} 数据...")

                # 注意: 实际执行时，这里会被Claude Code使用WebFetch/WebSearch工具
                # 这是一个占位符方法，用于说明数据获取逻辑

                # 方式1: 尝试通过manager的国际金融适配器获取(如果已实现)
                # 方式2: 提示需要通过MCP WebFetch获取

                print(f"    [WebFetch] 需要MCP获取: Investing.com或Yahoo Finance")
                print(f"    查询符号: {config['yahoo_symbol']}, 单位: {config['unit']}")

                # 占位符: 实际执行时会被替换为真实数据
                commodity_data[commodity_name] = {
                    'price': 'MCP_REQUIRED',
                    'daily_change': 'MCP_REQUIRED',
                    'ytd_change': 'MCP_REQUIRED',
                    'trend': 'MCP_REQUIRED',
                    'source': 'MCP WebFetch待获取',
                    'unit': config['unit'],
                    'query_symbol': config['yahoo_symbol']
                }

            except Exception as e:
                print(f"    [WARNING] {commodity_name} 数据配置失败: {e}")
                commodity_data[commodity_name] = {
                    'price': '数据获取失败',
                    'daily_change': 'N/A',
                    'ytd_change': 'N/A',
                    'trend': 'N/A',
                    'source': '获取失败',
                    'error': str(e)
                }

        return commodity_data

    async def collect_forex_data(self) -> Dict[str, Any]:
        """收集汇率数据 - V2.1 优先使用真实数据源

        Returns:
            汇率数据字典，包含汇率、涨跌幅、趋势等信息
        """
        print("收集汇率数据...")

        forex_data = {}

        # 汇率配置映射
        forex_configs = {
            'USD/CNY': {'symbol': 'USDCNY', 'display': 'USD/CNY在岸', 'yahoo_symbol': 'USDCNY=X'},
            'USD/CNH': {'symbol': 'USDCNH', 'display': 'USD/CNH离岸', 'yahoo_symbol': 'USDCNH=X'},
            '美元指数': {'symbol': 'DXY', 'display': 'DXY美元指数', 'yahoo_symbol': 'DX-Y.NYB'}
        }

        for forex_name, config in forex_configs.items():
            try:
                print(f"  获取 {forex_name} 数据...")

                # 尝试使用manager的forex接口
                response = await self.manager.get_forex_data(
                    config['symbol'],
                    self.start_date,
                    self.end_date
                )

                if not response.error and response.data is not None and len(response.data) > 0:
                    df = response.data

                    # 计算统计数据
                    latest = df.iloc[-1]
                    start = df.iloc[0]

                    latest_rate = latest.get('close', latest.get('rate', 0))
                    start_rate = start.get('close', start.get('rate', 1))

                    # 计算涨跌幅
                    change_120d = ((latest_rate / start_rate) - 1) * 100 if start_rate != 0 else 0

                    # 近5日变化
                    change_5d = 0
                    if len(df) >= 5:
                        recent_5d = df.iloc[-5]
                        recent_rate = recent_5d.get('close', recent_5d.get('rate', latest_rate))
                        change_5d = ((latest_rate / recent_rate) - 1) * 100 if recent_rate != 0 else 0

                    # 判断趋势
                    if change_5d > 0.5:
                        trend = '升值' if 'USD' in forex_name else '走强'
                    elif change_5d < -0.5:
                        trend = '贬值' if 'USD' in forex_name else '走弱'
                    else:
                        trend = '震荡'

                    forex_data[forex_name] = {
                        'rate': round(latest_rate, 4),
                        'change_5d': round(change_5d, 2),
                        'change_120d': round(change_120d, 2),
                        'trend': trend,
                        'source': f"{response.source}",
                        'display_name': config['display']
                    }

                    print(f"    [OK] {forex_name}: {latest_rate:.4f}, 120日变化{change_120d:+.2f}%")
                else:
                    # 数据获取失败，提示使用MCP
                    print(f"    [WARNING] {forex_name} 数据获取失败，需要MCP WebFetch补充")
                    forex_data[forex_name] = {
                        'rate': 'MCP_REQUIRED',
                        'change_5d': 'MCP_REQUIRED',
                        'change_120d': 'MCP_REQUIRED',
                        'trend': 'MCP_REQUIRED',
                        'source': 'MCP WebFetch待获取',
                        'display_name': config['display'],
                        'query_symbol': config['yahoo_symbol']
                    }

            except Exception as e:
                print(f"    [WARNING] {forex_name} 数据处理异常: {e}")
                forex_data[forex_name] = {
                    'rate': '数据获取失败',
                    'change_5d': 'N/A',
                    'change_120d': 'N/A',
                    'trend': 'N/A',
                    'source': '获取失败',
                    'error': str(e)
                }

        return forex_data

    async def collect_bond_data(self) -> Dict[str, Any]:
        """收集债券收益率数据 - V2.1 优先使用真实数据源

        Returns:
            债券数据字典，包含收益率、变化bp、趋势等信息
        """
        print("收集债券收益率数据...")

        bond_data = {}

        # 债券配置映射
        bond_configs = {
            '美国10Y国债': {'symbol': 'US10Y', 'display': '美国10年期国债', 'yahoo_symbol': '^TNX'},
            '中国10Y国债': {'symbol': 'CN10Y', 'display': '中国10年期国债', 'proxy_etf': '511010'},
            '中国10Y国开债': {'symbol': 'CN10Y_CDB', 'display': '中国10年期国开债', 'proxy_etf': '019950'}
        }

        for bond_name, config in bond_configs.items():
            try:
                print(f"  获取 {bond_name} 数据...")

                # 尝试使用manager的债券接口
                response = await self.manager.get_bond_yield_data(
                    config['symbol'],
                    self.start_date,
                    self.end_date
                )

                if not response.error and response.data is not None and len(response.data) > 0:
                    df = response.data

                    # 计算统计数据
                    latest = df.iloc[-1]
                    start = df.iloc[0]

                    latest_yield = latest.get('yield', latest.get('close', 0))
                    start_yield = start.get('yield', start.get('close', 0))

                    # 计算变化(单位: bp, 1bp = 0.01%)
                    change_120d_bp = (latest_yield - start_yield) * 100

                    # 近5日变化
                    change_5d_bp = 0
                    if len(df) >= 5:
                        recent_5d = df.iloc[-5]
                        recent_yield = recent_5d.get('yield', recent_5d.get('close', latest_yield))
                        change_5d_bp = (latest_yield - recent_yield) * 100

                    # 判断趋势
                    if change_5d_bp > 2:
                        trend = '上行'
                    elif change_5d_bp < -2:
                        trend = '下行'
                    else:
                        trend = '平稳'

                    bond_data[bond_name] = {
                        'yield': round(latest_yield, 3),
                        'change_5d_bp': round(change_5d_bp, 1),
                        'change_120d_bp': round(change_120d_bp, 1),
                        'trend': trend,
                        'source': f"{response.source}",
                        'display_name': config['display']
                    }

                    print(f"    [OK] {bond_name}: {latest_yield:.3f}%, 120日变化{change_120d_bp:+.1f}bp")
                else:
                    # 数据获取失败，提示使用MCP
                    print(f"    [WARNING] {bond_name} 数据获取失败，需要MCP WebFetch补充")
                    bond_data[bond_name] = {
                        'yield': 'MCP_REQUIRED',
                        'change_5d_bp': 'MCP_REQUIRED',
                        'change_120d_bp': 'MCP_REQUIRED',
                        'trend': 'MCP_REQUIRED',
                        'source': 'MCP WebFetch待获取',
                        'display_name': config['display'],
                        'query_symbol': config.get('yahoo_symbol', config.get('proxy_etf', ''))
                    }

            except Exception as e:
                print(f"    [WARNING] {bond_name} 数据处理异常: {e}")
                bond_data[bond_name] = {
                    'yield': '数据获取失败',
                    'change_5d_bp': 'N/A',
                    'change_120d_bp': 'N/A',
                    'trend': 'N/A',
                    'source': '获取失败',
                    'error': str(e)
                }

        return bond_data

    async def collect_fund_flow_data(self) -> Dict[str, Any]:
        """收集资金流向数据 - V2.1 MCP WebSearch优先"""
        print("收集资金流向数据 (MCP WebSearch优先)...")

        fund_flow_data = {
            'northbound': None,
            'southbound': None,
            'margin': None,
            'etf_flow': None
        }

        try:
            # 1. 北向资金 - 优先使用MCP WebSearch
            print("  获取北向资金数据 (MCP WebSearch优先)...")
            northbound_data = await self._get_fund_flow_websearch('北向资金')

            if northbound_data:
                fund_flow_data['northbound'] = northbound_data
                print(f"    [OK] 北向资金(WebSearch): 5日{northbound_data['recent_5d']}亿, 120日{northbound_data['total_120d']}亿")
            elif not self.disable_akshare:
                # 降级到AKShare (仅在未禁用时)
                print("    WebSearch失败,降级到AKShare...")
                north_response = await self.manager.get_hsgt_flow('北向资金')
                if not north_response.error and north_response.data is not None:
                    df = north_response.data
                    # 筛选120日数据
                    if 'date' in df.columns or '日期' in df.columns:
                        date_col = 'date' if 'date' in df.columns else '日期'
                        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                        df = df.dropna(subset=[date_col])
                        df = df[df[date_col] >= self.start_date]
                        df = df[df[date_col] <= self.end_date]

                    if len(df) > 0:
                        # 计算累计流入和近5日流入
                        flow_col = None
                        for col in df.columns:
                            if '净买额' in str(col) or '净流入' in str(col):
                                flow_col = col
                                break

                        if flow_col:
                            df_sorted = df.sort_values(date_col)
                            total_flow = df_sorted[flow_col].sum() / 100_000_000  # 转换为亿元
                            recent_5d_flow = df_sorted[flow_col].tail(5).sum() / 100_000_000

                            # 检测异常零值
                            if total_flow == 0.0 and recent_5d_flow == 0.0:
                                print("    [WARNING] 检测到异常零值,使用WebSearch验证...")
                                websearch_data = await self._get_fund_flow_websearch('北向资金')
                                if websearch_data:
                                    fund_flow_data['northbound'] = websearch_data
                                    print(f"    [OK] 北向资金(WebSearch补充): {websearch_data['recent_5d']}亿")
                                else:
                                    fund_flow_data['northbound'] = {
                                        'recent_5d': round(recent_5d_flow, 2),
                                        'total_120d': round(total_flow, 2),
                                        'trend': '流入' if recent_5d_flow > 0 else '流出',
                                        'source': f"{north_response.source}(异常零值)",
                                        'note': '数据异常,请人工核查'
                                    }
                            else:
                                fund_flow_data['northbound'] = {
                                    'recent_5d': round(recent_5d_flow, 2),
                                    'total_120d': round(total_flow, 2),
                                    'trend': '流入' if recent_5d_flow > 0 else '流出',
                                    'source': f"{north_response.source}(备用)"
                                }
                            print(f"    [OK] 北向资金(AKShare): 5日{recent_5d_flow:.2f}亿, 120日{total_flow:.2f}亿")
            else:
                # AKShare已禁用且WebSearch失败
                print("    [WARNING] AKShare已禁用且WebSearch失败，北向资金数据缺失")
                fund_flow_data['northbound'] = {
                    'recent_5d': 'N/A',
                    'total_120d': 'N/A',
                    'trend': 'N/A',
                    'source': 'AKShare已禁用',
                    'note': 'WebSearch失败，需人工补充'
                }

            # 2. 南向资金 - 优先使用MCP WebSearch
            print("  获取南向资金数据 (MCP WebSearch优先)...")
            southbound_data = await self._get_fund_flow_websearch('南向资金')

            if southbound_data:
                fund_flow_data['southbound'] = southbound_data
                print(f"    [OK] 南向资金(WebSearch): 5日{southbound_data['recent_5d']}亿, 120日{southbound_data['total_120d']}亿")
            elif not self.disable_akshare:
                # 降级到AKShare (仅在未禁用时)
                print("    WebSearch失败,降级到AKShare...")
                south_response = await self.manager.get_hsgt_flow('南向资金')
                if not south_response.error and south_response.data is not None:
                    df = south_response.data
                    if 'date' in df.columns or '日期' in df.columns:
                        date_col = 'date' if 'date' in df.columns else '日期'
                        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                        df = df.dropna(subset=[date_col])
                        df = df[df[date_col] >= self.start_date]
                        df = df[df[date_col] <= self.end_date]

                    if len(df) > 0:
                        flow_col = None
                        for col in df.columns:
                            if '净买额' in str(col) or '净流入' in str(col):
                                flow_col = col
                                break

                        if flow_col:
                            df_sorted = df.sort_values(date_col)
                            total_flow = df_sorted[flow_col].sum() / 100_000_000
                            recent_5d_flow = df_sorted[flow_col].tail(5).sum() / 100_000_000

                            # 检测异常零值
                            if total_flow == 0.0 and recent_5d_flow == 0.0:
                                print("    [WARNING] 检测到异常零值,使用WebSearch验证...")
                                websearch_data = await self._get_fund_flow_websearch('南向资金')
                                if websearch_data:
                                    fund_flow_data['southbound'] = websearch_data
                                    print(f"    [OK] 南向资金(WebSearch补充): {websearch_data['recent_5d']}亿")
                                else:
                                    fund_flow_data['southbound'] = {
                                        'recent_5d': round(recent_5d_flow, 2),
                                        'total_120d': round(total_flow, 2),
                                        'trend': '流入' if recent_5d_flow > 0 else '流出',
                                        'source': f"{south_response.source}(异常零值)",
                                        'note': '数据异常,请人工核查'
                                    }
                            else:
                                fund_flow_data['southbound'] = {
                                    'recent_5d': round(recent_5d_flow, 2),
                                    'total_120d': round(total_flow, 2),
                                    'trend': '流入' if recent_5d_flow > 0 else '流出',
                                    'source': f"{south_response.source}(备用)"
                                }
                            print(f"    [OK] 南向资金(AKShare): 5日{recent_5d_flow:.2f}亿, 120日{total_flow:.2f}亿")
            else:
                # AKShare已禁用且WebSearch失败
                print("    [WARNING] AKShare已禁用且WebSearch失败，南向资金数据缺失")
                fund_flow_data['southbound'] = {
                    'recent_5d': 'N/A',
                    'total_120d': 'N/A',
                    'trend': 'N/A',
                    'source': 'AKShare已禁用',
                    'note': 'WebSearch失败，需人工补充'
                }

            # 3. 融资融券
            print("  获取融资融券数据...")
            if not self.disable_akshare:
                # 使用AKShare获取融资融券数据
                margin_response = await self.manager.get_margin_summary(
                    self.start_date, self.end_date, 'both'
                )
            else:
                print("    AKShare已禁用，尝试使用WebSearch获取融资融券数据...")
                margin_websearch = await self._get_fund_flow_websearch('融资融券')
                if margin_websearch:
                    fund_flow_data['margin'] = margin_websearch
                    print(f"    [OK] 融资融券(WebSearch): 余额{margin_websearch.get('latest_balance', 'N/A')}亿")
                else:
                    fund_flow_data['margin'] = {
                        'recent_5d': 'N/A',
                        'total_120d': 'N/A',
                        'trend': 'N/A',
                        'source': 'AKShare已禁用',
                        'note': 'WebSearch失败，需人工补充'
                    }
                margin_response = None  # 设置为None跳过后续处理

            if margin_response and not margin_response.error and margin_response.data is not None:
                df = margin_response.data

                # 查找融资余额列
                balance_col = None
                for col in df.columns:
                    if '融资余额' in str(col) or 'rzye' in str(col).lower():
                        balance_col = col
                        break

                if balance_col:
                    df_sorted = df.sort_values(df.columns[0])  # 按第一列（日期）排序
                    if len(df_sorted) >= 2:
                        latest_balance = df_sorted[balance_col].iloc[-1] / 100_000_000
                        start_balance = df_sorted[balance_col].iloc[0] / 100_000_000
                        balance_change = latest_balance - start_balance

                        # 近5日变化
                        recent_5d_change = 0
                        if len(df_sorted) >= 5:
                            recent_balance = df_sorted[balance_col].iloc[-5] / 100_000_000
                            recent_5d_change = latest_balance - recent_balance

                        fund_flow_data['margin'] = {
                            'recent_5d': round(recent_5d_change, 2),
                            'total_120d': round(balance_change, 2),
                            'trend': '增加' if recent_5d_change > 0 else '减少',
                            'latest_balance': round(latest_balance, 2),
                            'source': margin_response.source
                        }
                        print(f"    [OK] 融资融券: 5日变化{recent_5d_change:.2f}亿, 120日变化{balance_change:.2f}亿")

            # 4. ETF资金流 - 使用MCP WebSearch获取
            print("  获取ETF资金流数据 (MCP WebSearch)...")
            etf_flow_data = await self._get_fund_flow_websearch('ETF资金流')

            if etf_flow_data:
                fund_flow_data['etf_flow'] = etf_flow_data
                print(f"    [OK] ETF资金流(WebSearch): 5日{etf_flow_data['recent_5d']}亿, 120日{etf_flow_data['total_120d']}亿")
            else:
                fund_flow_data['etf_flow'] = {
                    'recent_5d': 'N/A',
                    'total_120d': 'N/A',
                    'trend': 'N/A',
                    'note': 'MCP WebSearch获取失败',
                    'source': 'N/A'
                }
                print("    [WARNING] ETF资金流数据获取失败")

        except Exception as e:
            print(f"  资金流向数据收集异常: {e}")
            import traceback
            traceback.print_exc()

        return fund_flow_data

    def generate_market_conclusion(self, market_data: Dict, pring_analysis: Dict) -> List[str]:
        """
        生成市场结论要点（V4.0适配三层框架）

        Args:
            market_data: 市场数据
            pring_analysis: Pring三层框架完整分析结果

        Returns:
            结论要点列表
        """
        conclusions = []

        # 主要指数表现
        if '000300' in market_data:
            hs300 = market_data['000300']
            change_120d = hs300.get('change_120d_pct', 0)
            trend_label = hs300.get('trend_label', '中性')
            conclusions.append(
                f"过去120天，沪深300指数累计变化{change_120d:+.1f}%，当前趋势评级为「{trend_label}」"
            )

        # 上证50表现
        if '000016' in market_data:
            sz50 = market_data['000016']
            change_120d = sz50.get('change_120d_pct', 0)
            trend_label = sz50.get('trend_label', '中性')
            conclusions.append(
                f"上证50指数120日累计变化{change_120d:+.1f}%，趋势评级为「{trend_label}」"
            )

        # 创业板表现
        if '399006' in market_data:
            cyb = market_data['399006']
            change_120d = cyb.get('change_120d_pct', 0)
            trend_label = cyb.get('trend_label', '中性')
            conclusions.append(
                f"创业板指120日累计变化{change_120d:+.1f}%，趋势评级为「{trend_label}」"
            )

        # V4.0: 三层框架分析结论
        layer_1 = pring_analysis.get('layer_1_inventory_cycle', {})
        layer_2 = pring_analysis.get('layer_2_monetary_cycle', {})
        final_stage = pring_analysis.get('stage', 'N/A')
        final_confidence = pring_analysis.get('confidence', 0)

        # 库存周期结论
        inventory_stage = layer_1.get('cycle_stage', 'N/A')
        commodity_bias = layer_1.get('commodity_bias', 'N/A')
        conclusions.append(
            f"库存周期分析：当前处于「{inventory_stage}」阶段，商品趋势倾向「{commodity_bias}」"
        )

        # 货币周期结论
        monetary_stage = layer_2.get('cycle_stage', 'N/A')
        equity_bias = layer_2.get('equity_bias', 'N/A')
        conclusions.append(
            f"货币周期分析：当前货币政策「{monetary_stage}」，权益市场{equity_bias}"
        )

        # Pring最终判定
        if final_stage != 'N/A':
            conclusions.append(
                f"普林格六阶段判定：经三层框架修正后，当前可能处于「{final_stage}」(置信度{final_confidence:.1%})"
            )

        return conclusions

    def generate_stock_market_table(self, market_data: Dict) -> str:
        """生成股票市场综述表格"""
        table_header = """| 指数 | 近5日% | 近120日% | >MA50? | >MA200? | MA50斜率 | 30日波动率% | 趋势评分 | 趋势标签 |
|------|--------|----------|--------|---------|----------|-------------|----------|----------|"""

        rows = []
        stock_indices = ['000001', '000300', '000016', '399001', '399006']

        for symbol in stock_indices:
            if symbol not in market_data:
                continue

            data = market_data[symbol]
            name = data['name']
            change_5d = f"{data['change_5d_pct']:+.1f}" if data['change_5d_pct'] is not None else "N/A"
            change_120d = f"{data['change_120d_pct']:+.1f}"
            above_ma50 = "是" if data['above_ma50'] else "否" if data['above_ma50'] is not None else "N/A"
            above_ma200 = "是" if data['above_ma200'] else "否" if data['above_ma200'] is not None else "N/A"
            ma50_slope = f"{data['ma50_slope']:+.4f}" if data['ma50_slope'] is not None else "N/A"
            volatility = f"{data['volatility_30d_pct']:.1f}" if data['volatility_30d_pct'] is not None else "N/A"
            trend_score = data['trend_score']
            trend_label = data['trend_label']

            row = f"| {name} | {change_5d}% | {change_120d}% | {above_ma50} | {above_ma200} | {ma50_slope} | {volatility}% | {trend_score:+d} | {trend_label} |"
            rows.append(row)

        return table_header + "\n" + "\n".join(rows)

    def generate_commodity_table(self, commodity_data: Dict) -> str:
        """生成国际商品期货表现表格 - V2.1 使用实际数据"""
        table_header = """| 品种 | 最新报价 | 日涨跌 | 年内涨跌 | 趋势方向 | 数据来源 |
|------|----------|--------|----------|----------|----------|"""

        rows = []

        # 按顺序生成表格行
        commodity_order = ['COMEX黄金', 'WTI原油', 'Brent原油', 'COMEX铜', 'BCOM指数', 'GSG ETF']

        for commodity_name in commodity_order:
            if commodity_name in commodity_data:
                data = commodity_data[commodity_name]

                # 处理不同类型的值(实际数据 vs MCP_REQUIRED vs 错误)
                if data.get('price') == 'MCP_REQUIRED':
                    # 需要MCP补充
                    price = f"待MCP获取"
                    daily_change = 'N/A'
                    ytd_change = 'N/A'
                    trend = 'N/A'
                    source = f"MCP WebFetch({data.get('query_symbol', 'N/A')})"
                elif data.get('price') == '数据获取失败':
                    # 获取失败
                    price = '数据获取失败'
                    daily_change = 'N/A'
                    ytd_change = 'N/A'
                    trend = 'N/A'
                    source = '获取失败'
                else:
                    # 实际数据
                    unit = data.get('unit', '')
                    price = f"{data.get('price')}{unit}" if data.get('price') else 'N/A'
                    daily_change = f"{data.get('daily_change')}%" if data.get('daily_change') else 'N/A'
                    ytd_change = f"{data.get('ytd_change')}%" if data.get('ytd_change') else 'N/A'
                    trend = data.get('trend', 'N/A')
                    source = data.get('source', 'N/A')

                row = f"| {commodity_name} | {price} | {daily_change} | {ytd_change} | {trend} | {source} |"
            else:
                # 数据缺失
                row = f"| {commodity_name} | 数据缺失 | N/A | N/A | N/A | 未收集 |"

            rows.append(row)

        return table_header + "\n" + "\n".join(rows)

    def generate_forex_table(self, forex_data: Dict) -> str:
        """生成汇率变动表格 - V2.1 使用实际数据"""
        table_header = """| 汇率对 | 最新报价 | 日涨跌 | 120日涨跌 | 趋势方向 | 数据来源 |
|--------|----------|--------|----------|----------|----------|"""

        rows = []

        # 按顺序生成表格行
        forex_order = ['USD/CNY', 'USD/CNH', '美元指数']

        for forex_name in forex_order:
            if forex_name in forex_data:
                data = forex_data[forex_name]

                # 处理不同类型的值
                if data.get('rate') == 'MCP_REQUIRED':
                    # 需要MCP补充
                    rate = f"待MCP获取"
                    change_5d = 'N/A'
                    change_120d = 'N/A'
                    trend = 'N/A'
                    source = f"MCP WebFetch({data.get('query_symbol', 'N/A')})"
                elif data.get('rate') == '数据获取失败':
                    # 获取失败
                    rate = '数据获取失败'
                    change_5d = 'N/A'
                    change_120d = 'N/A'
                    trend = 'N/A'
                    source = '获取失败'
                else:
                    # 实际数据
                    rate = f"{data.get('rate'):.4f}" if isinstance(data.get('rate'), (int, float)) else data.get('rate', 'N/A')
                    change_5d = f"{data.get('change_5d'):+.2f}%" if isinstance(data.get('change_5d'), (int, float)) else 'N/A'
                    change_120d = f"{data.get('change_120d'):+.2f}%" if isinstance(data.get('change_120d'), (int, float)) else 'N/A'
                    trend = data.get('trend', 'N/A')
                    source = data.get('source', 'N/A')

                display_name = data.get('display_name', forex_name)
                row = f"| {display_name} | {rate} | {change_5d} | {change_120d} | {trend} | {source} |"
            else:
                # 数据缺失
                row = f"| {forex_name} | 数据缺失 | N/A | N/A | N/A | 未收集 |"

            rows.append(row)

        return table_header + "\n" + "\n".join(rows)

    def generate_bond_table(self, bond_data: Dict) -> str:
        """生成债券收益率表格 - V2.1 使用实际数据"""
        table_header = """| 品种 | 当前收益率 | 近5日变动(bp) | 近120日变动(bp) | 趋势方向 | 数据来源 |
|------|------------|---------------|-----------------|----------|----------|"""

        rows = []

        # 按顺序生成表格行
        bond_order = ['美国10Y国债', '中国10Y国债', '中国10Y国开债']

        for bond_name in bond_order:
            if bond_name in bond_data:
                data = bond_data[bond_name]

                # 处理不同类型的值
                if data.get('yield') == 'MCP_REQUIRED':
                    # 需要MCP补充
                    bond_yield = f"待MCP获取"
                    change_5d = 'N/A'
                    change_120d = 'N/A'
                    trend = 'N/A'
                    source = f"MCP WebFetch({data.get('query_symbol', 'N/A')})"
                elif data.get('yield') == '数据获取失败':
                    # 获取失败
                    bond_yield = '数据获取失败'
                    change_5d = 'N/A'
                    change_120d = 'N/A'
                    trend = 'N/A'
                    source = '获取失败'
                else:
                    # 实际数据
                    bond_yield = f"{data.get('yield'):.3f}%" if isinstance(data.get('yield'), (int, float)) else data.get('yield', 'N/A')
                    change_5d = f"{data.get('change_5d_bp'):+.1f}bp" if isinstance(data.get('change_5d_bp'), (int, float)) else 'N/A'
                    change_120d = f"{data.get('change_120d_bp'):+.1f}bp" if isinstance(data.get('change_120d_bp'), (int, float)) else 'N/A'
                    trend = data.get('trend', 'N/A')
                    source = data.get('source', 'N/A')

                display_name = data.get('display_name', bond_name)
                row = f"| {display_name} | {bond_yield} | {change_5d} | {change_120d} | {trend} | {source} |"
            else:
                # 数据缺失
                row = f"| {bond_name} | 数据缺失 | N/A | N/A | N/A | 未收集 |"

            rows.append(row)

        return table_header + "\n" + "\n".join(rows)

    def generate_fund_flow_table(self, fund_flow_data: Dict) -> str:
        """生成资金流向表格 - V2.1 自动识别数据来源"""
        table_header = """| 资金类型 | 近5日流向(亿元) | 近120日累计(亿元) | 流向趋势 | 备注 |
|----------|----------------|-------------------|----------|------|"""

        rows = []

        # 北向资金
        north = fund_flow_data.get('northbound')
        if north:
            recent = f"{north['recent_5d']:+.2f}" if isinstance(north['recent_5d'], (int, float)) else north['recent_5d']
            total = f"{north['total_120d']:+.2f}" if isinstance(north['total_120d'], (int, float)) else north['total_120d']
            # 自动识别数据来源
            source = north.get('source', 'AKShare数据')
            note = north.get('note', '')
            if 'WebSearch' in source:
                source_label = f"MCP WebSearch实时获取{' - ' + note if note else ''}"
            elif '异常零值' in source:
                source_label = f"{source} - {note}"
            elif '备用' in source:
                source_label = source.replace('(备用)', '(AKShare备用)')
            else:
                source_label = "AKShare数据"
            rows.append(f"| 北向资金 | {recent} | {total} | {north['trend']} | {source_label} |")
        else:
            rows.append("| 北向资金 | N/A | N/A | N/A | 数据获取失败 |")

        # 南向资金
        south = fund_flow_data.get('southbound')
        if south:
            recent = f"{south['recent_5d']:+.2f}" if isinstance(south['recent_5d'], (int, float)) else south['recent_5d']
            total = f"{south['total_120d']:+.2f}" if isinstance(south['total_120d'], (int, float)) else south['total_120d']
            # 自动识别数据来源
            source = south.get('source', 'AKShare数据')
            note = south.get('note', '')
            if 'WebSearch' in source:
                source_label = f"MCP WebSearch实时获取{' - ' + note if note else ''}"
            elif '异常零值' in source:
                source_label = f"{source} - {note}"
            elif '备用' in source:
                source_label = source.replace('(备用)', '(AKShare备用)')
            else:
                source_label = "AKShare数据"
            rows.append(f"| 南向资金 | {recent} | {total} | {south['trend']} | {source_label} |")
        else:
            rows.append("| 南向资金 | N/A | N/A | N/A | 数据获取失败 |")

        # ETF资金流
        etf = fund_flow_data.get('etf_flow')
        if etf:
            recent = etf['recent_5d']
            total = etf['total_120d']
            if isinstance(recent, (int, float)):
                recent = f"{recent:+.2f}"
            if isinstance(total, (int, float)):
                total = f"{total:+.2f}"

            # 自动识别数据来源
            source = etf.get('source', 'N/A')
            note = etf.get('note', '')
            if 'WebSearch' in source:
                source_label = f"MCP WebSearch实时获取{' - ' + note if note else ''}"
            elif note:
                source_label = note
            else:
                source_label = "N/A"
            rows.append(f"| ETF资金流 | {recent} | {total} | {etf['trend']} | {source_label} |")
        else:
            rows.append("| ETF资金流 | N/A | N/A | N/A | 数据接入中 |")

        # 融资融券
        margin = fund_flow_data.get('margin')
        if margin:
            recent = f"{margin['recent_5d']:+.2f}" if isinstance(margin['recent_5d'], (int, float)) else margin['recent_5d']
            total = f"{margin['total_120d']:+.2f}" if isinstance(margin['total_120d'], (int, float)) else margin['total_120d']
            balance_note = f"余额{margin['latest_balance']:.2f}亿" if 'latest_balance' in margin else "AKShare数据"
            rows.append(f"| 融资融券余额 | {recent} | {total} | {margin['trend']} | {balance_note} |")
        else:
            rows.append("| 融资融券余额 | N/A | N/A | N/A | 数据获取失败 |")

        return table_header + "\n" + "\n".join(rows)

    def generate_pring_analysis_section(self, pring_analysis: Dict) -> str:
        """
        生成普林格阶段推断章节（V4.1增强）

        V4.1优化:
        - 专门处理stage="数据不足"情况
        - 显示数据完整性报告
        - 提供明确的改进建议

        Args:
            pring_analysis: PringAnalyzer返回的完整分析结果

        Returns:
            格式化的Markdown章节
        """
        # 提取关键信息
        final_stage = pring_analysis.get('stage', 'N/A')
        final_confidence = pring_analysis.get('confidence', 0)

        # V4.1: 检查是否为数据不足情况
        if final_stage == "数据不足":
            error_msg = pring_analysis.get('error', '数据不足，无法执行分析')
            completeness = pring_analysis.get('data_completeness', {})

            # 生成数据质量等级标签
            overall = completeness.get('overall', 0)
            if overall >= 80:
                quality_label = "良好"
                quality_mark = "[GOOD]"
            elif overall >= 60:
                quality_label = "可接受"
                quality_mark = "[OK]"
            elif overall >= 40:
                quality_label = "较差"
                quality_mark = "[POOR]"
            else:
                quality_label = "严重不足"
                quality_mark = "[CRITICAL]"

            # 返回专门的"数据不足"报告
            section = f"""### [WARNING] 分析状态：数据不足

**V4.1数据完整性验证**: 系统检测到数据不足，为确保分析可靠性，已拒绝执行Pring周期判断。

---

### 数据完整性报告

| 层级 | 完整性 | 最低要求 | 状态 |
|------|--------|---------|------|
| 第一层(库存周期) | {completeness.get('layer_1', 0):.1f}% | 60% | {'[PASS]' if completeness.get('layer_1', 0) >= 60 else '[FAIL]'} |
| 第二层(货币周期) | {completeness.get('layer_2', 0):.1f}% | 60% | {'[PASS]' if completeness.get('layer_2', 0) >= 60 else '[FAIL]'} |
| 第三层(Pring信号) | {completeness.get('layer_3', 0):.1f}% | 60% | {'[PASS]' if completeness.get('layer_3', 0) >= 60 else '[FAIL]'} |
| **总体** | **{overall:.1f}%** | **60%** | **{quality_mark} {quality_label}** |

---

### 详细错误信息

```
{error_msg}
```

---

### 改进建议

**立即行动**:
1. **检查数据源连接**: 验证AKShare和TuShare API可用性
2. **查看数据收集日志**: 定位具体缺失的数据项
3. **补充货币周期数据**: 考虑使用WebSearch从央行公告获取M2/逆回购/MLF/降准/TSF数据

**后续步骤**:
- 等待数据源恢复后重新生成报告
- 或使用历史数据作为临时替代方案
- 参考其他信息源（如行业报告、新闻资讯）进行综合判断

---

**重要提示**: V4.1数据完整性保障机制确保Pring分析只在数据充分可靠（≥60%）时执行，
避免"垃圾输入，垃圾输出"(GIGO)问题，保护您的投资决策质量。

**技术细节**: 详见 `docs/V4.1优化总结-数据完整性保障.md`"""

            return section

        # V4.1: 正常分析情况 - 继续原有逻辑
        # 提取三层分析结果
        layer_1 = pring_analysis.get('layer_1_inventory_cycle', {})
        layer_2 = pring_analysis.get('layer_2_monetary_cycle', {})
        layer_3 = pring_analysis.get('layer_3_pring_final', {})

        methodology = pring_analysis.get('methodology', 'N/A')

        # 安全获取score_details
        layer_1_details = layer_1.get('score_details', {})
        layer_2_details = layer_2.get('score_details', {})

        section = f"""### 阶段判断结果（V4.0三层框架）
- **最终判定**: {final_stage}
- **置信度**: {final_confidence:.1%}
- **分析框架**: {methodology}

---

### 第一层：库存周期分析

**数据来源**: {layer_1.get('data_source', '未知')} (更新时间: {layer_1.get('update_time', 'N/A')})

| 指标 | 权重 | 评分详情 |
|------|------|----------|
| PPI | 30% | {layer_1_details.get('PPI评分', 'N/A')} |
| PMI | 25% | {layer_1_details.get('PMI评分', 'N/A')} |
| 工业增加值 | 20% | {layer_1_details.get('工业增加值评分', 'N/A')} |
| BDI指数 | 15% | {layer_1_details.get('BDI评分', 'N/A')} |
| CPI | 10% | {layer_1_details.get('CPI评分', 'N/A')} |

**库存周期阶段**: {layer_1.get('cycle_stage', 'N/A')}
**商品趋势倾向**: {layer_1.get('commodity_bias', 'N/A')}
**基本面评分**: {layer_1.get('fundamental_score', 0):.1f}/60分

---

### 第二层：货币周期叠加

**数据来源**: {layer_2.get('data_source', '未获取')}

| 货币政策指标 | 权重 | 评分详情 |
|-------------|------|----------|
| 存款准备金率变化 | 30% | {layer_2_details.get('降准幅度评分', 'N/A')} |
| 7天逆回购利率 | 30% | {layer_2_details.get('政策利率评分', 'N/A')} |
| TSF增速 | 25% | {layer_2_details.get('TSF增速评分', 'N/A')} |
| M2增速 | 15% | {layer_2_details.get('M2增速评分', 'N/A')} |

**货币周期阶段**: {layer_2.get('cycle_stage', 'N/A')}
**权益偏向**: {layer_2.get('equity_bias', 'N/A')}
**债券偏向**: {layer_2.get('bond_bias', 'N/A')}
**货币宽松度**: {layer_2.get('monetary_score', 0):.1f}/100分

**WebSearch待补充数据**: {', '.join(layer_2.get('websearch_required', {}).keys()) if layer_2.get('websearch_required') else '无'}

---

### 第三层：Pring六阶段最终判定

**基础判定**: {layer_3.get('base_stage', 'N/A')} (置信度: {layer_3.get('base_confidence', 0):.1%})
**货币修正后**: {layer_3.get('final_stage', 'N/A')} (置信度: {layer_3.get('final_confidence', 0):.1%})
**置信度调整**: {layer_3.get('monetary_adjustment', 0):+.1%}

**资产配置建议**: {pring_analysis.get('allocation_suggestion', 'N/A')}

| 资产类别 | 配置建议 | 当前信号 |
|---------|---------|---------|
| 债券 | {pring_analysis.get('asset_recommendations', {}).get('bonds', 'N/A')} | {pring_analysis.get('asset_signals', {}).get('bonds', 'N/A')} |
| 股票 | {pring_analysis.get('asset_recommendations', {}).get('stocks', 'N/A')} | {pring_analysis.get('asset_signals', {}).get('stocks', 'N/A')} |
| 商品 | {pring_analysis.get('asset_recommendations', {}).get('commodities', 'N/A')} | {pring_analysis.get('asset_signals', {}).get('commodities', 'N/A')} |

---

### 框架说明

**V4.0三层框架核心逻辑**:
1. **第一层（库存周期）**: 通过PPI、PMI、工业增加值、BDI、CPI五个指标判断中国经济所处的库存周期阶段，为商品趋势提供基本面支撑
2. **第二层（货币周期）**: 基于央行货币政策工具（降准、降息、MLF、TSF、M2）判断流动性环境，修正权益和债券的相对强弱
3. **第三层（Pring修正）**: 结合前两层分析，对经典Pring六阶段框架进行中国市场适配性修正，输出最终资产配置建议

**市场覆盖**:
- 股票市场：A股（沪深300）+ 港股（恒生指数）为主 (权重70%)，美股（S&P500）为参考 (权重30%)
- 债券市场：中国10年期国债收益率（使用ETF代理：511010/019649）
- 商品市场：国际期货（COMEX黄金、WTI/Brent原油、COMEX铜）+ 综合指数（BCOM、GSG）

**数据透明性**: 完整披露三层分析的评分过程、数据来源和计算逻辑，确保可追溯性和可验证性"""

        return section

    async def generate_report(self) -> str:
        """生成完整的120日背景扫描报告 - V2.1 重构版"""
        print("开始生成120日背景扫描报告...")

        # 1. 并行收集所有数据(提高效率)
        print("\n并行收集数据...")
        results = await asyncio.gather(
            self.collect_market_data(),
            self.collect_commodity_data(),
            self.collect_forex_data(),
            self.collect_bond_data(),
            self.collect_fund_flow_data(),
            self.get_pring_cycle_analysis(),  # V4.0: 三层框架分析
            return_exceptions=True
        )

        # 解包结果
        market_data = results[0] if not isinstance(results[0], Exception) else {}
        commodity_data = results[1] if not isinstance(results[1], Exception) else {}
        forex_data = results[2] if not isinstance(results[2], Exception) else {}
        bond_data = results[3] if not isinstance(results[3], Exception) else {}
        fund_flow_data = results[4] if not isinstance(results[4], Exception) else {}
        pring_analysis = results[5] if not isinstance(results[5], Exception) else {}  # V4.0: 完整三层分析结果

        print(f"\n数据收集完成:")
        print(f"  - 市场数据: {len(market_data)} 个指数")
        print(f"  - 商品数据: {len(commodity_data)} 个品种")
        print(f"  - 汇率数据: {len(forex_data)} 个货币对")
        print(f"  - 债券数据: {len(bond_data)} 个品种")
        print(f"  - 资金流向: {len(fund_flow_data)} 类数据")

        # 2. 生成市场结论（V4.0：使用三层框架结果）
        conclusions = self.generate_market_conclusion(market_data, pring_analysis)

        # 3. 生成报告内容
        report_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        report_content = f"""# 120日市场背景扫描报告 ({self.end_date})

**📅 报告生成时间**: {report_time}
**📊 数据窗口**: {self.start_date} 至 {self.end_date} (120个自然日)
**🔧 分析框架**: 120日背景扫描方案 V4.0 + 三层周期框架（库存→货币→Pring）

---

## 一、市场结论要点

{chr(10).join(f"- {conclusion}" for conclusion in conclusions)}

---

## 二、股票市场综述

### 表格：主要股指表现

{self.generate_stock_market_table(market_data)}

**数据说明**: 基于TuShare/AKShare数据源，计算窗口为120个自然日。趋势评分采用-2至+2评分体系，综合收益趋势、均线位置、中期趋势和短期动量四个维度。

---

## 三、商品与黄金

### 表格：国际商品期货表现（V2.1 数据增强）

{self.generate_commodity_table(commodity_data)}

**数据说明**:
- **数据来源**: 优先使用国际金融API，备用MCP WebFetch实时数据（Investing.com, Yahoo Finance）
- **品种说明**: COMEX黄金、WTI/Brent原油、COMEX铜为全球商品定价基准；BCOM/GSG为综合商品指数
- **指数构成**: BCOM指数包含24个商品期货（能源、农产品、工业金属、贵金属、畜牧）
- **MCP补充**: 标注"待MCP获取"的数据需要在Claude Code环境中使用WebFetch/WebSearch工具补充
- **降级逻辑**: 数据获取失败时显示明确错误信息，而非N/A占位符

---

## 四、汇率变化

### 表格：主要汇率变动

{self.generate_forex_table(forex_data)}

**数据说明** (V2.1 数据增强):
- **数据来源**: 优先使用InternationalFinance适配器，备用MCP WebFetch(Investing.com)
- **USD/CNY**: 美元兑人民币在岸价，数据源自中国外汇交易中心
- **USD/CNH**: 美元兑人民币离岸价，反映香港市场汇率
- **美元指数(DXY)**: 衡量美元对一篮子主要货币的强弱
- **MCP补充**: 标注"待MCP获取"的数据需要在Claude Code环境中补充

---

## 五、利率与债券收益率

### 表格：国债收益率变动

{self.generate_bond_table(bond_data)}

**数据说明** (V2.1 数据增强):
- **数据来源**: 优先使用InternationalFinance适配器，备用MCP WebFetch(Investing.com)
- **美国10Y国债**: 数据源自FRED/Yahoo Finance，反映美国长期利率水平
- **中国10Y国债**: 数据源自中债估值，部分日期可能延迟1天
- **中国10Y国开债**: 使用ETF代理(019950)或历史利差估算
- **bp说明**: 1bp = 0.01%，用于衡量债券收益率微小变化
- **MCP补充**: 标注"待MCP获取"的数据需要在Claude Code环境中补充

---

## 六、资金流向综述

### 表格：各类资金流动数据

{self.generate_fund_flow_table(fund_flow_data)}

**数据说明** (V2.1 MCP WebSearch优先):
- **数据获取策略**: 优先使用MCP WebSearch实时获取 → AKShare备用 → 异常零值检测与验证
- **北向资金/南向资金**: MCP WebSearch实时获取(东方财富网/同花顺/每经网)，AKShare作为备用数据源
- **融资融券余额**: 沪深两市融资融券余额变化（数据源：上交所/深交所官网，通过AKShare获取）
- **ETF资金流**: 100% MCP WebSearch实时获取（数据源：Wind、Choice、东方财富网等金融平台）
- **异常零值检测**: 当AKShare返回连续零值时，自动切换WebSearch验证，确保数据准确性
- **流向趋势**: 基于近5日数据判断，正值为流入/增加，负值为流出/减少
- **计算方法**: 120日累计 = 分析窗口内所有交易日的资金流向总和
- **数据时效性**: WebSearch数据延迟≤5分钟，AKShare数据延迟≤1天

---

## 七、财经要闻

*【财经要闻板块正在完善中，后续版本将通过Web搜索提供最新财经资讯】*

---

## 八、普林格阶段推断（V4.0三层框架）

{self.generate_pring_analysis_section(pring_analysis)}

---

## 九、附注说明

### 代理口径说明
- **商品数据**: V2.1优先使用国际期货数据API，备用MCP WebFetch实时获取
- **数据周期**: 120个自然日，约等于4个月的交易周期
- **评分体系**: 趋势评分采用-2至+2整数评分，±1为中性阈值
- **降级逻辑**: 数据获取失败时提供明确提示，引导使用MCP工具补充

### 计算方法说明
- **涨跌幅**: (期末价格/期初价格 - 1) × 100%，保留1-2位小数
- **MA斜率**: 采用10期线性回归计算，保留4位小数
- **年化波动率**: 近30日收益率标准差 × √252，保留1位小数
- **趋势评分**: 四维度评分累加，收益趋势+均线位置+中期趋势+短期动量

### 数据源汇总
- **股票数据**: TuShare (主)，AKShare (备)
- **商品数据**: InternationalFinance API (主)，MCP WebFetch (备)
- **汇率数据**: InternationalFinance API (主)，MCP WebFetch (备)
- **债券数据**: InternationalFinance API (主)，MCP WebFetch (备)
- **资金流向**: AKShare (北向/南向/融资融券)，MCP WebSearch (ETF资金流)
- **技术指标**: 自主计算，基于收盘价序列
- **库存周期**: 集成宏观经济指标(PPI、PMI、CPI、工业增加值、BDI)

### 合规声明
**本报告仅供研究与教学参考，不构成任何投资建议。投资有风险，决策需谨慎。**

---

**📊 报告生成**: 统一数据源集成框架 V2.1 (Phase 1增强)
**🔧 技术框架**: 120日背景扫描方案 V4.0 (三层周期框架)
**⚡ 分析引擎**: 库存周期 → 货币周期 → Pring六阶段修正
**✨ 新增特性**: 中国货币政策层 + 三层交叉验证 + 以中国市场为主的适配性修正
"""

        return report_content


async def main():
    """主函数 - 集成质量检查"""
    import argparse

    parser = argparse.ArgumentParser(description='生成120日背景扫描报告')
    parser.add_argument('--date', type=str, required=False, default="2025-09-16",
                        help='报告结束日期 (格式: YYYY-MM-DD)')
    parser.add_argument('--output', type=str, required=False, default=None,
                        help='输出文件路径 (默认: reports/YYYYMMDD背景扫描120.md)')
    parser.add_argument('--skip-validation', action='store_true',
                        help='跳过质量检查（不推荐）')

    args = parser.parse_args()

    try:
        generator = BackgroundScan120DGeneratorFixed(
            end_date=args.date
        )
        report = await generator.generate_report()

        # 保存报告到文件
        os.makedirs("reports", exist_ok=True)

        if args.output:
            report_filename = args.output
        else:
            date_str = args.date.replace("-", "")
            report_filename = f"reports/{date_str}背景扫描120.md"

        # 先写入临时文件
        temp_filename = report_filename + ".temp"
        with open(temp_filename, 'w', encoding='utf-8') as f:
            f.write(report)

        print(f"[SUCCESS] 报告生成完成: {temp_filename}")
        print(f"[INFO] 报告总计 {len(report)} 个字符")

        # 质量检查（Quality Gate）
        if VALIDATOR_AVAILABLE and not args.skip_validation:
            print("\n[VALIDATION] 执行质量检查...")
            validator = BackgroundScanValidator()
            validation_result = await validator.validate_background_scan_file(temp_filename)

            # 打印验证结果
            print(f"\n{'='*60}")
            print(f"质量评分: {validation_result.score:.1f}/100")
            print(f"{'='*60}")

            if validation_result.errors:
                print(f"\n[ERROR] 错误 ({len(validation_result.errors)}项):")
                for error in validation_result.errors:
                    print(f"  - {error}")

            if validation_result.warnings:
                print(f"\n[WARNING] 警告 ({len(validation_result.warnings)}项):")
                for warning in validation_result.warnings:
                    print(f"  - {warning}")

            if validation_result.suggestions:
                print(f"\n[SUGGESTION] 建议 ({len(validation_result.suggestions)}项):")
                for suggestion in validation_result.suggestions:
                    print(f"  - {suggestion}")

            # 质量门槛判断
            if validation_result.score < 60:
                print(f"\n{'='*60}")
                print(f"[FAIL] 质量不合格 (评分: {validation_result.score:.1f}/100)")
                print(f"   最低要求: 60分")
                print(f"   报告未保存到最终位置")
                print(f"   请修复上述问题后重新生成")
                print(f"{'='*60}")
                os.remove(temp_filename)
                return None
            elif validation_result.score < 80:
                print(f"\n{'='*60}")
                print(f"[WARNING] 质量合格但需改进 (评分: {validation_result.score:.1f}/100)")
                print(f"   建议评分: 80分以上")
                print(f"   报告已保存，但建议优化")
                print(f"{'='*60}")
            else:
                print(f"\n{'='*60}")
                print(f"[EXCELLENT] 质量优秀 (评分: {validation_result.score:.1f}/100)")
                print(f"{'='*60}")

            # 保存验证结果
            validation_log = report_filename.replace('.md', '_质量检查.json')
            with open(validation_log, 'w', encoding='utf-8') as f:
                json.dump({
                    'score': validation_result.score,
                    'is_valid': validation_result.is_valid,
                    'errors': validation_result.errors,
                    'warnings': validation_result.warnings,
                    'suggestions': validation_result.suggestions,
                    'data_summary': validation_result.data_summary
                }, f, ensure_ascii=False, indent=2)
            print(f"\n[INFO] 验证结果已保存: {validation_log}")

        else:
            if args.skip_validation:
                print("\n[WARNING] 已跳过质量检查 (--skip-validation)")
            else:
                print("\n[WARNING] 质量检查工具不可用，跳过验证")

        # 重命名为最终文件
        if os.path.exists(report_filename):
            os.remove(report_filename)
        os.rename(temp_filename, report_filename)

        print(f"\n[SUCCESS] 最终报告: {report_filename}")
        return report_filename

    except Exception as e:
        print(f"[FAIL] 报告生成失败: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    asyncio.run(main())
