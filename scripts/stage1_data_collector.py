#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 1: Market Data Collector (V3.1 解耦架构)
职责: 收集所有市场数据,输出标准JSON格式
输出: data/YYYYMMDD_market_data.json
"""

import asyncio
import json
import argparse
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path
import shutil
import pandas as pd
import numpy as np
from functools import lru_cache

# 导入核心模块
from datasource import get_manager
from datasource.calculators.technical_indicators import TechnicalIndicatorCalculator
from datasource.models.market_data_contract import (
    MarketDataContract,
    StockIndexData,
    CommodityData,
    ForexData,
    BondYieldData,
    FundFlowData,
    FinancialNewsItem,
    MacroIndicatorData,
    MonetaryPolicyData
)


class MarketDataCollector:
    """市场数据收集器 - 解耦版本

    职责:
    - 收集股票指数数据(A股)
    - 收集商品数据
    - 收集汇率数据
    - 收集债券收益率数据
    - 收集资金流向数据
    - 输出标准化JSON格式

    不负责:
    - Pring分析
    - 报告生成
    - 任何业务逻辑计算
    """

    def __init__(self, end_date: str):
        self.end_date = end_date

        # 计算开始日期(120天 + 200天缓冲用于MA200计算)
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=120)
        self.start_date = start_dt.strftime("%Y-%m-%d")

        # 获取数据源管理器
        self.manager = get_manager()
        self.manager.set_primary_source('tushare')
        if hasattr(self.manager, 'fallback_sources'):
            self.manager.fallback_sources = [
                source for source in self.manager.fallback_sources
                if source not in {'international_finance'}
            ]

        # A股指数配置
        self.indices = {
            '000300': '沪深300',
            '000016': '上证50',
            '399006': '创业板指',
            '399001': '深证成指',
            '000001': '上证指数'
        }

        # 技术指标计算器
        self.tech_calc = TechnicalIndicatorCalculator()

        # 数据完整性跟踪
        self.missing_items = defaultdict(list)

        # 统一的配置常量，便于Stage 2引用
        self.commodity_configs = [
            {'symbol': 'GC=F', 'name': 'COMEX黄金', 'unit': '$/oz', 'search_query': 'COMEX黄金 最新报价 年内涨跌'},
            {'symbol': 'CL=F', 'name': 'WTI原油', 'unit': '$/barrel', 'search_query': 'WTI原油 最新价 YTD'},
            {'symbol': 'BZ=F', 'name': 'Brent原油', 'unit': '$/barrel', 'search_query': 'Brent原油 价格 年内涨跌'},
            {'symbol': 'HG=F', 'name': 'COMEX铜', 'unit': '$/lb', 'search_query': 'COMEX铜 最新价 年初至今'},
            {'symbol': 'BCOM', 'name': 'BCOM指数', 'unit': '点', 'search_query': 'BCOM 指数 最新点位'},
            {'symbol': 'GSG', 'name': 'GSG ETF', 'unit': '$', 'search_query': 'GSG ETF price today'}
        ]

        self.fund_flow_configs = [
            {'key': 'northbound', 'name': '北向资金', 'type': 'northbound', 'search_query': '北向资金 近5日 净买入'},
            {'key': 'southbound', 'name': '南向资金', 'type': 'southbound', 'search_query': '南向资金 近5日 净买入'},
            {'key': 'etf', 'name': 'ETF资金流', 'type': 'etf', 'search_query': 'A股ETF 资金流向 近5日'},
            {'key': 'margin', 'name': '融资融券', 'type': 'margin', 'search_query': '融资融券余额 近5日 变化'}
        ]
        # TuShare cn_pmi 列名映射（Doc#2）
        self.pmi_column_map = {
            'pmi': ['pmi010100', 'pmi020202', 'pmi010000'],
            'pmi_new_orders': ['pmi010500', 'pmi010501', 'pmi010502'],
            'pmi_production': ['pmi010400', 'pmi010401', 'pmi010402']
        }

        self.macro_indicator_config = [
            {
                'key': 'ppi',
                'name': 'PPI',
                'full_name': '工业生产者出厂价格指数',
                'unit': '%',
                'weight': 30,
                'search_query': '中国PPI 工业生产者出厂价格指数 国家统计局 最新数据',
                'source_hint': 'TuShare cn_ppi',
                'preferred_source': 'tushare'
            },
            {
                'key': 'cpi',
                'name': 'CPI',
                'full_name': '居民消费价格指数',
                'unit': '%',
                'weight': 20,
                'search_query': '中国CPI 居民消费价格指数 国家统计局 最新数据',
                'source_hint': 'TuShare cn_cpi',
                'preferred_source': 'tushare'
            },
            {
                'key': 'pmi',
                'name': 'PMI',
                'full_name': '制造业采购经理指数',
                'unit': '点',
                'weight': 25,
                'search_query': '中国PMI 制造业采购经理指数 国家统计局 最新数据',
                'source_hint': 'TuShare cn_pmi',
                'preferred_source': 'tushare'
            },
            {
                'key': 'pmi_new_orders',
                'name': 'PMI新订单',
                'full_name': '制造业PMI新订单指数',
                'unit': '点',
                'weight': 15,
                'search_query': '制造业 PMI 新订单 最新 数据',
                'source_hint': 'TuShare cn_pmi',
                'preferred_source': 'tushare'
            },
            {
                'key': 'pmi_production',
                'name': 'PMI生产',
                'full_name': '制造业PMI生产指数',
                'unit': '点',
                'weight': 10,
                'search_query': '制造业 PMI 生产 指数 最新 数据',
                'source_hint': 'TuShare cn_pmi',
                'preferred_source': 'tushare'
            },
            {
                'key': 'gdp',
                'name': 'GDP',
                'full_name': '国内生产总值同比',
                'unit': '%',
                'weight': 20,
                'search_query': '中国 GDP 增长率 最新 数据',
                'source_hint': 'TuShare cn_gdp',
                'preferred_source': 'tushare'
            },
            {
                'key': 'industrial',
                'name': '工业增加值',
                'full_name': '规模以上工业增加值',
                'unit': '%',
                'weight': 15,
                'search_query': '中国工业增加值 同比增长 国家统计局 最新数据',
                'source_hint': 'stats.gov.cn',
                'preferred_source': 'websearch'
            },
            {
                'key': 'industrial_sales',
                'name': '工业企业营收',
                'full_name': '规模以上工业企业营业收入',
                'unit': '%',
                'weight': 10,
                'search_query': '规模以上工业企业 营业收入 同比 最新 数据',
                'source_hint': 'stats.gov.cn',
                'preferred_source': 'websearch'
            },
            {
                'key': 'bdi',
                'name': 'BDI指数',
                'full_name': '波罗的海干散货指数',
                'unit': '点',
                'weight': 10,
                'search_query': 'BDI 指数 最新 数据',
                'source_hint': 'investing.com',
                'preferred_source': 'websearch'
            }
        ]

        self.monetary_policy_config = [
            {
                'key': 'rrr',
                'name': '存款准备金率',
                'full_name': '金融机构存款准备金率',
                'unit': '%',
                'weight': 30,
                'search_query': '中国人民银行 存款准备金率 最新调整',
                'source_hint': 'pbc.gov.cn',
                'preferred_source': 'websearch'
            },
            {
                'key': 'dr007',
                'name': 'DR007',
                'full_name': '银行间质押式回购加权利率（7天）',
                'unit': '%',
                'weight': 25,
                'search_query': 'DR007 利率 最新 数据',
                'source_hint': 'TuShare repo_daily',
                'preferred_source': 'tushare'
            },
            {
                'key': 'reverse_repo',
                'name': '7天逆回购利率',
                'full_name': '公开市场7天逆回购操作利率',
                'unit': '%',
                'weight': 30,
                'search_query': '央行公开市场 7天逆回购 最新 利率',
                'source_hint': 'pbc.gov.cn',
                'preferred_source': 'websearch'
            },
            {
                'key': 'mlf',
                'name': 'MLF利率',
                'full_name': '中期借贷便利(MLF)一年期利率',
                'unit': '%',
                'weight': 20,
                'search_query': '中国人民银行 MLF 1年期 利率 最新',
                'source_hint': 'pbc.gov.cn',
                'preferred_source': 'websearch'
            },
            {
                'key': 'tsf',
                'name': 'TSF社融增速',
                'full_name': '社会融资规模存量同比增速',
                'unit': '%',
                'weight': 25,
                'search_query': '社会融资规模 增速 最新数据',
                'source_hint': 'TuShare sf_month',
                'preferred_source': 'tushare'
            },
            {
                'key': 'm0',
                'name': 'M0增速',
                'full_name': '流通中现金M0同比增速',
                'unit': '%',
                'weight': 15,
                'search_query': '中国M0货币供应量 同比增速 最新',
                'source_hint': 'TuShare cn_m',
                'preferred_source': 'tushare'
            },
            {
                'key': 'm1',
                'name': 'M1增速',
                'full_name': '狭义货币M1同比增速',
                'unit': '%',
                'weight': 20,
                'search_query': '中国M1货币供应量 同比增速 最新 数据',
                'source_hint': 'TuShare cn_m',
                'preferred_source': 'tushare'
            },
            {
                'key': 'm2',
                'name': 'M2增速',
                'full_name': '广义货币M2同比增速',
                'unit': '%',
                'weight': 15,
                'search_query': '中国M2货币供应量 同比增速 最新',
                'source_hint': 'TuShare cn_m',
                'preferred_source': 'tushare'
            }
        ]

    async def collect_all_data(self) -> MarketDataContract:
        """收集所有市场数据并返回标准化合约"""
        print(f"\n{'='*60}")
        print(f"Stage 1: 市场数据收集")
        print(f"日期范围: {self.start_date} -> {self.end_date}")
        print(f"{'='*60}\n")

        # 并行收集所有数据
        stock_task = self.collect_stock_indices()
        commodity_task = self.collect_commodities()
        forex_task = self.collect_forex()
        bond_task = self.collect_bonds()
        fund_flow_task = self.collect_fund_flow()
        macro_task = self.collect_macro_indicators()
        monetary_task = self.collect_monetary_policy()

        # 等待所有数据收集完成
        results = await asyncio.gather(
            stock_task,
            commodity_task,
            forex_task,
            bond_task,
            fund_flow_task,
            macro_task,
            monetary_task,
            return_exceptions=True
        )

        stock_indices, commodities, forex, bonds, fund_flow, macro_indicators, monetary_policy = results

        # 处理异常
        if isinstance(stock_indices, Exception):
            print(f"[ERROR] 股票数据收集失败: {stock_indices}")
            stock_indices = []
        if isinstance(commodities, Exception):
            print(f"[ERROR] 商品数据收集失败: {commodities}")
            commodities = []
        if isinstance(forex, Exception):
            print(f"[ERROR] 汇率数据收集失败: {forex}")
            forex = []
        if isinstance(bonds, Exception):
            print(f"[ERROR] 债券数据收集失败: {bonds}")
            bonds = []
        if isinstance(fund_flow, Exception):
            print(f"[ERROR] 资金流向收集失败: {fund_flow}")
            fund_flow = {}
        if isinstance(macro_indicators, Exception):
            print(f"[ERROR] 宏观指标收集失败: {macro_indicators}")
            macro_indicators = {}
        if isinstance(monetary_policy, Exception):
            print(f"[ERROR] 货币政策收集失败: {monetary_policy}")
            monetary_policy = {}

        # 构建元数据
        metadata = {
            'date': self.end_date,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'generation_time': datetime.now().isoformat(),
            'data_completeness': self._calculate_completeness(
                stock_indices, commodities, forex, bonds, fund_flow
            ),
            'missing_items': {k: v for k, v in self.missing_items.items()}
        }

        # 构建合约
        contract = MarketDataContract(
            metadata=metadata,
            stock_indices=stock_indices,
            commodities=commodities,
            forex=forex,
            bonds=bonds,
            fund_flow=fund_flow,
            financial_news=[],  # 财经要闻留待后续补充
            macro_indicators=macro_indicators,
            monetary_policy=monetary_policy
        )

        print(f"\n{'='*60}")
        print(f"数据收集完成:")
        print(f"  股票指数: {len(stock_indices)}/{len(self.indices)}")
        print(f"  商品数据: {len(commodities)}/6")
        print(f"  汇率数据: {len(forex)}/3")
        print(f"  债券数据: {len(bonds)}/3")
        print(f"  资金流向: {len(fund_flow)}/4")
        macro_expected = max(len(macro_indicators), len(getattr(self, "macro_indicator_config", [])))
        monetary_expected = max(len(monetary_policy), len(getattr(self, "monetary_policy_config", [])))
        print(f"  宏观指标: {len(macro_indicators)}/{macro_expected}")
        print(f"  货币政策: {len(monetary_policy)}/{monetary_expected}")
        print(f"  数据完整度: {metadata['data_completeness']:.1%}")
        print(f"{'='*60}\n")

        return contract

    async def collect_stock_indices(self) -> List[StockIndexData]:
        """收集股票指数数据"""
        print("[1/5] 收集股票指数数据...")

        stock_data_list = []

        # 数据获取需要更长历史(用于MA200计算)
        fetch_start_dt = datetime.strptime(self.start_date, "%Y-%m-%d") - timedelta(days=200)
        fetch_start = fetch_start_dt.strftime("%Y-%m-%d")

        for symbol, name in self.indices.items():
            try:
                print(f"  获取 {name} ({symbol})...")

                # 获取指数数据
                response = await self.manager.get_index_daily(
                    symbol, fetch_start, self.end_date
                )

                if response.error or response.data is None or response.data.empty:
                    print(f"    [SKIP] 数据获取失败")
                    self._record_missing(
                        'stock_indices',
                        symbol,
                        name,
                        f"TuShare返回空/错误: {response.error}",
                        search_query=f"{name} 指数 日线 数据 最新",
                        source_hint='tushare.pro'
                    )
                    continue

                # 计算技术指标
                data = self._prepare_price_data(response.data)
                if data is None:
                    continue

                # 使用TechnicalIndicatorCalculator的calculate_trend_score方法
                analysis = self.tech_calc.calculate_trend_score(data)

                # 计算120日涨跌幅(不在analysis中)
                change_120d = self._calculate_change(data, 120)

                # 构建数据对象
                stock_info = StockIndexData(
                    symbol=symbol,
                    name=name,
                    current_price=float(analysis['current_price']),
                    change_5d=float(analysis['change_5d']),
                    change_120d=change_120d,
                    above_ma50=bool(analysis['above_ma50']),
                    above_ma200=bool(analysis['above_ma200']),
                    ma50_slope=float(analysis['ma50_slope']),
                    volatility_30d=float(analysis['volatility_30d']),
                    trend_score=int(analysis['trend_score']),
                    trend_label=str(analysis['trend_label']),
                    source=response.source
                )

                stock_data_list.append(stock_info)
                print(f"    [OK] 收盘:{analysis['current_price']:.2f}, 120日涨跌:{change_120d:+.1f}%")

            except Exception as e:
                print(f"    [ERROR] {name} 处理失败: {e}")
                fallback = await self._fallback_index_from_tushare(symbol, name, fetch_start, self.end_date)
                if fallback:
                    stock_data_list.append(fallback)
                    print(f"    [OK] {name} 通过 TuShare index_daily 兜底成功")
                else:
                    self._record_missing(
                        'stock_indices',
                        symbol,
                        name,
                        f"TuShare返回空/错误: {e}",
                        search_query=f"{name} 收盘价 历史数据",
                        source_hint='tushare.pro',
                        attempted_tushare=True
                    )
                continue

        return stock_data_list

    async def _fallback_index_from_tushare(self, symbol: str, name: str, start_date: str, end_date: str) -> Optional[StockIndexData]:
        """
        当 DataSourceManager 获取失败时，直接调用 TuShare index_daily 兜底一次，尽量补齐 000016 等指数。
        """
        try:
            import pandas as pd
            import tushare as ts
            token = os.getenv("TUSHARE_TOKEN")
            pro = ts.pro_api(token) if token else ts.pro_api()
            ts_code = f"{symbol}.SH" if symbol.startswith("0") else f"{symbol}.SZ"
            last_error = None
            for attempt in range(3):
                try:
                    df = pro.index_daily(ts_code=ts_code, start_date=start_date.replace("-", ""), end_date=end_date.replace("-", ""))
                    if df is None or df.empty:
                        raise ValueError("empty dataframe")
                    df = df.sort_values("trade_date")
                    df["close"] = pd.to_numeric(df["close"], errors="coerce")
                    df = df.dropna(subset=["close"])
                    if df.empty:
                        raise ValueError("close series empty")
                    closes = df["close"]
                    current = float(closes.iloc[-1])
                    change_5d = (current / closes.iloc[-6] - 1) * 100 if len(closes) > 6 else 0.0
                    change_120d = (current / closes.iloc[-121] - 1) * 100 if len(closes) > 121 else 0.0
                    ma50 = closes.rolling(50).mean().iloc[-1] if len(closes) >= 50 else closes.mean()
                    ma200 = closes.rolling(200).mean().iloc[-1] if len(closes) >= 200 else ma50
                    above_ma50 = current > (ma50 or current)
                    above_ma200 = current > (ma200 or current)
                    ma50_slope = float(closes.rolling(50).mean().diff().iloc[-1] or 0.0) if len(closes) >= 51 else 0.0
                    vol30 = float(closes.pct_change().rolling(30).std().iloc[-1] * (252 ** 0.5) * 100) if len(closes) > 30 else 0.0
                    return StockIndexData(
                        symbol=symbol,
                        name=name,
                        current_price=current,
                        change_5d=change_5d,
                        change_120d=change_120d,
                        above_ma50=above_ma50,
                        above_ma200=above_ma200,
                        ma50_slope=ma50_slope,
                        volatility_30d=vol30,
                        trend_score=50,
                        trend_label="中性",
                        source="TuShare index_daily(fallback)"
                    )
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    await asyncio.sleep(1)
                    continue
            if last_error:
                print(f"    [WARN] index_daily fallback retries exhausted for {name}: {last_error}")
            return None
        except Exception:
            return None

    async def collect_commodities(self) -> List[CommodityData]:
        """收集商品数据

        注意: 此方法返回占位符,实际数据需要通过MCP WebSearch/WebFetch获取
        """
        print("[2/5] 收集商品数据...")

        commodity_list = []
        print("  [INFO] Stage1已禁用Yahoo/Investing fallback，商品行情需由Stage2/MCP补充")

        for config in self.commodity_configs:
            symbol = config['symbol']
            name = config['name']
            unit = config['unit']
            print(f"  获取 {name}({symbol}) ...")

            self._record_missing(
                'commodities',
                symbol,
                name,
                'Stage1禁用Yahoo/Investing fallback，需MCP补充实时行情',
                search_query=config.get('search_query'),
                source_hint='MCP WebSearch'
            )
            commodity_data = CommodityData(
                symbol=symbol,
                name=name,
                current_price=None,
                unit=unit,
                daily_change=None,
                ytd_change=None,
                trend="待MCP获取",
                source="MCP WebFetch待获取",
                timestamp=self.end_date
            )

            commodity_list.append(commodity_data)

        return commodity_list

    async def collect_forex(self) -> List[ForexData]:
        """收集汇率数据"""
        print("[3/5] 收集汇率数据...")

        forex_list = []
        forex_configs = [
            {'symbol': 'USDCNY', 'pair': 'USDCNY', 'name': 'USD/CNY在岸'},
            {'symbol': 'USDCNH', 'pair': 'USDCNH', 'name': 'USD/CNH离岸'},
            {'symbol': 'DXY', 'pair': 'DXY', 'name': 'DXY美元指数'}
        ]

        print("  [INFO] Stage1尝试TuShare fx_daily，若无数据则交由 Stage2/MCP")
        for config in forex_configs:
            fx_entry = await self._fetch_fx_from_tushare(config['symbol'], config['name'])
            if fx_entry:
                forex_list.append(fx_entry)
                print(f"  [OK] {config['name']} 通过 TuShare fx_daily 获取")
                continue
            self._record_missing(
                'forex',
                config['symbol'],
                config['name'],
                'TuShare fx_daily 返回空，需MCP/Tavily补充',
                search_query=f"{config['name']} 汇率 最新 数据",
                source_hint='MCP WebSearch',
                preferred_source='tushare',
                attempted_tushare=True
            )

        return forex_list

    async def collect_bonds(self) -> List[BondYieldData]:
        """收集债券收益率数据"""
        print("[4/5] 收集债券收益率数据...")
        print("  [INFO] Stage1尝试 TuShare/中债接口，失败再交 Stage2/MCP")

        bond_list = []
        bond_configs = [
            {'symbol': 'US10Y', 'name': '美国10年期国债'},
            {'symbol': 'CN10Y', 'name': '中国10年期国债'},
            {'symbol': 'CN10Y_CDB', 'name': '中国10年期国开债'}
        ]

        for config in bond_configs:
            bond_entry = await self._fetch_bond_yield_from_tushare(config['symbol'], config['name'])
            if bond_entry:
                bond_list.append(bond_entry)
                print(f"  [OK] {config['name']} 通过 TuShare/中债接口获取")
                continue
            self._record_missing(
                'bonds',
                config['symbol'],
                config['name'],
                'TuShare/中债接口无数据，需MCP WebSearch补充',
                search_query=f"{config['name']} 收益率 最新",
                source_hint='MCP WebSearch',
                preferred_source='tushare',
                attempted_tushare=True
            )
            bond = BondYieldData(
                symbol=config['symbol'],
                name=config['name'],
                current_yield=None,
                change_5d_bp=None,
                change_120d_bp=None,
                trend="待MCP获取",
                source="MCP WebFetch待获取",
                is_estimated=True
            )
            bond_list.append(bond)

        return bond_list

    async def collect_fund_flow(self) -> Dict[str, FundFlowData]:
        """收集资金流向数据

        注意: 资金流向数据需要通过MCP WebSearch获取
        """
        print("[5/5] 收集资金流向数据...")
        print("  [INFO] 资金流向数据优先使用TuShare/交易所数据，缺口再由MCP WebSearch补充")

        fund_flow_dict: Dict[str, FundFlowData] = {}
        pending_missing: List[Dict[str, str]] = []

        for flow in self.fund_flow_configs:
            fund_flow_dict[flow['key']] = FundFlowData(
                type=flow['type'],
                recent_5d=None,
                total_120d=None,
                trend='待获取',
                source='MCP WebSearch待获取',
                note='需要MCP WebSearch实时获取'
            )
            pending_missing.append(flow)

        # 0) TuShare 沪深港通北向/南向资金（最近开市日）
        nb_val, sb_val = await self._fetch_hsgt_from_tushare()
        if nb_val is not None:
            fund_flow_dict['northbound'] = FundFlowData(
                type='northbound',
                recent_5d=nb_val,
                total_120d=None,
                trend='流入' if nb_val > 0 else '流出' if nb_val < 0 else '未知',
                source='TuShare moneyflow_hsgt',
                note='最新交易日北向资金（十亿元）',
            )
            pending_missing = [item for item in pending_missing if item['key'] != 'northbound']
            print("  [OK] 北向资金已通过 TuShare moneyflow_hsgt 获取")
        if sb_val is not None:
            fund_flow_dict['southbound'] = FundFlowData(
                type='southbound',
                recent_5d=sb_val,
                total_120d=None,
                trend='流入' if sb_val > 0 else '流出' if sb_val < 0 else '未知',
                source='TuShare moneyflow_hsgt',
                note='最新交易日南向资金（十亿元）',
            )
            pending_missing = [item for item in pending_missing if item['key'] != 'southbound']
            print("  [OK] 南向资金已通过 TuShare moneyflow_hsgt 获取")

        # 1) TuShare 融资融券余额 -> fund_flow.margin
        margin_entry = await self._fetch_margin_flow_from_tushare()
        if margin_entry:
            fund_flow_dict['margin'] = margin_entry
            pending_missing = [item for item in pending_missing if item['key'] != 'margin']
            print("  [OK] 融资融券余额已通过TuShare margin转换为近5日/120日变化")
        else:
            print("  [WARN] TuShare margin暂未返回数据，融资融券仍需MCP补充")

        # 2) 日度成交统计（daily_info）估算ETF热度
        etf_entry = await self._fetch_etf_flow_proxy()
        if etf_entry:
            fund_flow_dict['etf'] = etf_entry
            pending_missing = [item for item in pending_missing if item['key'] != 'etf']
            print("  [OK] ETF资金流以TuShare daily_info成交额估算（已注明来源）")
        else:
            print("  [WARN] 无法从TuShare daily_info获取成交统计，ETF仍记为缺口")

        # 其余类型仍需 WebSearch
        for flow in pending_missing:
            print(f"  [{flow['name']}] 占位符已创建,需MCP补充")
            self._record_missing(
                'fund_flow',
                flow['key'],
                flow['name'],
                'TuShare/公共接口不可用，需MCP WebSearch',
                search_query=flow['search_query'],
                source_hint='eastmoney.com',
                attempted_tushare=flow['key'] in {'northbound', 'southbound'}
            )

        return fund_flow_dict

    async def _fetch_hsgt_from_tushare(self) -> (Optional[float], Optional[float]):
        """尝试获取最近开市日的北向/南向资金（十亿元）"""
        try:
            import tushare as ts  # 局部导入，避免环境缺少时报错
            token = os.getenv("TUSHARE_TOKEN")
            pro = ts.pro_api(token) if token else ts.pro_api()
            open_dates = self._get_recent_open_dates(count=5)
            last_error = None
            for trade_date in open_dates[::-1]:  # 从最近往前最多 5 个开市日
                for attempt in range(3):
                    try:
                        df = pro.moneyflow_hsgt(trade_date=trade_date)
                        if df is None or df.empty:
                            break
                        north = df.iloc[0].get('north_money')
                        south = df.iloc[0].get('south_money')
                        nb_val = float(north) if north is not None else None  # TuShare 单位：亿元
                        sb_val = float(south) if south is not None else None
                        if nb_val is not None or sb_val is not None:
                            return nb_val, sb_val
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_error = exc
                        await asyncio.sleep(1)
                # 尝试完此交易日继续往前
            if last_error:
                print(f"  [WARN] moneyflow_hsgt retries exhausted: {last_error}")
            return None, None
        except Exception:
            return None, None

    async def _fetch_fx_from_tushare(self, symbol: str, name: str) -> Optional[ForexData]:
        """尝试用 TuShare fx_daily 获取在岸/离岸汇率"""
        if symbol not in {"USDCNY", "USDCNH"}:
            return None
        try:
            import tushare as ts
            pro = ts.pro_api()
            open_dates = self._get_recent_open_dates(count=5)
            for trade_date in open_dates[::-1]:  # 最近 5 个开市日尝试
                df = pro.fx_daily(ts_code=symbol, start_date=trade_date, end_date=trade_date)
                if df is None or df.empty:
                    continue
                row = df.iloc[-1]
                rate = row.get("bid_close") or row.get("ask_close") or row.get("bid_open")
                if rate is None:
                    continue
                return ForexData(
                    pair=symbol,
                    name=name,
                    current_rate=float(rate),
                    daily_change=None,
                    change_120d=None,
                    trend='平稳',
                    source='TuShare fx_daily',
                    timestamp=trade_date,
                    note='TuShare fx_daily 最近开市日'
                )
            return None
        except Exception:
            return None

    @lru_cache(maxsize=1)
    def _get_recent_open_dates(self, count: int = 5) -> List[str]:
        """获取最近的开市日列表（默认 5 个），用于 T+1 数据回退。"""
        try:
            import tushare as ts
            pro = ts.pro_api()
            end_dt = datetime.strptime(self.end_date, "%Y-%m-%d")
            cal = pro.trade_cal(
                exchange='',
                start_date=(end_dt - timedelta(days=30)).strftime("%Y%m%d"),
                end_date=end_dt.strftime("%Y%m%d")
            )
            open_dates = [d for d in cal[cal.is_open == 1].cal_date]
            return open_dates[-count:] if open_dates else []
        except Exception:
            return []

    async def _fetch_bond_yield_from_tushare(self, symbol: str, name: str) -> Optional[BondYieldData]:
        """通过 DataSourceManager→InternationalFinanceAdapter 优先调用 TuShare us_tycr / ETF 代理获取债券收益率"""
        try:
            resp = await self.manager.get_bond_yield_data(symbol, self.start_date, self.end_date)
            data = getattr(resp, "data", None)
            if data is None or len(data) == 0:
                return None

            df = data.sort_values("date")
            yield_series = df["yield_rate"] if "yield_rate" in df.columns else df["close"]
            current = float(yield_series.iloc[-1])

            def _calc_bp(series, window):
                if len(series) <= window:
                    return None
                return float((series.iloc[-1] - series.iloc[-1 - window]) * 100)

            change_5d_bp = _calc_bp(yield_series, 5)
            change_120d_bp = _calc_bp(yield_series, 120)

            trend = "平稳"
            if change_5d_bp is not None:
                if change_5d_bp > 0:
                    trend = "上行"
                elif change_5d_bp < 0:
                    trend = "下行"

            source_label = resp.metadata.get("data_source") if resp and resp.metadata else resp.source

            return BondYieldData(
                symbol=symbol,
                name=name,
                current_yield=current,
                change_5d_bp=change_5d_bp,
                change_120d_bp=change_120d_bp,
                trend=trend,
                source=source_label or "TuShare us_tycr",
                is_estimated=False
            )
        except Exception as exc:
            print(f"  [WARN] 通过TuShare获取{symbol}失败: {exc}")
            return None

    async def collect_macro_indicators(self) -> Dict[str, MacroIndicatorData]:
        """
        收集宏观经济指标 - Pring第一层(库存周期)必需数据

        数据项: PPI, PMI, 工业增加值, BDI, CPI
        数据来源: 100% MCP WebSearch (国家统计局、央行等权威来源)
        """
        print("[6/8] 收集宏观经济指标...")
        print("  [INFO] 宏观指标用于Pring第一层库存周期分析")
        print("  [INFO] 优先使用TuShare (PPI/CPI/PMI/GDP)，BDI与工业营收缺口由MCP WebSearch补齐")

        macro_dict = {}
        indicators = self.macro_indicator_config
        pending_tushare_missing: List[Dict[str, Any]] = []

        for indicator in indicators:
            preferred_source = indicator.get('preferred_source', 'websearch')
            print(f"  获取 {indicator['name']}...")
            if preferred_source == 'tushare':
                print(f"    [INFO] 优先使用TuShare: {indicator['search_query']}")
            else:
                print(f"    [INFO] 需要MCP WebSearch: {indicator['search_query']}")

            placeholder_source = (
                f'待TuShare获取({indicator["source_hint"]})'
                if preferred_source == 'tushare'
                else f'待MCP WebSearch获取({indicator["source_hint"]})'
            )

            macro_dict[indicator['key']] = MacroIndicatorData(
                indicator_name=indicator['name'],
                current_value=None,
                previous_value=None,
                change_rate=None,
                unit=indicator['unit'],
                date=self.end_date,
                source=placeholder_source,
                is_estimated=True
            )
            missing_reason = (
                'TuShare暂未返回数据，需后续补录'
                if preferred_source == 'tushare'
                else 'TuShare/本地无数据，需MCP WebSearch'
            )
            if preferred_source == 'websearch':
                self._record_missing(
                    'macro_indicators',
                    indicator['key'],
                    indicator['name'],
                    missing_reason,
                    search_query=indicator['search_query'],
                    source_hint=indicator['source_hint'],
                    preferred_source=preferred_source
                )
            else:
                pending_tushare_missing.append({
                    "key": indicator['key'],
                    "name": indicator['name'],
                    "reason": missing_reason,
                    "search_query": indicator['search_query'],
                    "source_hint": indicator['source_hint'],
                    "preferred_source": preferred_source
                })

        macro_payload = await self._fetch_macro_from_tushare()
        for key, payload in macro_payload.items():
            entry = macro_dict.get(key)
            if not entry or payload.get("current_value") is None:
                continue
            entry.indicator_name = payload.get("indicator_name", entry.indicator_name)
            entry.current_value = payload.get("current_value")
            entry.previous_value = payload.get("previous_value")
            entry.change_rate = payload.get("change_rate")
            entry.unit = payload.get("unit", entry.unit)
            entry.date = payload.get("date", entry.date)
            entry.source = payload.get("source", entry.source)
            entry.is_estimated = False

        for item in pending_tushare_missing:
            entry = macro_dict.get(item["key"])
            if not entry or entry.current_value is None:
                self._record_missing(
                    'macro_indicators',
                    item['key'],
                    item['name'],
                    item['reason'],
                    search_query=item['search_query'],
                    source_hint=item['source_hint'],
                    preferred_source=item['preferred_source']
                )

        return macro_dict

    async def collect_monetary_policy(self) -> Dict[str, MonetaryPolicyData]:
        """
        收集货币政策数据 - Pring第二层(货币周期)必需数据

        数据项: 存准率、DR007、7天逆回购、MLF、TSF、M0/M1/M2
        数据来源: 政策利率优先MCP WebSearch，DR007/货币供应/TSF优先TuShare
        """
        print("[7/8] 收集货币政策数据...")
        print("  [INFO] 货币政策用于Pring第二层货币周期分析")
        print("  [INFO] 政策利率走MCP WebSearch，DR007与货币供应数据优先TuShare cn_m/sf_month")

        tushare_payload = await self._fetch_monetary_policy_from_tushare()
        monetary_dict: Dict[str, MonetaryPolicyData] = {}
        pending_tushare_missing: List[Dict[str, Any]] = []

        for policy in self.monetary_policy_config:
            print(f"  获取 {policy['name']}...")
            print(f"    [INFO] 数据源指引: {policy.get('search_query')} ({policy.get('preferred_source', 'websearch')})")
            preferred_source = policy.get('preferred_source', 'websearch')
            placeholder_source = (
                f'待MCP WebSearch获取({policy["source_hint"]})'
                if preferred_source == 'websearch'
                else f'待TuShare获取({policy["source_hint"]})'
            )

            monetary_dict[policy['key']] = MonetaryPolicyData(
                policy_name=policy['name'],
                current_value=None,
                change_from_120d=None,
                unit=policy['unit'],
                date=self.end_date,
                source=placeholder_source,
                is_estimated=True
            )
            if preferred_source == 'websearch':
                self._record_missing(
                    'monetary_policy',
                    policy['key'],
                    policy['name'],
                    'TuShare/本地无数据，需MCP WebSearch',
                    search_query=policy.get('search_query'),
                    source_hint=policy.get('source_hint'),
                    preferred_source=preferred_source
                )
            else:
                pending_tushare_missing.append({
                    "key": policy['key'],
                    "name": policy['name'],
                    "reason": 'TuShare暂未返回数据，需后续补录',
                    "search_query": policy.get('search_query'),
                    "source_hint": policy.get('source_hint'),
                    "preferred_source": preferred_source
                })

        if tushare_payload:
            for key, payload in tushare_payload.items():
                entry = monetary_dict.get(key)
                if not entry or payload.get("current_value") is None:
                    continue
                entry.policy_name = payload.get("policy_name", entry.policy_name)
                entry.current_value = payload.get("current_value")
                entry.change_from_120d = payload.get("change_from_120d")
                entry.unit = payload.get("unit", entry.unit)
                entry.date = payload.get("date", entry.date)
                entry.source = payload.get("source", entry.source)
                entry.note = payload.get("note", entry.note)
                entry.is_estimated = False

        for item in pending_tushare_missing:
            entry = monetary_dict.get(item["key"])
            if not entry or entry.current_value is None:
                self._record_missing(
                    'monetary_policy',
                    item['key'],
                    item['name'],
                    item['reason'],
                    search_query=item['search_query'],
                    source_hint=item['source_hint'],
                    preferred_source=item['preferred_source']
                )

        return monetary_dict

    # ========== 辅助方法 ==========

    def _prepare_price_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """准备价格数据,统一格式"""
        try:
            data = df.copy()

            # 统一日期列
            date_col = None
            for col in data.columns:
                if any(x in str(col).lower() for x in ['date', '日期', 'trade_date']):
                    date_col = col
                    break

            if date_col:
                data['date'] = pd.to_datetime(data[date_col], errors='coerce')
                data = data.dropna(subset=['date']).sort_values('date')

            # 统一close列
            close_col = None
            for col in data.columns:
                if any(x in str(col).lower() for x in ['close', '收盘', 'price']):
                    close_col = col
                    break

            if not close_col:
                # 尝试使用第一个数值列
                numeric_cols = data.select_dtypes(include=[np.number]).columns
                if len(numeric_cols) > 0:
                    close_col = numeric_cols[0]

            if not close_col:
                print("    [ERROR] 未找到价格列")
                return None

            data['close'] = pd.to_numeric(data[close_col], errors='coerce')
            data = data.dropna(subset=['close'])

            if len(data) == 0:
                print("    [ERROR] 数据为空")
                return None

            return data

        except Exception as e:
            print(f"    [ERROR] 数据准备失败: {e}")
            return None

    def _calculate_change(self, df: pd.DataFrame, days: int) -> float:
        """计算指定天数的涨跌幅"""
        try:
            if len(df) < days:
                return 0.0
            latest = df.iloc[-1]['close']
            previous = df.iloc[-days]['close']
            return round(((latest / previous) - 1) * 100, 1)
        except:
            return 0.0

    def _calculate_slope(self, series: pd.Series) -> float:
        """计算斜率"""
        try:
            series = series.dropna()
            if len(series) < 2:
                return 0.0
            x = np.arange(len(series))
            y = series.values
            slope = np.polyfit(x, y, 1)[0]
            return round(slope, 4)
        except:
            return 0.0

    def _calculate_trend_score(self, data: pd.DataFrame, latest: pd.Series) -> int:
        """计算趋势评分 (-2 ~ +2)"""
        score = 0

        # 1. 收益趋势
        if len(data) > 0:
            total_return = ((latest['close'] / data.iloc[0]['close']) - 1) * 100
            if total_return >= 5.0:
                score += 1
            elif total_return <= -5.0:
                score -= 1

        # 2. 均线位置
        if not pd.isna(latest.get('ma50')):
            if latest['close'] > latest['ma50']:
                score += 1
            else:
                score -= 1

        # 3. 中期趋势
        if not pd.isna(latest.get('ma50')) and not pd.isna(latest.get('ma200')):
            if latest['ma50'] > latest['ma200']:
                score += 1
            else:
                score -= 1

        # 4. 短期动量
        if not pd.isna(latest.get('ma20')) and len(data) >= 20:
            ma20_slope = self._calculate_slope(data['ma20'].tail(10))
            if ma20_slope > 0:
                score += 1
            elif ma20_slope < 0:
                score -= 1

        return max(-2, min(2, score))

    def _get_trend_label(self, score: int) -> str:
        """获取趋势标签"""
        if score >= 1:
            return "牛"
        elif score <= -1:
            return "熊"
        else:
            return "中性"

    async def _fetch_monetary_policy_from_tushare(self) -> Dict[str, Dict[str, Any]]:
        """尝试通过TuShare获取DR007/M1/M2/TSF数据"""
        results: Dict[str, Dict[str, Any]] = {}

        dr007_payload = await self._fetch_dr007_from_tushare()
        if dr007_payload:
            results["dr007"] = dr007_payload

        money_supply = await self._fetch_money_supply_from_tushare()
        for key in ("m0", "m1", "m2"):
            payload = money_supply.get(key)
            if payload:
                results[key] = payload

        tsf_payload = await self._fetch_tsf_from_tushare()
        if tsf_payload:
            results["tsf"] = tsf_payload

        return results

    async def _fetch_macro_from_tushare(self) -> Dict[str, Dict[str, Any]]:
        results: Dict[str, Dict[str, Any]] = {}
        ppi_payload = await self._fetch_ppi_from_tushare()
        if ppi_payload:
            results["ppi"] = ppi_payload
        cpi_payload = await self._fetch_cpi_from_tushare()
        if cpi_payload:
            results["cpi"] = cpi_payload
        gdp_payload = await self._fetch_gdp_from_tushare()
        if gdp_payload:
            results["gdp"] = gdp_payload
        pmi_payload = await self._fetch_pmi_components_from_tushare()
        if pmi_payload:
            results.update(pmi_payload)
        return results

    async def _fetch_monthly_indicator_series(
        self,
        *,
        method_name: str,
        indicator_name: str,
        value_candidates: List[str],
        unit: str,
        source_label: str,
        fallback_months: int = 1
    ) -> Optional[Dict[str, Any]]:
        """通用的TuShare月度指标获取逻辑，支持自动回退到上一个统计月"""
        end_dt = datetime.strptime(self.end_date, "%Y-%m-%d")
        start_month = (end_dt - pd.DateOffset(months=18)).strftime("%Y%m")
        attempt_months = [end_dt.strftime("%Y%m")]
        fallback_dt = end_dt - pd.DateOffset(months=fallback_months)
        fallback_month = fallback_dt.strftime("%Y%m")
        if fallback_month not in attempt_months:
            attempt_months.append(fallback_month)

        fetch_method = getattr(self.manager, method_name)

        for idx, end_month in enumerate(attempt_months):
            response = await fetch_method(start_month, end_month)
            payload = self._parse_monthly_indicator_dataframe(
                getattr(response, "data", None),
                indicator_name=indicator_name,
                value_candidates=value_candidates,
                unit=unit,
                source_label=source_label
            )
            if payload:
                return payload
            if idx == 0:
                print(f"    [WARN] {indicator_name} TuShare返回为空，尝试回退至上一统计月 ({fallback_month})")

        return None

    def _parse_monthly_indicator_dataframe(
        self,
        df: Optional[pd.DataFrame],
        *,
        indicator_name: str,
        value_candidates: List[str],
        unit: str,
        source_label: str
    ) -> Optional[Dict[str, Any]]:
        if df is None or isinstance(df, dict):
            return None
        try:
            frame = df.copy()
            frame.columns = [str(col).lower() for col in frame.columns]
            value_candidates = [col.lower() for col in value_candidates]
            date_col = "month" if "month" in frame.columns else None
            if not date_col:
                return None
            frame[date_col] = pd.to_datetime(frame[date_col].astype(str), format="%Y%m", errors="coerce")
            frame = frame.dropna(subset=[date_col]).sort_values(date_col)
            if frame.empty:
                return None
            value_col = next((col for col in value_candidates if col in frame.columns), None)
            if not value_col:
                return None
            parsed = pd.DataFrame({
                "month": frame[date_col],
                "value": pd.to_numeric(frame[value_col], errors="coerce")
            }).dropna(subset=["value"])
            if parsed.empty:
                return None
            latest = parsed.iloc[-1]
            previous = parsed.iloc[-2] if len(parsed) >= 2 else None
            change_rate = None
            if previous is not None:
                change_rate = float(latest["value"]) - float(previous["value"])
            return {
                "indicator_name": indicator_name,
                "current_value": float(latest["value"]),
                "previous_value": float(previous["value"]) if previous is not None else None,
                "change_rate": change_rate,
                "unit": unit,
                "date": latest["month"].strftime("%Y-%m"),
                "source": source_label,
                "is_estimated": False
            }
        except Exception:
            return None

    async def _fetch_ppi_from_tushare(self) -> Optional[Dict[str, Any]]:
        return await self._fetch_monthly_indicator_series(
            method_name="get_ppi_data",
            indicator_name="PPI",
            value_candidates=["ppi_yoy", "ppi"],
            unit="%",
            source_label="TuShare cn_ppi"
        )

    async def _fetch_cpi_from_tushare(self) -> Optional[Dict[str, Any]]:
        return await self._fetch_monthly_indicator_series(
            method_name="get_cpi_data",
            indicator_name="CPI",
            value_candidates=["cpi_yoy", "nt_yoy", "cpi", "nt_val"],
            unit="%",
            source_label="TuShare cn_cpi"
        )

    async def _fetch_dr007_from_tushare(self) -> Optional[Dict[str, Any]]:
        end_dt = datetime.strptime(self.end_date, "%Y-%m-%d")
        # 拉长至>120天窗口，确保baseline存在
        start_dt = end_dt - timedelta(days=260)
        response = await self.manager.get_repo_rate(
            start_dt.strftime("%Y-%m-%d"),
            self.end_date
        )
        df = getattr(response, "data", None)
        if df is None or isinstance(df, dict):
            return None
        try:
            df = df.copy()
            df.columns = [str(col).lower() for col in df.columns]
            date_col = "date" if "date" in df.columns else "trade_date"
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce", format="%Y%m%d")
            df = df.dropna(subset=[date_col])
            maturity_col = "repo_maturity" if "repo_maturity" in df.columns else None
            if maturity_col:
                df = df[df[maturity_col].str.contains("007", case=False, na=False)]
            value_col = "weight" if "weight" in df.columns else "repo_rate"
            df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
            df = df.dropna(subset=[value_col])
            if df.empty:
                return None
            df = df.sort_values(date_col)
            latest = df.iloc[-1]
            target_date = latest[date_col] - pd.Timedelta(days=120)
            baseline = df[df[date_col] <= target_date]
            if baseline.empty:
                baseline = df[df[date_col] < latest[date_col]]
            base_row = baseline.iloc[-1] if not baseline.empty else None
            change = None
            if base_row is not None:
                change = float(latest[value_col]) - float(base_row[value_col])
            return {
                "policy_name": "DR007",
                "current_value": float(latest[value_col]),
                "change_from_120d": change,
                "unit": "%",
                "date": latest[date_col].strftime("%Y-%m-%d"),
                "source": "TuShare repo_daily",
                "note": "TuShare repo_daily 加权利率",
                "is_estimated": False
            }
        except Exception:
            return None

    async def _fetch_money_supply_from_tushare(self) -> Dict[str, Optional[Dict[str, Any]]]:
        payloads: Dict[str, Optional[Dict[str, Any]]] = {"m0": None, "m1": None, "m2": None}
        end_dt = datetime.strptime(self.end_date, "%Y-%m-%d")
        start_dt = (end_dt - pd.DateOffset(months=18)).strftime("%Y%m")
        end_month = end_dt.strftime("%Y%m")
        response = await self.manager.get_money_supply(start_dt, end_month)
        df = getattr(response, "data", None)
        if df is None or isinstance(df, dict):
            return payloads
        try:
            df = df.copy()
            df.columns = [str(col).lower() for col in df.columns]
            if "month" not in df.columns:
                return payloads
            df["month"] = pd.to_datetime(df["month"].astype(str), format="%Y%m", errors="coerce")
            df = df.dropna(subset=["month"]).sort_values("month")
            if df.empty:
                return payloads

            latest = df.iloc[-1]
            base_date = latest["month"] - pd.DateOffset(months=4)
            base_row = df[df["month"] <= base_date].tail(1)

            def _build_payload(label: str, col_name: str) -> Optional[Dict[str, Any]]:
                if col_name not in df.columns:
                    return None
                df[col_name] = pd.to_numeric(df[col_name], errors="coerce")
                target = float(latest[col_name])
                change = None
                if not base_row.empty:
                    change = target - float(base_row.iloc[-1][col_name])
                return {
                    "policy_name": f"{label.upper()}增速",
                    "current_value": target,
                    "change_from_120d": change,
                    "unit": "%",
                    "date": latest["month"].strftime("%Y-%m"),
                    "source": "TuShare cn_m",
                    "note": f"TuShare cn_m 数据（{label.upper()}同比增速）",
                    "is_estimated": False
                }

            payloads["m0"] = _build_payload("m0", "m0_yoy" if "m0_yoy" in df.columns else "m0")
            payloads["m1"] = _build_payload("m1", "m1_yoy" if "m1_yoy" in df.columns else "m1")
            payloads["m2"] = _build_payload("m2", "m2_yoy" if "m2_yoy" in df.columns else "m2")
            return payloads
        except Exception:
            return payloads

    async def _fetch_tsf_from_tushare(self) -> Optional[Dict[str, Any]]:
        end_dt = datetime.strptime(self.end_date, "%Y-%m-%d")
        start_month = (end_dt - pd.DateOffset(months=24)).strftime("%Y%m")
        end_month = end_dt.strftime("%Y%m")
        response = await self.manager.get_social_financing(start_month, end_month)
        df = getattr(response, "data", None)
        if df is None or isinstance(df, dict):
            return None
        try:
            df = df.copy()
            df.columns = [str(col).lower() for col in df.columns]
            if "month" not in df.columns:
                return None
            df["month"] = pd.to_datetime(df["month"].astype(str), format="%Y%m", errors="coerce")
            value_col = "stk_endval" if "stk_endval" in df.columns else None
            if not value_col:
                return None
            df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
            df = df.dropna(subset=["month", value_col]).sort_values("month")
            if df.empty:
                return None

            def _calc_yoy(target_date: pd.Timestamp) -> Optional[float]:
                prev_date = target_date - pd.DateOffset(months=12)
                prev_row = df[df["month"] == prev_date]
                if prev_row.empty:
                    prev_row = df[df["month"] < prev_date].tail(1)
                if prev_row.empty:
                    return None
                curr_val = float(df[df["month"] == target_date].iloc[-1][value_col])
                prev_val = float(prev_row.iloc[-1][value_col])
                if prev_val == 0:
                    return None
                return (curr_val - prev_val) / prev_val * 100

            latest_row = df.iloc[-1]
            latest_date = latest_row["month"]
            latest_yoy = _calc_yoy(latest_date)
            if latest_yoy is None:
                return None

            base_date = latest_date - pd.DateOffset(months=4)
            base_row = df[df["month"] <= base_date].tail(1)
            base_yoy = _calc_yoy(base_row.iloc[-1]["month"]) if not base_row.empty else None
            change = None
            if base_yoy is not None:
                change = latest_yoy - base_yoy

            return {
                "policy_name": "TSF社融增速",
                "current_value": round(latest_yoy, 2),
                "change_from_120d": round(change, 2) if change is not None else None,
                "unit": "%",
                "date": latest_date.strftime("%Y-%m"),
                "source": "TuShare sf_month",
                "note": "根据社融存量计算的同比增速",
                "is_estimated": False
            }
        except Exception:
            return None

    async def _fetch_gdp_from_tushare(self) -> Optional[Dict[str, Any]]:
        end_dt = datetime.strptime(self.end_date, "%Y-%m-%d")
        end_quarter = f"{end_dt.year}Q{((end_dt.month - 1) // 3) + 1}"
        start_dt = end_dt - pd.DateOffset(years=3)
        start_quarter = f"{start_dt.year}Q{((start_dt.month - 1) // 3) + 1}"
        response = await self.manager.get_gdp_data(start_quarter, end_quarter)
        df = getattr(response, "data", None)
        if df is None or isinstance(df, dict):
            return None
        try:
            df = df.copy()
            df.columns = [str(col).lower() for col in df.columns]
            if "quarter" not in df.columns:
                return None
            df["quarter"] = df["quarter"].astype(str)
            df = df.dropna(subset=["quarter"]).sort_values("quarter")
            if df.empty:
                return None
            value_col = "gdp_yoy" if "gdp_yoy" in df.columns else "gdp"
            if value_col not in df.columns:
                return None
            df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
            df = df.dropna(subset=[value_col])
            if df.empty:
                return None
            latest = df.iloc[-1]
            previous = df.iloc[-2] if len(df) >= 2 else None
            return {
                "indicator_name": "GDP",
                "current_value": float(latest[value_col]),
                "previous_value": float(previous[value_col]) if previous is not None else None,
                "change_rate": float(latest[value_col]),
                "unit": "%",
                "date": latest["quarter"],
                "source": "TuShare cn_gdp",
                "is_estimated": False
            }
        except Exception:
            return None

    async def _fetch_pmi_components_from_tushare(self) -> Dict[str, Dict[str, Any]]:
        results: Dict[str, Dict[str, Any]] = {}
        end_dt = datetime.strptime(self.end_date, "%Y-%m-%d")
        start_dt = end_dt - pd.DateOffset(months=18)
        response = await self.manager.get_pmi_data(start_dt.strftime("%Y%m"), end_dt.strftime("%Y%m"))
        df = getattr(response, "data", None)
        if df is None or isinstance(df, dict):
            return results
        try:
            df = df.copy()
            df.columns = [str(col).lower() for col in df.columns]
            if "month" not in df.columns:
                return results
            df["month"] = pd.to_datetime(df["month"].astype(str), format="%Y%m", errors="coerce")
            df = df.dropna(subset=["month"]).sort_values("month")
            if df.empty:
                return results

            def _find_column(pattern_groups: List[List[str]]) -> Optional[str]:
                for patterns in pattern_groups:
                    for col in df.columns:
                        lowered = str(col).lower()
                        if all(pattern in lowered for pattern in patterns):
                            return col
                return None

            def _resolve_column(key: str, pattern_groups: List[List[str]]) -> Optional[str]:
                aliases = [alias.lower() for alias in self.pmi_column_map.get(key, [])]
                for alias in aliases:
                    if alias in df.columns:
                        return alias
                return _find_column(pattern_groups)

            def _build_payload(key: str, label: str, col_name: Optional[str]) -> None:
                if not col_name or col_name not in df.columns:
                    return
                series = pd.to_numeric(df[col_name], errors="coerce")
                valid = pd.DataFrame({"month": df["month"], "value": series}).dropna(subset=["value"])
                if valid.empty:
                    return
                latest_row = valid.iloc[-1]
                prev_row = valid.iloc[-2] if len(valid) >= 2 else None
                prev_value = float(prev_row["value"]) if prev_row is not None else None
                change_rate = None
                if prev_row is not None:
                    change_rate = float(latest_row["value"]) - prev_value
                results[key] = {
                    "indicator_name": label,
                    "current_value": float(latest_row["value"]),
                    "previous_value": prev_value,
                    "change_rate": change_rate,
                    "unit": "点",
                    "date": latest_row["month"].strftime("%Y-%m"),
                    "source": f"TuShare cn_pmi({col_name})",
                    "is_estimated": False
                }

            pmi_col = _resolve_column("pmi", [['manufacturing'], ['manu'], ['pmi']])
            new_order_col = _resolve_column("pmi_new_orders", [['new', 'order'], ['neworder'], ['dingdan']])
            production_col = _resolve_column("pmi_production", [['production'], ['product'], ['shengchan']])

            _build_payload("pmi", "PMI", pmi_col)
            _build_payload("pmi_new_orders", "PMI新订单", new_order_col)
            _build_payload("pmi_production", "PMI生产", production_col)
            return results
        except Exception:
            return results

    async def _fetch_margin_flow_from_tushare(self) -> Optional[FundFlowData]:
        """使用TuShare融资融券余额推算资金流"""
        if not hasattr(self.manager, "get_margin_summary"):
            return None

        end_dt = datetime.strptime(self.end_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=200)
        response = await self.manager.get_margin_summary(
            start_dt.strftime("%Y-%m-%d"),
            self.end_date,
            'both'
        )
        df = getattr(response, "data", None)
        if df is None or isinstance(df, dict):
            return None
        try:
            frame = df.copy()
            frame.columns = [str(col).lower() for col in frame.columns]
            if "trade_date" not in frame.columns:
                return None
            frame["trade_date"] = pd.to_datetime(frame["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
            value_col = "rzrqye" if "rzrqye" in frame.columns else "rzye" if "rzye" in frame.columns else None
            if not value_col:
                return None
            frame[value_col] = pd.to_numeric(frame[value_col], errors="coerce")
            frame = frame.dropna(subset=["trade_date", value_col])
            if frame.empty:
                return None
            series = frame.groupby("trade_date")[value_col].sum().sort_index() / 1e8
            if series.empty:
                return None

            recent_delta = self._calc_flow_delta(series, window=5)
            total_delta = self._calc_flow_delta(series, window=120)
            if recent_delta is None and total_delta is None:
                return None

            latest_value = float(series.iloc[-1])
            return FundFlowData(
                type="margin",
                recent_5d=recent_delta,
                total_120d=total_delta,
                trend=self._infer_trend(recent_delta),
                source="TuShare margin(SSE+SZSE)",
                note=f"依据融资融券余额推算；最新余额≈{latest_value:.1f}亿元"
            )
        except Exception:
            return None

    async def _fetch_etf_flow_proxy(self) -> Optional[FundFlowData]:
        """基于daily_info成交额估算ETF热度（权限不足时返回None）"""
        if not hasattr(self.manager, "get_daily_market_info"):
            return None
        end_dt = datetime.strptime(self.end_date, "%Y-%m-%d")

        latest = await self._get_daily_turnover_amount(end_dt, window_days=3)
        baseline_5d = await self._get_daily_turnover_amount(end_dt - timedelta(days=7), window_days=5)
        baseline_120d = await self._get_daily_turnover_amount(end_dt - timedelta(days=130), window_days=5)

        if latest is None:
            return None

        recent_delta = None
        if baseline_5d is not None:
            recent_delta = round(latest - baseline_5d, 2)
        total_delta = None
        if baseline_120d is not None:
            total_delta = round(latest - baseline_120d, 2)

        if recent_delta is None and total_delta is None:
            return None

        note_parts = [
            "日成交额合计估算ETF申赎热度 (亿元)",
            f"最新:{latest:.2f}",
        ]
        if baseline_5d is not None:
            note_parts.append(f"5日前:{baseline_5d:.2f}")
        if baseline_120d is not None:
            note_parts.append(f"120日前:{baseline_120d:.2f}")

        return FundFlowData(
            type="etf",
            recent_5d=recent_delta,
            total_120d=total_delta,
            trend=self._infer_trend(recent_delta),
            source="TuShare daily_info估算",
            note="; ".join(note_parts)
        )

    def _calc_flow_delta(self, series: pd.Series, window: int) -> Optional[float]:
        """计算指定窗口的余额变化（亿元）"""
        if series.empty:
            return None
        if len(series) <= 1:
            return None
        base_index = len(series) - window - 1
        if base_index < 0:
            base_index = 0
        latest = float(series.iloc[-1])
        base_value = float(series.iloc[base_index])
        delta = latest - base_value
        return round(delta, 2)

    def _infer_trend(self, value: Optional[float]) -> str:
        if value is None:
            return "未知"
        if value > 0:
            return "流入"
        if value < 0:
            return "流出"
        return "震荡"

    async def _get_daily_turnover_amount(self, base_date: datetime, *, window_days: int = 3) -> Optional[float]:
        """尝试在指定日期附近获取daily_info总成交额（亿元）"""
        if not hasattr(self.manager, "get_daily_market_info"):
            return None
        exchanges = ['SSE', 'SZSE']
        for offset in range(window_days):
            target = base_date - timedelta(days=offset)
            trade_str = target.strftime("%Y-%m-%d")
            totals = []
            for exch in exchanges:
                response = await self.manager.get_daily_market_info(trade_date=trade_str, exchange=exch)
                df = getattr(response, "data", None)
                if df is None or isinstance(df, dict):
                    continue
                if getattr(df, "empty", True):
                    continue
                try:
                    frame = df.copy()
                    frame.columns = [str(col).lower() for col in frame.columns]
                    if "amount" not in frame.columns:
                        continue
                    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
                    valid = frame.dropna(subset=["amount"])
                    if valid.empty:
                        continue
                    totals.append(valid["amount"].sum())
                except Exception:
                    continue
            if not totals:
                continue
            total_amount = sum(totals) / 1e8
            if np.isnan(total_amount):
                continue
            return float(total_amount)
        print(f"    [WARN] TuShare daily_info在{base_date.strftime('%Y-%m-%d')}±{window_days}日内无成交统计，无法估算ETF资金流")
        return None

    def _calculate_completeness(
        self,
        stock_indices: List,
        commodities: List,
        forex: List,
        bonds: List,
        fund_flow: Dict
    ) -> float:
        """计算数据完整度"""
        total = 0
        complete = 0

        # 股票指数 (5个)
        total += 5
        complete += len(stock_indices)

        # 商品 (6个)
        total += 6
        complete += sum(1 for c in commodities if c.source != "MCP WebFetch待获取")

        # 汇率 (3个)
        total += 3
        complete += len(forex)

        # 债券 (3个)
        total += 3
        complete += sum(1 for b in bonds if not b.is_estimated)

        # 资金流向 (4个)
        total += 4
        complete += sum(1 for f in fund_flow.values() if f.source != "MCP WebSearch待获取")

        return complete / total if total > 0 else 0.0

    def _record_missing(
        self,
        category: str,
        key: str,
        name: str,
        reason: str,
        *,
        search_query: Optional[str] = None,
        source_hint: Optional[str] = "tavily",
        preferred_source: str = "tushare",
        attempted_tushare: bool = False,
    ) -> None:
        """记录缺失数据,供Stage 2回填"""
        self.missing_items[category].append(
            {
                "key": key,
                "name": name,
                "reason": reason,
                "preferred_source": preferred_source,
                "search_query": search_query,
                "source_hint": source_hint,
                "attempted_tushare": attempted_tushare,
            }
        )


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Stage 1: 市场数据收集器')
    parser.add_argument('--date', required=True, help='结束日期 (YYYY-MM-DD 或 YYYYMMDD)')
    parser.add_argument('--output', help='输出JSON文件路径 (默认: data/YYYYMMDD_market_data.json)')

    args = parser.parse_args()

    def _normalize_date_str(date_text: str) -> str:
        """
        接受 YYYY-MM-DD / YYYYMMDD，标准化为 YYYY-MM-DD。
        若格式不合法则抛出 ValueError。
        """
        candidates = ["%Y-%m-%d", "%Y%m%d"]
        for fmt in candidates:
            try:
                dt = datetime.strptime(date_text.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        raise ValueError(f"无法解析日期 {date_text}，请使用 YYYY-MM-DD 或 YYYYMMDD")

    def _resolve_last_trading_day(target_date: str) -> str:
        """
        将传入日期规范到最近的交易日（含当日）。用于避开周末/法定节假日导致的空数据。
        """
        try:
            import tushare as ts

            pro = ts.pro_api()
            end_dt = datetime.strptime(target_date, "%Y-%m-%d")
            start_dt = end_dt - timedelta(days=15)  # 向前最多回溯两周

            cal = pro.trade_cal(
                exchange='',
                start_date=start_dt.strftime("%Y%m%d"),
                end_date=end_dt.strftime("%Y%m%d"),
            )
            open_dates = [d for d in cal[cal.is_open == 1].cal_date]
            if not open_dates:
                return target_date  # 获取失败时保持原值，避免阻断
            last_open = open_dates[-1]
            return datetime.strptime(last_open, "%Y%m%d").strftime("%Y-%m-%d")
        except Exception:
            # 若 TuShare 不可用或无权限，保持用户输入日期
            return target_date

    # 构建输出路径
    if args.output:
        output_path = Path(args.output)
    else:
        output_dir = Path('data')
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / 'market_data.json'

    # 统一日期格式，容忍 YYYYMMDD
    try:
        normalized_date = _normalize_date_str(args.date)
    except ValueError as ve:
        print(f"[ERROR] {ve}")
        return

    # 若传入日期为休市日，则回退到最近交易日
    trading_date = _resolve_last_trading_day(normalized_date)
    if trading_date != normalized_date:
        print(f"[INFO] 目标日期 {normalized_date} 为休市日，自动回退至最近交易日 {trading_date}")
    else:
        print(f"[INFO] 使用交易日: {trading_date}")

    # 创建收集器
    collector = MarketDataCollector(
        end_date=trading_date
    )

    # 收集数据
    contract = await collector.collect_all_data()

    # 保存JSON
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        backup = output_path.with_suffix(output_path.suffix + ".bak")
        shutil.copy2(output_path, backup)
    with open(output_path.with_suffix(output_path.suffix + ".tmp"), 'w', encoding='utf-8') as f:
        json.dump(contract.model_dump(), f, ensure_ascii=False, indent=2)
    Path(output_path.with_suffix(output_path.suffix + ".tmp")).replace(output_path)

    print(f"[OK] 数据已保存到: {output_path}")
    print(f"   文件大小: {output_path.stat().st_size / 1024:.1f} KB")


if __name__ == '__main__':
    asyncio.run(main())
