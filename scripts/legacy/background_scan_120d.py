#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
120日背景扫描器 - 主执行脚本
根据120背景扫描方案.md V3.1实现的完整市场背景扫描器

功能:
- 120日滚动窗口数据收集和分析
- 普林格六阶段判断(集成库存周期矫正)
- 技术指标计算和趋势评分
- 结构化Markdown报告生成

使用:
python scripts/background_scan_120d.py --date 2025-09-17 --output reports/20250917背景扫描120日.md
"""

import sys
import os
import asyncio
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import json
from typing import Dict, List, Any, Optional

# 添加项目根目录到Python路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

from datasource import get_manager
from datasource.calculators.pring_analyzer import PringAnalyzer
from datasource.utils.data_completion import NewsCollector


@contextmanager
def without_proxies():
    proxy_keys = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]
    backup = {key: os.environ.get(key) for key in proxy_keys}
    for key in proxy_keys:
        if key in os.environ:
            os.environ.pop(key)
    try:
        yield
    finally:
        for key, value in backup.items():
            if value is not None:
                os.environ[key] = value


def fetch_with_no_proxy(func, *args, **kwargs):
    with without_proxies():
        return func(*args, **kwargs)


class BackgroundScanner120D:
    """120日背景扫描器主类"""

    def __init__(self, end_date: str):
        self.end_date = datetime.strptime(end_date, '%Y-%m-%d')
        self.start_date = self.end_date - timedelta(days=120)
        self.manager = get_manager()
        self.pring_analyzer = PringAnalyzer(self.manager)
        self.news_collector = NewsCollector(use_mcp=False, manager=self.manager)

        # 核心标的配置
        self.stock_symbols = {
            '000300.SH': '沪深300',
            '000016.SH': '上证50',
            '399006.SZ': '创业板指',
            '000001.SH': '上证指数',
            '399001.SZ': '深证成指'
        }

        self.commodity_assets = {
            'CL': {'name': 'WTI原油', 'display': 'WTI原油(美元/桶)', 'fetch': 'futures_foreign'},
            'OIL': {'name': 'Brent原油', 'display': 'Brent原油(美元/桶)', 'fetch': 'futures_foreign'},
            'HG': {'name': 'COMEX铜', 'display': 'COMEX铜(美元/磅)', 'fetch': 'futures_foreign'},
            'XAU': {'name': '现货黄金', 'display': '现货黄金(XAUUSD)', 'fetch': 'futures_foreign'},
            'GSG': {'name': 'BCOM商品指数', 'display': 'BCOM商品指数(GSG代理)', 'fetch': 'us_etf'}
        }

        # 汇率与国债目标
        self.forex_pairs = {
            'USDCNY': {'display': 'USD/CNY'},
            'USDCNH': {'display': 'USD/CNH'},
            'DXY': {'display': '美元指数(DXY)'}
        }

        self.bond_targets = {
            'US10Y': {'display': '美国10Y国债'},
            'CN10Y': {'display': '中国10Y国债'},
            'CN10Y_CDB': {'display': '中国10Y国开债'}
        }

    async def collect_stock_data(self) -> Dict[str, Any]:
        """收集股票指数数据并计算技术指标"""
        results = {}

        for symbol, name in self.stock_symbols.items():
            try:
                # 对于指数，去掉后缀使用index方法
                clean_symbol = symbol.split('.')[0]  # 000300.SH -> 000300

                # 获取指数日线数据
                response = await self.manager.get_index_daily(
                    clean_symbol,
                    self.start_date.strftime('%Y-%m-%d'),
                    self.end_date.strftime('%Y-%m-%d')
                )

                if response.error:
                    results[symbol] = {'error': response.error, 'name': name}
                    continue

                df = response.data
                if df.empty:
                    results[symbol] = {'error': '无数据', 'name': name}
                    continue

                # 计算技术指标
                metrics = self._calculate_stock_metrics(df)
                metrics['name'] = name
                metrics['source'] = response.source
                results[symbol] = metrics

            except Exception as e:
                results[symbol] = {'error': str(e), 'name': name}

        return results

    def _calculate_stock_metrics(self, df: pd.DataFrame) -> Dict[str, Any]:
        """计算股票技术指标"""
        if df.empty:
            return {}

        # 标准化列名（AKShare返回中文列名）
        column_mapping = {
            '日期': 'trade_date',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount',
            '振幅': 'amplitude',
            '涨跌幅': 'pct_chg',
            '涨跌额': 'change',
            '换手率': 'turnover'
        }

        # 重命名列
        for cn_name, en_name in column_mapping.items():
            if cn_name in df.columns:
                df = df.rename(columns={cn_name: en_name})

        # 确保有必要的列
        if 'trade_date' not in df.columns:
            if 'date' in df.columns:
                df = df.rename(columns={'date': 'trade_date'})
            elif df.index.name in ('date', '日期'):
                df = df.reset_index()
                df = df.rename(columns={'date': 'trade_date', df.index.name: 'trade_date'})

        if 'close' not in df.columns:
            print(f"Warning: Missing 'close' column. Available columns: {list(df.columns)}")
            return {'error': 'Missing close price data'}

        date_column = 'trade_date' if 'trade_date' in df.columns else next(
            (col for col in df.columns if 'date' in str(col).lower()), None
        )
        if date_column:
            df = df.sort_values(date_column)
        else:
            date_column = 'trade_date'

        # 基础价格数据
        current_price = df['close'].iloc[-1]

        # 涨跌幅计算
        change_5d_pct = ((df['close'].iloc[-1] / df['close'].iloc[-6] - 1) * 100) if len(df) >= 6 else None
        change_120d_pct = ((df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100) if len(df) >= 2 else None

        # 移动均线
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma50'] = df['close'].rolling(50).mean()
        df['ma200'] = df['close'].rolling(200).mean()

        ma20 = df['ma20'].iloc[-1] if not pd.isna(df['ma20'].iloc[-1]) else None
        ma50 = df['ma50'].iloc[-1] if not pd.isna(df['ma50'].iloc[-1]) else None
        ma200 = df['ma200'].iloc[-1] if not pd.isna(df['ma200'].iloc[-1]) else None

        # MA50斜率 (10期线性回归)
        ma50_slope = None
        if ma50 is not None:
            recent_ma50 = df['ma50'].dropna().tail(10)
            if len(recent_ma50) >= 5:
                x = np.arange(len(recent_ma50))
                slope = np.polyfit(x, recent_ma50, 1)[0]
                ma50_slope = float(slope)
                if np.isnan(ma50_slope):
                    ma50_slope = None

        # 30日年化波动率
        volatility_30d = None
        if len(df) >= 30:
            returns = df['close'].pct_change().iloc[-30:]
            volatility_30d = returns.std() * (252 ** 0.5) * 100  # 年化波动率%
            if pd.isna(volatility_30d):
                volatility_30d = None
            else:
                volatility_30d = float(volatility_30d)

        # 趋势评分系统 (-2 to +2)
        trend_score = 0

        # 1. 收益趋势 (±1分)
        if change_120d_pct is not None:
            if change_120d_pct >= 5:
                trend_score += 1
            elif change_120d_pct <= -5:
                trend_score -= 1

        # 2. 均线位置 (±1分)
        if ma50 is not None and current_price > ma50:
            trend_score += 1
        elif ma50 is not None and current_price < ma50:
            trend_score -= 1

        # 3. 中期趋势 (±1分) - 黄金交叉
        if ma50 is not None and ma200 is not None:
            if ma50 > ma200:
                trend_score += 1
            else:
                trend_score -= 1

        # 4. 短期动量 (±1分) - MA20斜率
        if ma20 is not None and len(df) >= 25:
            recent_ma20 = df['ma20'].iloc[-5:].dropna()
            if len(recent_ma20) >= 5:
                ma20_trend = recent_ma20.iloc[-1] - recent_ma20.iloc[0]
                if ma20_trend > 0:
                    trend_score += 1
                else:
                    trend_score -= 1

        # 趋势标签
        if trend_score >= 1:
            trend_label = '牛'
        elif trend_score <= -1:
            trend_label = '熊'
        else:
            trend_label = '中性'

        return {
            'current_price': round(current_price, 2),
            'change_5d_pct': round(change_5d_pct, 1) if change_5d_pct is not None else '—',
            'change_120d_pct': round(change_120d_pct, 1) if change_120d_pct is not None else '—',
            'ma20': round(ma20, 2) if ma20 is not None else '—',
            'ma50': round(ma50, 2) if ma50 is not None else '—',
            'ma200': round(ma200, 2) if ma200 is not None else '—',
            'above_ma50': current_price > ma50 if ma50 is not None else '—',
            'above_ma200': current_price > ma200 if ma200 is not None else '—',
            'ma50_slope': round(ma50_slope, 4) if ma50_slope is not None else '—',
            'volatility_30d_pct': round(volatility_30d, 1) if volatility_30d is not None else '—',
            'trend_score': trend_score,
            'trend_label': trend_label
        }

    async def collect_forex_data(self) -> Dict[str, Any]:
        """收集主要汇率数据"""
        results: Dict[str, Any] = {}
        end_date_str = self.end_date.strftime('%Y-%m-%d')
        start_date_str = (self.end_date - timedelta(days=200)).strftime('%Y-%m-%d')

        for symbol, meta in self.forex_pairs.items():
            display_name = meta.get('display', symbol)
            try:
                response = await self.manager.get_forex_data(symbol, start_date_str, end_date_str)
                if response.error or response.data is None or response.data.empty:
                    results[symbol] = {
                        'display': display_name,
                        'error': response.error or '数据缺失'
                    }
                    continue

                data = response.data.copy()
                if 'date' in data.columns:
                    data['date'] = pd.to_datetime(data['date'], errors='coerce')
                    data = data.dropna(subset=['date']).sort_values('date')

                latest = data.iloc[-1]
                latest_close = float(latest['close'])

                change_5d = latest.get('change_5d_pct')
                if change_5d is None or (isinstance(change_5d, float) and np.isnan(change_5d)):
                    if len(data) >= 6 and data.iloc[-6]['close'] not in (0, None):
                        change_5d = (latest_close / data.iloc[-6]['close'] - 1) * 100
                    else:
                        change_5d = None

                change_120d = latest.get('change_120d_pct')
                if change_120d is None or (isinstance(change_120d, float) and np.isnan(change_120d)):
                    baseline_idx = max(len(data) - 120, 0)
                    baseline_close = data.iloc[baseline_idx]['close'] if len(data) > 0 else None
                    if baseline_close not in (0, None):
                        change_120d = (latest_close / baseline_close - 1) * 100
                    else:
                        change_120d = None

                trend_direction = '偏强' if change_5d is not None and change_5d > 0 else (
                    '偏弱' if change_5d is not None and change_5d < 0 else '观望'
                )

                results[symbol] = {
                    'display': display_name,
                    'latest': latest_close,
                    'change_5d_pct': change_5d,
                    'change_120d_pct': change_120d,
                    'trend': trend_direction,
                    'source': response.source,
                    'metadata': response.metadata or {}
                }
            except Exception as exc:
                results[symbol] = {
                    'display': display_name,
                    'error': str(exc)
                }

        return results

    async def collect_bond_yield_data(self) -> Dict[str, Any]:
        """收集主要国债收益率数据"""
        results: Dict[str, Any] = {}
        end_date_str = self.end_date.strftime('%Y-%m-%d')
        start_date_str = (self.end_date - timedelta(days=200)).strftime('%Y-%m-%d')

        for symbol, meta in self.bond_targets.items():
            display_name = meta.get('display', symbol)
            try:
                response = await self.manager.get_bond_yield_data(symbol, start_date_str, end_date_str)
                if response.error or response.data is None or response.data.empty:
                    results[symbol] = {
                        'display': display_name,
                        'error': response.error or '数据缺失'
                    }
                    continue

                data = response.data.copy()
                if 'date' in data.columns:
                    data['date'] = pd.to_datetime(data['date'], errors='coerce')
                    data = data.dropna(subset=['date']).sort_values('date')

                latest = data.iloc[-1]
                latest_yield = float(latest['close'])

                change_5d = latest.get('yield_change_5d_bp')
                if change_5d is None or (isinstance(change_5d, float) and np.isnan(change_5d)):
                    if len(data) >= 6:
                        prior_close = data.iloc[-6]['close']
                        if prior_close is not None:
                            change_5d = (latest_yield - prior_close) * 100

                change_120d = latest.get('yield_change_120d_bp')
                if change_120d is None or (isinstance(change_120d, float) and np.isnan(change_120d)):
                    baseline_idx = max(len(data) - 120, 0)
                    baseline = data.iloc[baseline_idx]['close'] if len(data) > 0 else None
                    if baseline is not None:
                        change_120d = (latest_yield - baseline) * 100

                trend = '收益率上行' if change_5d is not None and change_5d > 0 else (
                    '收益率下行' if change_5d is not None and change_5d < 0 else '持平'
                )

                results[symbol] = {
                    'display': display_name,
                    'yield': latest_yield,
                    'change_5d_bp': change_5d,
                    'change_120d_bp': change_120d,
                    'trend': trend,
                    'source': response.source,
                    'metadata': response.metadata or {}
                }
            except Exception as exc:
                results[symbol] = {
                    'display': display_name,
                    'error': str(exc)
                }

        return results

    async def collect_capital_flow_data(self) -> List[Dict[str, Any]]:
        """收集主要资金流向数据"""
        results: List[Dict[str, Any]] = []
        adapter = self.manager.get_data_source('tushare')
        if not adapter or not getattr(adapter, "pro", None):
            return results

        loop = asyncio.get_event_loop()
        start_date = (self.end_date - timedelta(days=160)).strftime('%Y%m%d')
        end_date = self.end_date.strftime('%Y%m%d')

        try:
            def fetch_hsgt():
                return adapter.pro.moneyflow_hsgt(start_date=start_date, end_date=end_date)

            df = await loop.run_in_executor(None, fetch_hsgt)
            if df is not None and not df.empty:
                df['trade_date'] = pd.to_datetime(df['trade_date'], errors='coerce')
                df = df.dropna(subset=['trade_date']).sort_values('trade_date')
                latest = df.iloc[-1]

                def _sum_last(series: pd.Series, window: int = 120) -> float:
                    tail = pd.to_numeric(series, errors='coerce').dropna().tail(min(window, len(series)))
                    return float(tail.sum()) if not tail.empty else 0.0

                north_daily = float(latest['north_money'])
                south_daily = float(latest['south_money'])

                results.append({
                    'type': '北向资金',
                    'daily': north_daily,
                    'rolling_120': _sum_last(df['north_money']),
                    'trend': '净流入' if north_daily > 0 else '净流出' if north_daily < 0 else '持平',
                    'remark': '数据来源: TuShare moneyflow_hsgt'
                })
                results.append({
                    'type': '南向资金',
                    'daily': south_daily,
                    'rolling_120': _sum_last(df['south_money']),
                    'trend': '净流入' if south_daily > 0 else '净流出' if south_daily < 0 else '持平',
                    'remark': '数据来源: TuShare moneyflow_hsgt'
                })
            else:
                results.append({
                    'type': '北向资金',
                    'daily': None,
                    'rolling_120': None,
                    'trend': '待接入',
                    'remark': 'TuShare moneyflow_hsgt 未返回数据'
                })
                results.append({
                    'type': '南向资金',
                    'daily': None,
                    'rolling_120': None,
                    'trend': '待接入',
                    'remark': 'TuShare moneyflow_hsgt 未返回数据'
                })
        except Exception as exc:
            results.append({
                'type': '北向资金',
                'error': str(exc)
            })

        results.append({
            'type': 'ETF资金',
            'daily': None,
            'rolling_120': None,
            'trend': '待接入',
            'remark': 'ETF资金净流入数据尚未对接'
        })
        results.append({
            'type': '融资融券余额',
            'daily': None,
            'rolling_120': None,
            'trend': '待接入',
            'remark': '融资融券余额数据待补充'
        })

        return results

    async def collect_financial_news(self) -> List[Dict[str, Any]]:
        """收集财经要闻列表"""
        try:
            return await self.news_collector.collect_120d_financial_news(self.end_date.strftime('%Y-%m-%d'))
        except Exception:
            return []

    async def _fetch_commodity_dataframe(self, symbol: str, fetch_type: str) -> Optional[pd.DataFrame]:
        """已移除 AKShare 依赖，此处直接返回 None，待后续接入 WebSearch/TuShare 替代。"""
        print(f"[INFO] AKShare 已移除，commodity {symbol}({fetch_type}) 暂无数据源，返回空。")
        return None

    def _standardize_commodity_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """统一商品数据列名为 trade_date/close 等标准格式"""
        normalized = df.copy()

        rename_map = {
            '日期': 'trade_date',
            'date': 'trade_date',
            'Date': 'trade_date',
            '时间': 'trade_date',
            '交易日期': 'trade_date',
            '收盘': 'close',
            'close': 'close',
            'Close': 'close',
            '结算价': 'close',
            '最新价': 'close',
            '价格': 'close',
            '开盘': 'open',
            'open': 'open',
            '最高': 'high',
            'high': 'high',
            '最低': 'low',
            'low': 'low'
        }

        normalized = normalized.rename(columns={k: v for k, v in rename_map.items() if k in normalized.columns})

        if 'trade_date' not in normalized.columns:
            first_col = normalized.columns[0]
            normalized = normalized.rename(columns={first_col: 'trade_date'})

        normalized['trade_date'] = pd.to_datetime(normalized['trade_date'], errors='coerce')
        normalized = normalized.dropna(subset=['trade_date']).sort_values('trade_date')

        if 'close' not in normalized.columns:
            candidate_cols = [
                col for col in normalized.columns
                if col != 'trade_date' and any(token in str(col).lower() for token in ['close', 'settle', 'price', 'last'])
            ]
            if candidate_cols:
                normalized['close'] = pd.to_numeric(normalized[candidate_cols[0]], errors='coerce')
            else:
                numeric_cols = normalized.select_dtypes(include=[float, int]).columns.tolist()
                if numeric_cols:
                    normalized['close'] = pd.to_numeric(normalized[numeric_cols[0]], errors='coerce')

        normalized['close'] = pd.to_numeric(normalized['close'], errors='coerce')
        normalized = normalized.dropna(subset=['close'])

        return normalized

    async def collect_commodity_data(self) -> Dict[str, Any]:
        """收集商品基准数据 (WTI/Brent/COMEX铜/现货黄金/BCOM)"""
        results = {}

        for symbol, config in self.commodity_assets.items():
            display_name = config.get('display', config.get('name', symbol))
            fetch_type = config.get('fetch', 'futures_foreign')
            try:
                df = await self._fetch_commodity_dataframe(symbol, fetch_type)
                if df is None or df.empty:
                    results[symbol] = {'error': '无数据', 'name': display_name}
                    continue

                metrics = self._calculate_stock_metrics(df)
                metrics['name'] = display_name
                results[symbol] = metrics

            except Exception as e:
                results[symbol] = {'error': str(e), 'name': display_name}

        return results

    async def analyze_pring_cycle(self) -> Dict[str, Any]:
        """执行普林格六阶段分析(集成库存周期矫正)"""
        try:
            # 使用PringAnalyzer进行增强分析
            result = await self.pring_analyzer.analyze_pring_stage(120)

            return {
                'stage': result.get('current_stage', 'N/A'),
                'confidence': result.get('confidence_score', 0),
                'commodity_signal': result.get('commodity_signal', 'Neutral'),
                'commodity_score': result.get('commodity_signal_score', 0),
                'technical_score': result.get('technical_analysis_score', 0),
                'inventory_score': result.get('inventory_cycle_score', 0),
                'inventory_stage': result.get('inventory_cycle_stage', 'N/A'),
                'analysis_details': result.get('analysis_details', {}),
                'signals': result.get('signals', {})
            }

        except Exception as e:
            return {
                'error': str(e),
                'stage': 'N/A',
                'confidence': 0,
                'commodity_signal': 'N/A',
                'commodity_score': 0
            }

    def generate_report(
        self,
        stock_data: Dict[str, Any],
        commodity_data: Dict[str, Any],
        forex_data: Dict[str, Any],
        bond_data: Dict[str, Any],
        capital_flows: List[Dict[str, Any]],
        news_list: List[Dict[str, Any]],
        pring_analysis: Dict[str, Any],
    ) -> str:
        """生成结构化Markdown报告，覆盖九大章节"""

        def fmt_percent(value: Any, decimals: int = 1) -> str:
            if value is None:
                return "—"
            if isinstance(value, str):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    return value
            if pd.isna(value):
                return "—"
            try:
                return f"{float(value):.{decimals}f}%"
            except (TypeError, ValueError):
                return "—"

        def fmt_number(value: Any, decimals: int = 2) -> str:
            if value is None:
                return "—"
            if isinstance(value, str):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    return value
            if pd.isna(value):
                return "—"
            try:
                return f"{float(value):.{decimals}f}"
            except (TypeError, ValueError):
                return "—"

        def fmt_bp(value: Any) -> str:
            if value is None:
                return "—"
            if isinstance(value, str):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    return value
            if pd.isna(value):
                return "—"
            try:
                return f"{float(value):.1f}"
            except (TypeError, ValueError):
                return "—"

        def fmt_bool(value: Any) -> str:
            if isinstance(value, bool):
                return "✓" if value else "✗"
            if isinstance(value, str):
                return value
            return "—"

        report_date = self.end_date.strftime("%Y-%m-%d")
        start_date_str = self.start_date.strftime("%Y-%m-%d")

        lines: List[str] = []
        lines.append(f"# 120日市场背景扫描报告 ({report_date})")
        lines.append("")
        lines.append(f"**📅 数据窗口**: {start_date_str} 至 {report_date} (120个自然日)")
        lines.append("**🔧 基于**: 120日背景扫描方案.md V3.1 + 统一数据源集成框架 V2.1")
        lines.append(f"**⏰ 生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # 市场结论
        lines.append("## 一、市场结论要点")
        lines.append("")
        conclusions: List[str] = []

        hs300 = stock_data.get('000300.SH')
        if hs300 and 'error' not in hs300:
            conclusions.append(
                f"- 过去120天，沪深300指数累计变化{fmt_percent(hs300.get('change_120d_pct'))}，趋势评级为「{hs300.get('trend_label', '—')}」"
            )

        cyb = stock_data.get('399006.SZ')
        if cyb and 'error' not in cyb:
            conclusions.append(
                f"- 创业板指数120日累计变化{fmt_percent(cyb.get('change_120d_pct'))}，趋势评级为「{cyb.get('trend_label', '—')}」"
            )

        dxy = forex_data.get('DXY') if forex_data else None
        if dxy and 'error' not in dxy:
            conclusions.append(
                f"- 美元指数(DXY) 近5日变化{fmt_percent(dxy.get('change_5d_pct'), 2)}，走势{dxy.get('trend', '观望')}"
            )

        us_bond = bond_data.get('US10Y') if bond_data else None
        if us_bond and 'error' not in us_bond:
            conclusions.append(
                f"- 美10Y国债收益率报{fmt_percent(us_bond.get('yield'), 2)}，5日变动{fmt_bp(us_bond.get('change_5d_bp'))}bp"
            )

        north_flow = None
        if capital_flows:
            for item in capital_flows:
                if item.get('type') == '北向资金' and 'error' not in item:
                    north_flow = item
                    break
        if north_flow and north_flow.get('daily') not in (None, '—'):
            conclusions.append(
                f"- 北向资金当日净流入{fmt_number(north_flow.get('daily'), 2)}亿元，近120日累计{fmt_number(north_flow.get('rolling_120'), 2)}亿元"
            )

        if 'stage' in pring_analysis and pring_analysis.get('stage') not in (None, 'N/A'):
            conclusions.append(
                f"- 普林格六阶段分析显示当前处于「{pring_analysis.get('stage')}」阶段，商品信号为{pring_analysis.get('commodity_signal', 'N/A')}"
            )

        if commodity_data:
            valid_trends = [
                f"{data.get('name', symbol)}({data.get('trend_label', '—')})"
                for symbol, data in commodity_data.items()
                if 'error' not in data
            ]
            if valid_trends:
                conclusions.append(f"- 商品基准趋势: {', '.join(valid_trends)}")

        if not conclusions:
            conclusions.append('- 数据收集过程中存在异常，部分指标暂未获取')

        lines.extend(conclusions)
        lines.append("")
        lines.append("---")
        lines.append("")

        # 股票市场
        lines.append("## 二、股票市场综述")
        lines.append("")
        lines.append("### 主要股指表现")
        lines.append("")
        lines.append("| 指数 | 代码 | 近5日% | 近120日% | >MA50? | >MA200? | MA50斜率 | 30日波动率% | 趋势评分 | 趋势标签 |")
        lines.append("|------|------|--------|----------|--------|---------|----------|-------------|----------|----------|")
        for symbol, data in stock_data.items():
            name = data.get('name', symbol)
            if 'error' in data:
                lines.append(f"| {name} | {symbol} | — | — | — | — | — | — | — | Error |")
                continue
            lines.append(
                "| {name} | {symbol} | {chg5} | {chg120} | {ma50} | {ma200} | {slope} | {vol} | {score} | {label} |".format(
                    name=name,
                    symbol=symbol,
                    chg5=fmt_percent(data.get('change_5d_pct')),
                    chg120=fmt_percent(data.get('change_120d_pct')),
                    ma50=fmt_bool(data.get('above_ma50')),
                    ma200=fmt_bool(data.get('above_ma200')),
                    slope=fmt_number(data.get('ma50_slope'), 4),
                    vol=fmt_percent(data.get('volatility_30d_pct')),
                    score=data.get('trend_score', '—'),
                    label=data.get('trend_label', '—')
                )
            )
        lines.append("")
        lines.append("---")
        lines.append("")

        # 商品
        lines.append("## 三、商品与黄金")
        lines.append("")
        lines.append("### 商品基准表现")
        lines.append("")
        lines.append("| 品种 | 代码 | 近5日% | 近120日% | 趋势评分 | 趋势标签 | 30日波动率% |")
        lines.append("|------|------|--------|----------|----------|----------|-------------|")
        for symbol, data in commodity_data.items():
            name = data.get('name', symbol)
            if 'error' in data:
                lines.append(f"| {name} | {symbol} | — | — | — | Error | — |")
                continue
            lines.append(
                "| {name} | {symbol} | {chg5} | {chg120} | {score} | {label} | {vol} |".format(
                    name=name,
                    symbol=symbol,
                    chg5=fmt_percent(data.get('change_5d_pct')),
                    chg120=fmt_percent(data.get('change_120d_pct')),
                    score=data.get('trend_score', '—'),
                    label=data.get('trend_label', '—'),
                    vol=fmt_percent(data.get('volatility_30d_pct'))
                )
            )
        lines.append("")
        lines.append("---")
        lines.append("")

        # 后续章节将追加

        # 汇率
        lines.append("## 四、汇率变动")
        lines.append("")
        lines.append("### 主要汇率表现")
        lines.append("")
        lines.append("| 汇率对 | 最新报价 | 近5日% | 近120日% | 趋势方向 | 备注 |")
        lines.append("|--------|----------|----------|------------|----------|------|")
        for symbol, entry in forex_data.items():
            display = entry.get('display', symbol)
            if entry.get('error'):
                lines.append(f"| {display} | — | — | — | — | {entry['error']} |")
                continue
            lines.append(
                "| {display} | {latest} | {chg5} | {chg120} | {trend} | {remark} |".format(
                    display=display,
                    latest=fmt_number(entry.get('latest'), 4),
                    chg5=fmt_percent(entry.get('change_5d_pct'), 2),
                    chg120=fmt_percent(entry.get('change_120d_pct'), 2),
                    trend=entry.get('trend', '—'),
                    remark=entry.get('metadata', {}).get('data_source') or entry.get('source', '—')
                )
            )
        lines.append("")
        lines.append("---")
        lines.append("")

        # 国债收益率
        lines.append("## 五、利率与债券收益率")
        lines.append("")
        lines.append("### 国债收益率表现")
        lines.append("")
        lines.append("| 品种 | 当前收益率 | 近5日变动(bp) | 近120日变动(bp) | 趋势 | 备注 |")
        lines.append("|------|------------|----------------|------------------|------|------|")
        for symbol, entry in bond_data.items():
            display = entry.get('display', symbol)
            if entry.get('error'):
                lines.append(f"| {display} | — | — | — | — | {entry['error']} |")
                continue
            lines.append(
                "| {display} | {current} | {chg5} | {chg120} | {trend} | {remark} |".format(
                    display=display,
                    current=fmt_percent(entry.get('yield'), 2),
                    chg5=fmt_bp(entry.get('change_5d_bp')),
                    chg120=fmt_bp(entry.get('change_120d_bp')),
                    trend=entry.get('trend', '—'),
                    remark=entry.get('metadata', {}).get('data_source') or entry.get('source', '—')
                )
            )
        lines.append("")
        lines.append("---")
        lines.append("")

        # 资金流向
        lines.append("## 六、资金流向总览")
        lines.append("")
        lines.append("| 资金类型 | 近一日净流入(亿元) | 120日累计(亿元) | 趋势 | 备注 |")
        lines.append("|----------|--------------------|-----------------|------|------|")
        for entry in capital_flows:
            if entry.get('error'):
                lines.append(f"| {entry.get('type', '—')} | — | — | — | {entry['error']} |")
                continue
            lines.append(
                "| {ctype} | {daily} | {total} | {trend} | {remark} |".format(
                    ctype=entry.get('type', '—'),
                    daily=fmt_number(entry.get('daily'), 2),
                    total=fmt_number(entry.get('rolling_120'), 2),
                    trend=entry.get('trend', '—'),
                    remark=entry.get('remark', '—')
                )
            )
        lines.append("")
        lines.append("---")
        lines.append("")

        # 财经要闻
        lines.append("## 七、财经要闻追踪")
        lines.append("")
        news_section = self.news_collector.generate_news_section(news_list)
        lines.append(news_section)
        lines.append("")
        lines.append("---")
        lines.append("")

        # 普林格阶段
        lines.append("## 八、普林格阶段推断（集成库存周期矫正）")
        lines.append("")
        if pring_analysis.get('error'):
            lines.append(f"- **分析状态**: 计算过程中遇到错误: {pring_analysis['error']}")
            lines.append("- **可能阶段**: N/A")
            lines.append("- **置信度评估**: 数据不足")
        else:
            lines.append(f"- **可能阶段**: {pring_analysis.get('stage', 'N/A')}")
            lines.append("- **判断依据**: 债券/股票/商品信号分析（商品信号已集成库存周期矫正）")
            lines.append(f"- **置信度评估**: {pring_analysis.get('confidence', 0)}%")
        lines.append("")
        lines.append("### 商品信号矫正详情")
        lines.append("")
        if not pring_analysis.get('error'):
            technical_score = pring_analysis.get('technical_score', 0)
            inventory_score = pring_analysis.get('inventory_score', 0)
            commodity_score = pring_analysis.get('commodity_score', 0)
            inventory_stage = pring_analysis.get('inventory_stage', 'N/A')
            commodity_signal = pring_analysis.get('commodity_signal', 'N/A')
            lines.append(f"- **技术面评分**: {technical_score:.1f}/35分 (基于WTI/Brent原油、COMEX铜、现货黄金、BCOM指数)")
            lines.append(f"- **库存周期评分**: {inventory_score:.1f}/65分 (PPI 30%、PMI 25%、工业增加值20%、BDI 15%、CPI 10%)")
            lines.append(f"- **综合评分**: {commodity_score:.1f}/100分 = 技术面×35% + 库存周期×65%")
            lines.append(f"- **库存周期阶段**: {inventory_stage}")
            lines.append(f"- **商品信号**: {commodity_signal} (≥70分Bullish，≤30分Bearish)")
        else:
            lines.append("- **技术面评分**: 数据缺失")
            lines.append("- **库存周期评分**: 数据缺失")
            lines.append("- **综合评分**: N/A")
            lines.append("- **库存周期阶段**: N/A")
            lines.append("- **商品信号**: N/A")
        lines.append("")
        lines.append("---")
        lines.append("")

        # 附注
        lines.append("## 九、附注说明")
        lines.append("")
        sources_used = set()
        for data in list(stock_data.values()) + list(commodity_data.values()):
            if isinstance(data, dict) and 'source' in data:
                sources_used.add(data['source'])
        for entry in forex_data.values():
            if isinstance(entry, dict) and 'source' in entry:
                sources_used.add(entry['source'])
        for entry in bond_data.values():
            if isinstance(entry, dict) and 'source' in entry:
                sources_used.add(entry['source'])

        if sources_used:
            lines.append(f"- **主要数据源**: {', '.join(sorted(sources_used))}")
        else:
            lines.append("- **主要数据源**: 自动采集未成功，需人工确认")
        lines.append(f"- **数据窗口**: {start_date_str} 至 {report_date} (120个自然日)")
        lines.append("- **计算标准**: 涨跌幅保留1位小数(%)，价格保留2位小数，斜率保留4位小数")
        lines.append("- **趋势评分**: 收益趋势、均线位置、中期趋势、短期动量四维加总")
        lines.append("- **普林格分析**: 技术面35% + 库存周期65%，强化宏观验证")
        lines.append("")
        lines.append("### 合规声明")
        lines.append("")
        lines.append("本报告仅供研究参考，不构成任何投资建议。数据来源于公开市场，计算结果仅反映历史情况，不代表未来走势。投资者应基于自身情况做出独立判断。")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("**📄 报告基于**: 《120日背景扫描方案.md V3.1》")
        lines.append("**🔧 技术框架**: 统一数据源集成框架 V2.1")
        lines.append("**🆕 增强功能**: 汇率、债券、资金流向与财经要闻集成输出")
        lines.append(f"**⏰ 生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        return "\n".join(lines)

    async def run_scan(self, output_file: str):
        """执行完整的120日背景扫描"""
        print(f"[开始] 120日背景扫描...")
        print(f"[数据窗口] {self.start_date.strftime('%Y-%m-%d')} 至 {self.end_date.strftime('%Y-%m-%d')}")

        # 数据收集阶段
        print("\n[收集] 股票市场数据...")
        stock_data = await self.collect_stock_data()

        print("[收集] 商品基准数据...")
        commodity_data = await self.collect_commodity_data()

        print("[收集] 汇率与国债数据...")
        forex_data = await self.collect_forex_data()
        bond_data = await self.collect_bond_yield_data()

        print("[收集] 资金流向与财经要闻...")
        capital_flows = await self.collect_capital_flow_data()
        news_list = await self.collect_financial_news()

        print("[分析] 执行普林格六阶段分析...")
        pring_analysis = await self.analyze_pring_cycle()

        # 报告生成阶段
        print("[生成] 报告...")
        report_content = self.generate_report(
            stock_data,
            commodity_data,
            forex_data,
            bond_data,
            capital_flows,
            news_list,
            pring_analysis,
        )

        # 保存报告
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report_content)

        print(f"[完成] 报告生成完成: {output_file}")

        # 输出简要统计
        print(f"\n[统计] 扫描结果:")
        print(f"   股票指数: {len(stock_data)}个")
        print(f"   商品基准: {len(commodity_data)}个")
        print(f"   普林格阶段: {pring_analysis.get('stage', 'N/A')}")
        print(f"   商品信号: {pring_analysis.get('commodity_signal', 'N/A')}")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='120日背景扫描器')
    parser.add_argument('--date', required=True, help='扫描日期 (YYYY-MM-DD)')
    parser.add_argument('--output', required=True, help='输出文件路径')

    args = parser.parse_args()

    try:
        # 验证日期格式
        datetime.strptime(args.date, '%Y-%m-%d')

        # 创建扫描器并执行
        scanner = BackgroundScanner120D(args.date)
        await scanner.run_scan(args.output)

    except ValueError as e:
        print(f"[错误] 日期格式错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[错误] 执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
