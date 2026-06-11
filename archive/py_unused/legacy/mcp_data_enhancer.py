#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Archived Stage 2a MCP Data Enhancer - Essential Data Only (V3.3混合架构)
当前补数入口为 Stage2 unified enhancer + Stage2.5 manual/WebSearch JSON 注入。
本脚本仅保留历史比对用途，默认禁止直接运行。

职责: 在Pring分析前,填充关键占位符数据(仅Pring分析必需项)
输入: market_data.json (from Stage 1)
输出: market_data_enhanced.json + enhancement_log.json

关键数据填充策略:
- 债券: CN10Y (影响货币周期判断) ✅ 必填
- 商品: 黄金/原油/铜等趋势 (验证库存周期) ✅ 必填
- 资金流向: 跳过 (不影响Pring分析) ❌ 跳过
- 财经要闻: 跳过 (Stage 3/4后期补充) ❌ 跳过
"""

import asyncio
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import re
import sys
import io

# 修复Windows控制台UTF-8输出问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 导入数据契约
from datasource.models.market_data_contract import (
    MarketDataContract,
    CommodityData,
    BondYieldData,
    FundFlowData,
    FinancialNewsItem,
    MacroIndicatorData,
    MonetaryPolicyData
)
from datasource.models.pring_result_contract import PringResultContract
from datasource.mcp_adapter import MCPToolAdapter
from datasource.utils.mcp_tools import MCPDataFetcher


class MCPDataEnhancer:
    """MCP数据增强器

    职责:
    - 扫描并识别占位符数据
    - 调用MCP工具(WebSearch/WebFetch)获取缺失数据
    - 验证并更新MarketDataContract
    - 重新生成完整报告

    不负责:
    - 数据收集 (Stage 1职责)
    - Pring分析 (Stage 2职责)
    - 模板渲染 (Stage 3职责)
    """

    def __init__(
        self,
        market_data_path: str,
        pring_result_path: Optional[str] = None,
        report_draft_path: Optional[str] = None,
        enable_mcp: bool = True,
        websearch_results_path: Optional[str] = None
    ):
        """初始化MCP增强器

        Args:
            market_data_path: Stage 1输出的JSON文件
            pring_result_path: Stage 2输出的JSON文件（Stage 2a模式下可选）
            report_draft_path: Stage 3输出的Markdown草稿（可选）
            enable_mcp: 是否启用MCP工具（默认True）
        """
        self.market_data_path = Path(market_data_path)
        self.pring_result_path = Path(pring_result_path) if pring_result_path else None
        self.report_draft_path = Path(report_draft_path) if report_draft_path else None
        self.enable_mcp = enable_mcp
        self.websearch_results_path = Path(websearch_results_path) if websearch_results_path else None
        self.manual_results = self._load_manual_results()

        # 加载数据
        self.market_data = self._load_market_data()
        self.pring_result = self._load_pring_result()

        # 创建MCP适配器
        self.mcp_adapter = MCPToolAdapter(enable_validation=True)
        self.mcp_fetcher = MCPDataFetcher() if enable_mcp else None

        # 可信数据源配置 (WebSearch降级使用)
        self.trusted_sources = {
            'bonds': {
                'CN10Y': {
                    'name': '中国10年期国债',
                    'sources': ['中国债券信息网 yield.chinabond.com.cn', 'cn.investing.com 中国10年期国债', 'eastmoney.com 中国10年国债收益率'],
                    'keywords': '中国10年期国债收益率 最新 债券'
                },
                'CN10Y_CDB': {
                    'name': '中国10年期国开债',
                    'sources': ['中国债券信息网 yield.chinabond.com.cn', 'cn.investing.com 中国国开债', 'eastmoney.com 国开债收益率'],
                    'keywords': '中国10年期国开债收益率 最新 政策性金融债'
                }
            },
            'commodities': {
                'GC=F': {
                    'name': 'COMEX黄金',
                    'sources': ['cn.investing.com COMEX黄金期货', 'finance.sina.com.cn 黄金期货', 'eastmoney.com COMEX黄金'],
                    'keywords': 'COMEX黄金期货 最新价格 实时行情'
                },
                'CL=F': {
                    'name': 'WTI原油',
                    'sources': ['cn.investing.com WTI原油期货', 'finance.sina.com.cn WTI原油', 'eastmoney.com WTI原油'],
                    'keywords': 'WTI原油期货 最新价格 实时行情'
                },
                'BZ=F': {
                    'name': 'Brent原油',
                    'sources': ['cn.investing.com Brent原油期货', 'finance.sina.com.cn 布伦特原油', 'eastmoney.com Brent原油'],
                    'keywords': 'Brent原油期货 布伦特原油 最新价格'
                },
                'HG=F': {
                    'name': 'COMEX铜',
                    'sources': ['cn.investing.com COMEX铜期货', 'finance.sina.com.cn 铜期货', 'eastmoney.com COMEX铜'],
                    'keywords': 'COMEX铜期货 最新价格 实时行情'
                },
                'BCOM': {
                    'name': 'BCOM指数',
                    'sources': ['bloomberg.com BCOM指数', 'cn.investing.com 彭博商品指数', 'finance.yahoo.com Bloomberg Commodity Index'],
                    'keywords': 'Bloomberg Commodity Index BCOM 彭博商品指数'
                }
            }
        }

        # 增强日志
        self.enhancement_log = {
            'start_time': datetime.now().isoformat(),
            'mcp_enabled': enable_mcp,
            'enhancements': [],
            'errors': [],
            'websearch_fallbacks': [],  # 新增：WebSearch降级记录
            'mcp_prompts_file': None  # 方案C: AI提示词文件路径
        }
        if self.manual_results:
            print(f"[INFO] 已加载手动WebSearch结果: {self.websearch_results_path}")
        elif self.websearch_results_path:
            print(f"[WARN] 指定的WebSearch结果文件不存在: {self.websearch_results_path}")

    def _load_manual_results(self) -> Optional[Dict[str, Any]]:
        if not self.websearch_results_path:
            return None
        if not self.websearch_results_path.exists():
            return None
        try:
            with open(self.websearch_results_path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            return data or None
        except Exception as exc:
            print(f"[WARN] 无法读取WebSearch结果文件: {exc}")
            return None

    def _load_market_data(self) -> MarketDataContract:
        """加载市场数据"""
        with open(self.market_data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return MarketDataContract(**data)

    def _load_pring_result(self) -> Optional[PringResultContract]:
        """加载Pring分析结果（可选）

        Note: Stage 2a在Pring分析前执行，此时pring_result可能不存在
        """
        if not self.pring_result_path or not self.pring_result_path.exists():
            return None

        try:
            with open(self.pring_result_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return PringResultContract(**data)
        except Exception as e:
            print(f"[WARN] 无法加载Pring结果: {e}")
            return None

    async def enhance(self, mode: str = "essential") -> Dict[str, Any]:
        """执行数据增强"""
        if mode not in {"essential", "full", "supplement"}:
            raise ValueError(f"Unsupported mode: {mode}")

        label = {"essential": "Stage 2a (Essential)", "full": "Stage 2a (Full)", "supplement": "Stage 4 (Supplement)"}[mode]

        print(f"\n{'='*70}")
        print(f"MCP数据增强器 - {label}")
        print(f"{'='*70}")
        print(f"MCP启用: {self.enable_mcp}")
        print(f"数据日期: {self.market_data.metadata['date']}")
        print(f"填充模式: {mode}")
        print(f"{'='*70}\n")

        print("[1/5] 扫描占位符数据...")
        placeholders = self._scan_placeholders()
        self._print_placeholder_summary(placeholders, mode)

        if not self.enable_mcp:
            print("\n[WARN] MCP未启用，本次跳过增强")
            return self._build_result(enhanced=False)

        print("\n[2/5] 生成MCP数据获取提示词...")
        prompts_file = self._generate_mcp_prompts(placeholders, mode)
        print(f"  [OK] 提示词文件: {prompts_file}")
        print(f"  [INFO] 请AI执行提示词中的MCP任务")

        run_core = mode in {"essential", "full"}
        run_optional = mode in {"full", "supplement"}
        step_idx = 3

        if run_core:
            print(f"\n[{step_idx}/5] 填充债券数据...")
            await self._fill_bonds(placeholders['bonds'])
            step_idx += 1

            print(f"\n[{step_idx}/5] 填充商品数据...")
            await self._fill_commodities(placeholders['commodities'])
            step_idx += 1
        else:
            print(f"\n[{step_idx}/5] 跳过债券与商品 (Supplement模式)")
            step_idx += 1

        if run_optional:
            print(f"\n[{step_idx}/5] 填充资金流向和财经要闻...")
            await self._fill_fund_flow(placeholders['fund_flow'])
            await self._fill_financial_news()
        else:
            print(f"\n[{step_idx}/5] 跳过资金流向和财经要闻(Stage 2a模式)")
            print("  [INFO] 资金流向和财经要闻将在Stage 4补充")

        if self.manual_results:
            print(f"\n[{step_idx}/5] 应用手动WebSearch结果...")
            applied_count = self._apply_manual_results()
            print(f"  [OK] 已应用 {applied_count} 条手动结果")
        else:
            # 检查Pring关键数据是否缺失
            if run_core and (placeholders['macro_indicators'] or placeholders['monetary_policy']):
                print(f"\n{'='*70}")
                print("⚠️  [警告] 检测到Pring分析必需数据缺失")
                print(f"{'='*70}")
                print(f"  缺失项: 宏观指标({len(placeholders['macro_indicators'])}项) + 货币政策({len(placeholders['monetary_policy'])}项)")
                print(f"  影响: Pring三层框架分析将失败（置信度=0%）")
                print(f"\n  解决方案:")
                print(f"  1. 使用WebSearch工具手动收集10个指标数据")
                print(f"  2. 创建JSON文件（格式参考: data/websearch_results_example.json）")
                print(f"  3. 重新运行并传入: --websearch-results <your_file.json>")
                print(f"\n  提示词文件: {prompts_file}")
                print(f"  包含WebSearch查询: {len(placeholders['macro_indicators']) + len(placeholders['monetary_policy'])} 项")
                print(f"{'='*70}\n")
                self.enhancement_log['pring_data_missing'] = True
                self.enhancement_log['missing_macro_count'] = len(placeholders['macro_indicators'])
                self.enhancement_log['missing_monetary_count'] = len(placeholders['monetary_policy'])
            else:
                print("\n[INFO] 未提供手动WebSearch结果文件，可使用 --websearch-results 传入")

        self.enhancement_log['end_time'] = datetime.now().isoformat()
        self.enhancement_log['fill_mode'] = mode
        self._print_summary()
        self._refresh_metadata_complete()

        return self._build_result(enhanced=True)

    def _scan_placeholders(self) -> Dict[str, List[str]]:
        """扫描占位符数据

        Returns:
            按类别组织的占位符列表
        """
        placeholders = {
            'commodities': [],
            'bonds': [],
            'macro_indicators': [],
            'monetary_policy': [],
            'fund_flow': [],
            'financial_news': []
        }

        # 扫描商品
        for commodity in self.market_data.commodities:
            if (
                self._is_placeholder_source(commodity.source)
                or self._is_suspicious_numeric(commodity.current_price)
            ):
                placeholders['commodities'].append(commodity.symbol)

        # 扫描债券
        for bond in self.market_data.bonds:
            if (
                self._is_placeholder_source(bond.source)
                or bond.is_estimated
                or self._is_suspicious_numeric(bond.current_yield)
            ):
                placeholders['bonds'].append(bond.symbol)

        # 扫描宏观指标
        for key, indicator in self.market_data.macro_indicators.items():
            if indicator.is_estimated or indicator.current_value is None:
                placeholders['macro_indicators'].append(key)

        # 扫描货币政策
        for key, policy in self.market_data.monetary_policy.items():
            if policy.is_estimated or policy.current_value is None:
                placeholders['monetary_policy'].append(key)

        # 扫描资金流向
        for key, flow in self.market_data.fund_flow.items():
            if self._is_placeholder_source(flow.source) or flow.recent_5d == 'N/A':
                placeholders['fund_flow'].append(key)

        # 检查财经要闻
        if not self.market_data.financial_news or len(self.market_data.financial_news) == 0:
            placeholders['financial_news'].append('all')

        return placeholders

    def _is_placeholder_source(self, text: str) -> bool:
        """判断是否为占位符"""
        placeholder_keywords = ['待MCP获取', 'MCP WebFetch待获取', 'MCP WebSearch待获取', 'N/A']
        return any(keyword in text for keyword in placeholder_keywords)

    def _is_suspicious_numeric(self, value: Optional[float]) -> bool:
        if value is None:
            return True
        try:
            val = float(value)
        except (TypeError, ValueError):
            return True
        if abs(val) < 1e-9:
            return True
        return abs(val - 7.13) < 1e-3

    def _print_placeholder_summary(self, placeholders: Dict[str, List[str]], mode: str):
        """总结占位信息"""
        macro_count = len(placeholders['macro_indicators'])
        monetary_count = len(placeholders['monetary_policy'])

        if mode == "supplement":
            total = len(placeholders["fund_flow"]) + len(placeholders["financial_news"])
            print(f"\n发现 {total} 个补充占位符 (Stage 4模式):")
            print(f"  - 资金流向: {len(placeholders['fund_flow'])} 项")
            print(f"  - 财经要闻: {len(placeholders['financial_news'])} 项")
            if macro_count or monetary_count:
                print("  [INFO] 检测到宏观/货币占位符，但当前模式默认跳过")
        elif mode == "essential":
            essential_count = (
                len(placeholders["commodities"])
                + len(placeholders["bonds"])
                + macro_count
                + monetary_count
            )
            print(f"\n发现 {essential_count} 个关键占位符 (Stage 2a模式):")
            print(f"  ✅ 债券数据: {len(placeholders['bonds'])} 项(必填)")
            print(f"  ✅ 商品数据: {len(placeholders['commodities'])} 项(必填)")
            print(f"  ✅ 宏观指标: {macro_count} 项(Pring第一层必填)")
            print(f"  ✅ 货币政策: {monetary_count} 项(Pring第二层必填)")
            print(f"  ⏭️  资金流向: {len(placeholders['fund_flow'])} 项(跳过,Stage 4补充)")
            print(f"  ⏭️  财经要闻: {len(placeholders['financial_news'])} 项(跳过,Stage 4补充)")
        else:
            total = sum(len(v) for v in placeholders.values())
            print(f"\n发现 {total} 个占位数据项 (Full模式):")
            print(f"  - 债券数据: {len(placeholders['bonds'])} 项")
            print(f"  - 商品数据: {len(placeholders['commodities'])} 项")
            print(f"  - 宏观指标: {macro_count} 项")
            print(f"  - 货币政策: {monetary_count} 项")
            print(f"  - 资金流向: {len(placeholders['fund_flow'])} 项")
            print(f"  - 财经要闻: {len(placeholders['financial_news'])} 项")

    def _generate_mcp_prompts(self, placeholders: Dict[str, List[str]], mode: str) -> str:
        """生成MCP提示词 (供Claude Code执行)"""
        core_enabled = mode in {"essential", "full"}
        optional_enabled = mode in {"full", "supplement"}

        all_prompts = []

        if core_enabled and placeholders['bonds']:
            all_prompts.extend(self.mcp_adapter.generate_bond_prompts(placeholders['bonds']))

        if core_enabled and placeholders['commodities']:
            all_prompts.extend(self.mcp_adapter.generate_commodity_prompts(placeholders['commodities']))

        if core_enabled and placeholders['macro_indicators']:
            macro_items = self._prepare_macro_prompt_items(placeholders['macro_indicators'])
            all_prompts.extend(self.mcp_adapter.generate_macro_prompts(macro_items))

        if core_enabled and placeholders['monetary_policy']:
            monetary_items = self._prepare_monetary_prompt_items(placeholders['monetary_policy'])
            all_prompts.extend(self.mcp_adapter.generate_monetary_prompts(monetary_items))

        if optional_enabled and placeholders['fund_flow']:
            flow_mapping = {
                'northbound': 'northbound',
                'southbound': 'southbound',
                'etf': 'etf',
                'margin': 'margin'
            }
            all_prompts.extend(self.mcp_adapter.generate_fund_flow_prompts(
                [flow_mapping.get(key, key) for key in placeholders['fund_flow']]
            ))

        if optional_enabled and placeholders['financial_news']:
            all_prompts.extend(self.mcp_adapter.generate_financial_news_prompts())

        prompts_text = self.mcp_adapter.format_prompts_for_ai(all_prompts)

        date_str = self.market_data.metadata['date']
        prompts_file = Path(f"logs/mcp_prompts_{date_str}.md")
        prompts_file.parent.mkdir(parents=True, exist_ok=True)

        with open(prompts_file, 'w', encoding='utf-8') as f:
            f.write(prompts_text)

        self.enhancement_log['mcp_prompts_file'] = str(prompts_file)
        self.enhancement_log['total_prompts'] = len(all_prompts)

        return str(prompts_file)

    def _prepare_macro_prompt_items(self, macro_keys: List[str]) -> List[Dict[str, Any]]:
        """根据Stage1缺失记录构建宏观指标提示词条目"""
        items: List[Dict[str, Any]] = []
        for key in macro_keys:
            indicator = self.market_data.macro_indicators.get(key)
            missing = self._get_missing_item_detail('macro_indicators', key) or {}
            name = indicator.indicator_name if indicator else key.upper()
            context = f"获取{name}用于Pring第一层库存周期分析"
            items.append({
                'key': key,
                'name': name,
                'query': missing.get('search_query') or f"{name} 最新数据",
                'context': context,
                'expected_fields': ['current_value', 'previous_value', 'change_rate', 'date', 'source'],
                'source_hint': missing.get('source_hint', 'stats.gov.cn')
            })
        return items

    def _prepare_monetary_prompt_items(self, policy_keys: List[str]) -> List[Dict[str, Any]]:
        """根据Stage1缺失记录构建货币政策提示词条目"""
        items: List[Dict[str, Any]] = []
        for key in policy_keys:
            policy = self.market_data.monetary_policy.get(key)
            missing = self._get_missing_item_detail('monetary_policy', key) or {}
            name = policy.policy_name if policy else key.upper()
            context = f"获取{name}用于Pring第二层货币周期分析"
            items.append({
                'key': key,
                'name': name,
                'query': missing.get('search_query') or f"{name} 最新数据",
                'context': context,
                'expected_fields': ['current_value', 'change_from_120d', 'date', 'source'],
                'source_hint': missing.get('source_hint', 'pbc.gov.cn')
            })
        return items

    def _get_missing_item_detail(self, category: str, key: str) -> Optional[Dict[str, Any]]:
        """从metadata.missing_items中取出记录"""
        metadata = self.market_data.metadata or {}
        missing_items = metadata.get('missing_items', {})
        for item in missing_items.get(category, []):
            if item.get('key') == key:
                return item
        return None

    def _apply_manual_results(self) -> int:
        """应用手动/WebSearch结果文件"""
        if not self.manual_results:
            return 0

        applied = 0
        self.enhancement_log['manual_results_file'] = str(self.websearch_results_path)

        if 'macro_indicators' in self.manual_results:
            for key, payload in self.manual_results['macro_indicators'].items():
                if self._apply_manual_macro_entry(key, payload):
                    applied += 1

        if 'monetary_policy' in self.manual_results:
            for key, payload in self.manual_results['monetary_policy'].items():
                if self._apply_manual_monetary_entry(key, payload):
                    applied += 1

        if 'commodities' in self.manual_results:
            for symbol, payload in self.manual_results['commodities'].items():
                if self._apply_manual_commodity_entry(symbol, payload):
                    applied += 1

        if 'bonds' in self.manual_results:
            for symbol, payload in self.manual_results['bonds'].items():
                if self._apply_manual_bond_entry(symbol, payload):
                    applied += 1

        if 'fund_flow' in self.manual_results:
            for key, payload in self.manual_results['fund_flow'].items():
                if self._apply_manual_fund_flow_entry(key, payload):
                    applied += 1

        if applied:
            print(f"  [OK] 已根据 {self.websearch_results_path} 写入 {applied} 条手动结果")
        else:
            print(f"  [INFO] 未在 {self.websearch_results_path} 中找到可匹配的手动结果")

        return applied

    def _apply_manual_macro_entry(self, key: str, payload: Dict[str, Any]) -> bool:
        if not payload:
            return False

        indicator = self.market_data.macro_indicators.get(key)
        if not indicator:
            indicator = MacroIndicatorData(
                indicator_name=payload.get('name', key.upper()),
                current_value=None,
                previous_value=None,
                change_rate=None,
                unit=payload.get('unit', '%'),
                date=payload.get('date', self.market_data.metadata.get('date')),
                source=payload.get('source', 'manual'),
                is_estimated=True
            )
            self.market_data.macro_indicators[key] = indicator

        indicator.current_value = payload.get('current_value', indicator.current_value)
        indicator.previous_value = payload.get('previous_value', indicator.previous_value)
        indicator.change_rate = payload.get('change_rate', indicator.change_rate)
        indicator.unit = payload.get('unit', indicator.unit)
        indicator.date = payload.get('date', indicator.date)
        indicator.source = payload.get('source', indicator.source)
        indicator.is_estimated = False

        self._clear_missing_item('macro_indicators', key)
        self._record_manual_update('macro_indicator', key, payload)
        self._log_enhancement('macro_indicator', key, 'manual_update', f"来源: {indicator.source}")
        return True

    def _apply_manual_monetary_entry(self, key: str, payload: Dict[str, Any]) -> bool:
        if not payload:
            return False

        policy = self.market_data.monetary_policy.get(key)
        if not policy:
            policy = MonetaryPolicyData(
                policy_name=payload.get('name', key.upper()),
                current_value=None,
                change_from_120d=None,
                unit=payload.get('unit', '%'),
                date=payload.get('date', self.market_data.metadata.get('date')),
                source=payload.get('source', 'manual'),
                is_estimated=True
            )
            self.market_data.monetary_policy[key] = policy

        if payload.get('current_value') is not None:
            policy.current_value = payload['current_value']
        if payload.get('change_from_120d') is not None:
            policy.change_from_120d = payload['change_from_120d']
        policy.unit = payload.get('unit', policy.unit)
        policy.date = payload.get('date', policy.date)
        policy.source = payload.get('source', policy.source)
        policy.is_estimated = False

        self._clear_missing_item('monetary_policy', key)
        self._record_manual_update('monetary_policy', key, payload)
        self._log_enhancement('monetary_policy', key, 'manual_update', f"来源: {policy.source}")
        return True

    def _apply_manual_commodity_entry(self, symbol: str, payload: Dict[str, Any]) -> bool:
        entry = self._find_commodity_entry(symbol)
        if not entry or not payload:
            return False

        entry.current_price = payload.get('current_price', entry.current_price)
        entry.unit = payload.get('unit', entry.unit)
        entry.daily_change = payload.get('daily_change', entry.daily_change)
        entry.ytd_change = payload.get('ytd_change', entry.ytd_change)
        entry.trend = payload.get('trend', entry.trend)
        entry.source = payload.get('source', entry.source)
        entry.timestamp = payload.get('timestamp', entry.timestamp or datetime.now().isoformat())

        self._clear_missing_item('commodities', symbol)
        self._record_manual_update('commodity', symbol, payload)
        self._log_enhancement('commodity', symbol, 'manual_update', f"来源: {entry.source}")
        return True

    def _apply_manual_bond_entry(self, symbol: str, payload: Dict[str, Any]) -> bool:
        entry = self._find_bond_entry(symbol)
        if not entry or not payload:
            return False

        if payload.get('current_yield') is not None:
            entry.current_yield = payload['current_yield']
        if payload.get('change_5d_bp') is not None:
            entry.change_5d_bp = payload['change_5d_bp']
        if payload.get('change_120d_bp') is not None:
            entry.change_120d_bp = payload['change_120d_bp']
        entry.trend = payload.get('trend', entry.trend)
        entry.source = payload.get('source', entry.source)
        entry.is_estimated = False

        self._clear_missing_item('bonds', symbol)
        self._record_manual_update('bond', symbol, payload)
        self._log_enhancement('bond', symbol, 'manual_update', f"来源: {entry.source}")
        return True

    def _apply_manual_fund_flow_entry(self, key: str, payload: Dict[str, Any]) -> bool:
        if not payload:
            return False

        flow_entry = self.market_data.fund_flow.get(key)
        if not flow_entry:
            flow_entry = FundFlowData(
                type=key,
                recent_5d=None,
                total_120d=None,
                trend='待获取',
                source='MCP WebSearch待获取',
                note=None
            )
            self.market_data.fund_flow[key] = flow_entry

        recent_value = FundFlowData._parse_amount(payload.get('recent_5d'))
        total_value = FundFlowData._parse_amount(payload.get('total_120d'))

        if recent_value is not None:
            flow_entry.recent_5d = recent_value
        if total_value is not None:
            flow_entry.total_120d = total_value

        normalized_source, anomaly_note = self._normalize_fund_flow_source(
            payload,
            flow_entry.recent_5d,
            flow_entry.total_120d
        )
        flow_entry.trend = self._infer_fund_flow_trend(payload, flow_entry.recent_5d)
        flow_entry.source = normalized_source
        flow_entry.note = self._compose_fund_flow_note(payload, extra_note=anomaly_note)

        self._clear_missing_item('fund_flow', key)
        self._record_manual_update('fund_flow', key, payload)
        self._log_enhancement('fund_flow', key, 'manual_update', flow_entry.source)
        return True

    @staticmethod
    def _normalize_fund_flow_source(
        payload: Dict[str, Any],
        recent_value: Optional[float],
        total_value: Optional[float]
    ) -> Tuple[str, Optional[str]]:
        """
        资金流向统一通过 MCP WebSearch 获取，若出现零值则标注异常，后续需重新核验。
        """
        abnormal = any(value == 0 for value in (recent_value, total_value) if value is not None)
        anomaly_note = "异常: 零值待WebSearch复核" if abnormal else None
        return "MCP WebSearch实时获取", anomaly_note

    @staticmethod
    def _infer_fund_flow_trend(payload: Dict[str, Any], recent_value: Optional[float]) -> str:
        if recent_value is not None:
            if recent_value > 0:
                return '流入'
            if recent_value < 0:
                return '流出'
        return payload.get('trend') or '未知'

    @staticmethod
    def _compose_fund_flow_note(payload: Dict[str, Any], *, extra_note: Optional[str] = None) -> Optional[str]:
        parts = []
        raw_source = payload.get('source')
        if raw_source:
            parts.append(f"来源:{raw_source}")
        if payload.get('unit'):
            parts.append(f"单位:{payload['unit']}")
        if payload.get('note'):
            parts.append(payload['note'])
        if payload.get('recent_5d'):
            parts.append(f"原始5日:{payload['recent_5d']}")
        if payload.get('total_120d'):
            parts.append(f"原始120日:{payload['total_120d']}")
        if extra_note:
            parts.append(extra_note)
        note = '；'.join(part for part in parts if part)
        return note or None

    def _record_manual_update(self, category: str, key: str, payload: Dict[str, Any]):
        manual_log = self.enhancement_log.setdefault('manual_updates', [])
        manual_log.append({
            'timestamp': datetime.now().isoformat(),
            'category': category,
            'item': key,
            'payload': payload
        })

    async def _fill_commodities(self, commodity_symbols: List[str]):
        """填充商品数据 (Stage 2a关键步骤)

        增强特性：
        - MCP优先获取
        - MCP失败时自动降级到WebSearch（使用可信数据源）
        """
        if not commodity_symbols:
            print("  [INFO] 商品数据完整")
            return

        if not self.mcp_fetcher:
            print("  [WARN] MCP工具未启用，跳过商品获取")
            return

        print(f"  [INFO] 需要获取商品数据: {len(commodity_symbols)} 项")

        for symbol in commodity_symbols:
            commodity_entry = self._find_commodity_entry(symbol)
            if not commodity_entry:
                self._log_error('commodity', symbol, '商品不存在于市场数据中')
                continue

            # 尝试MCP获取
            mcp_success = False
            fetch_cfg = self._get_commodity_fetch_config(symbol, commodity_entry.name)

            try:
                snapshot = await self.mcp_fetcher.webfetch_investing_com(
                    fetch_cfg['asset_name'],
                    fetch_cfg['asset_type']
                )

                if snapshot and self._apply_commodity_snapshot(commodity_entry, snapshot, fetch_cfg['unit']):
                    self._clear_missing_item('commodities', symbol)
                    self._log_enhancement(
                        'commodity',
                        symbol,
                        'updated',
                        f"来源: {snapshot.get('data_source', 'MCP WebFetch')}"
                    )
                    mcp_success = True
                    print(f"    [OK] {symbol} - MCP获取成功")
            except Exception as exc:
                print(f"    [MCP失败] {symbol}: {exc}")
                self._log_error('commodity', symbol, f"MCP WebFetch失败: {exc}")

            # MCP失败，启用WebSearch降级
            if not mcp_success:
                print(f"    [降级] 尝试WebSearch获取 {symbol}")
                fallback_result = await self._websearch_fallback_commodity(symbol)

                if fallback_result:
                    # 记录降级提示
                    self._log_enhancement(
                        'commodity',
                        symbol,
                        'websearch_fallback',
                        f"已生成WebSearch提示词，请手动执行"
                    )

                    # 将提示词保存到日志
                    if 'websearch_prompts' not in self.enhancement_log:
                        self.enhancement_log['websearch_prompts'] = []

                    self.enhancement_log['websearch_prompts'].append({
                        'category': 'commodity',
                        'symbol': symbol,
                        'prompt': fallback_result.get('prompt'),
                        'sources': fallback_result.get('sources')
                    })
                else:
                    self._log_enhancement('commodity', symbol, 'failed', '无可用数据源')
                    print(f"    [失败] {symbol} - 无可用降级方案")

    async def _fill_bonds(self, bond_symbols: List[str]):
        """填充债券数据 (Stage 2a关键步骤)

        增强特性：
        - MCP优先获取
        - MCP失败时自动降级到WebSearch（使用可信数据源）
        """
        if not bond_symbols:
            print("  [INFO] 债券数据完整")
            return

        if not self.mcp_fetcher:
            print("  [WARN] MCP工具未启用，跳过债券获取")
            return

        start_date, end_date = self._get_date_range()
        print(f"  [INFO] 需要获取债券数据: {len(bond_symbols)} 项")

        for symbol in bond_symbols:
            bond_entry = self._find_bond_entry(symbol)
            if not bond_entry:
                self._log_error('bond', symbol, '债券不存在于市场数据中')
                continue

            # 尝试MCP获取
            mcp_success = False
            try:
                result = await self.mcp_fetcher.get_bond_yield_data_mcp(symbol, start_date, end_date)
                if result and self._apply_bond_result(bond_entry, result):
                    self._clear_missing_item('bonds', symbol)
                    self._log_enhancement(
                        'bond',
                        symbol,
                        'updated',
                        f"来源: {result.get('source', 'MCP WebSearch')}"
                    )
                    mcp_success = True
                    print(f"    [OK] {symbol} - MCP获取成功")
            except Exception as exc:
                print(f"    [MCP失败] {symbol}: {exc}")
                self._log_error('bond', symbol, f"MCP获取失败: {exc}")

            # MCP失败，启用WebSearch降级
            if not mcp_success:
                print(f"    [降级] 尝试WebSearch获取 {symbol}")
                fallback_result = await self._websearch_fallback_bond(symbol)

                if fallback_result:
                    # 记录降级提示
                    self._log_enhancement(
                        'bond',
                        symbol,
                        'websearch_fallback',
                        f"已生成WebSearch提示词，请手动执行"
                    )

                    # 将提示词保存到日志
                    if 'websearch_prompts' not in self.enhancement_log:
                        self.enhancement_log['websearch_prompts'] = []

                    self.enhancement_log['websearch_prompts'].append({
                        'category': 'bond',
                        'symbol': symbol,
                        'prompt': fallback_result.get('prompt'),
                        'sources': fallback_result.get('sources')
                    })
                else:
                    self._log_enhancement('bond', symbol, 'failed', '无可用数据源')
                    print(f"    [失败] {symbol} - 无可用降级方案")

    async def _fill_fund_flow(self, flow_keys: List[str]):
        """???????? (Full/Supplement ??)"""
        if not flow_keys:
            print("  [INFO] ????????")
            return

        if not self.mcp_fetcher:
            print("  [WARN] MCP????????????")
            return

        print(f"  [INFO] ??????: {len(flow_keys)} ?")
        for key in flow_keys:
            snapshot = await self.mcp_fetcher.get_fund_flow_snapshot(key)
            if not snapshot:
                self._log_enhancement('fund_flow', key, 'skipped', '????????????')
                continue

            flow_entry = self.market_data.fund_flow.get(key)
            if not flow_entry:
                flow_entry = FundFlowData(type=key, recent_5d='N/A', total_120d='N/A', trend='N/A', source='MCP??')
                self.market_data.fund_flow[key] = flow_entry

            flow_entry.recent_5d = snapshot.get('recent_5d', 'N/A')
            flow_entry.total_120d = snapshot.get('total_120d', 'N/A')
            flow_entry.trend = snapshot.get('trend', 'N/A')
            flow_entry.source = snapshot.get('source', 'MCP WebSearch')
            flow_entry.note = snapshot.get('note')

            self._clear_missing_item('fund_flow', key)
            self._log_enhancement('fund_flow', key, 'updated', flow_entry.source)

    async def _fill_financial_news(self):
        """??????"""
        if not self.mcp_fetcher:
            print("  [WARN] MCP????????????")
            self._log_enhancement('financial_news', 'all', 'skipped', 'MCP disabled')
            return

        news_list = await self.mcp_fetcher.get_financial_news_mcp(limit=6)
        if not news_list:
            print("  [WARN] ????????")
            self._log_enhancement('financial_news', 'all', 'skipped', 'no news')
            return

        items = []
        for news in news_list:
            item = FinancialNewsItem(
                title=news.get('title', 'N/A'),
                category=news.get('category', '??'),
                date=news.get('date', datetime.now().strftime('%Y-%m-%d')),
                source=news.get('source', 'MCP WebSearch')
            )
            items.append(item)

        self.market_data.financial_news = items
        self._clear_missing_item('financial_news', 'all')
        self._log_enhancement('financial_news', 'all', 'updated', f"??{len(items)}???")

    def _find_bond_entry(self, symbol: str) -> Optional[BondYieldData]:
        return next((bond for bond in self.market_data.bonds if bond.symbol == symbol), None)

    def _find_commodity_entry(self, symbol: str) -> Optional[CommodityData]:
        return next((item for item in self.market_data.commodities if item.symbol == symbol), None)

    def _get_date_range(self) -> Tuple[str, str]:
        metadata = self.market_data.metadata
        start_date = metadata.get('start_date') or metadata.get('date')
        end_date = metadata.get('end_date') or metadata.get('date')
        return start_date, end_date

    def _get_commodity_fetch_config(self, symbol: str, fallback_name: str) -> Dict[str, str]:
        mapping = {
            'GC=F': {'asset_name': 'COMEX gold futures', 'asset_type': 'commodity', 'unit': '$/oz'},
            'CL=F': {'asset_name': 'WTI crude oil', 'asset_type': 'commodity', 'unit': '$/bbl'},
            'BZ=F': {'asset_name': 'Brent crude oil', 'asset_type': 'commodity', 'unit': '$/bbl'},
            'HG=F': {'asset_name': 'COMEX copper futures', 'asset_type': 'commodity', 'unit': '$/lb'},
            'BCOM': {'asset_name': 'Bloomberg Commodity Index', 'asset_type': 'index', 'unit': 'index'}
        }
        return mapping.get(symbol, {
            'asset_name': fallback_name or symbol,
            'asset_type': 'commodity',
            'unit': getattr(self._find_commodity_entry(symbol), 'unit', 'N/A')
        })

    def _apply_bond_result(self, bond_entry: BondYieldData, result: Dict[str, Any]) -> bool:
        data = result.get('data')
        if data is None:
            return False

        current_yield = None
        change_5d_pct = None
        change_120d_pct = None

        if isinstance(data, dict):
            current_yield = self._safe_float(data.get('current_price') or data.get('current_yield'))
            change_5d_pct = self._safe_float(data.get('change_5d_pct'))
            change_120d_pct = self._safe_float(data.get('change_120d_pct'))
        elif hasattr(data, 'tail') and hasattr(data, '__getitem__'):
            try:
                latest = data.tail(1)
                prev = data.tail(6).head(1)
                current_yield = self._safe_float(latest['close'].iloc[-1])
                if current_yield and not prev.empty:
                    prev_value = self._safe_float(prev['close'].iloc[0])
                    if prev_value:
                        change_5d_pct = ((current_yield - prev_value) / prev_value) * 100
            except Exception:
                pass

        if current_yield is None:
            return False

        bond_entry.current_yield = round(current_yield, 3)
        bond_entry.change_5d_bp = self._bp_from_pct(change_5d_pct)
        bond_entry.change_120d_bp = self._bp_from_pct(change_120d_pct)
        bond_entry.trend = self._infer_trend(change_5d_pct)
        bond_entry.source = self._format_source_label(result)
        bond_entry.is_estimated = False
        return True

    def _apply_commodity_snapshot(self, commodity_entry: CommodityData, snapshot: Dict[str, Any], unit_hint: str) -> bool:
        current_price = self._safe_float(snapshot.get('current_price'))
        if current_price is None:
            return False

        commodity_entry.current_price = round(current_price, 2)
        daily_change = self._safe_float(snapshot.get('change_1d_pct') or snapshot.get('daily_change'))
        commodity_entry.daily_change = daily_change if daily_change is not None else 0.0
        ytd_change = self._safe_float(snapshot.get('change_120d_pct') or snapshot.get('ytd_change'))
        if ytd_change is not None:
            commodity_entry.ytd_change = ytd_change
        commodity_entry.trend = self._infer_trend(daily_change)
        commodity_entry.unit = commodity_entry.unit or unit_hint or 'N/A'
        commodity_entry.source = snapshot.get('data_source', 'MCP WebFetch(Investing.com)')
        commodity_entry.timestamp = snapshot.get('timestamp', datetime.now().isoformat())
        return True

    def _bp_from_pct(self, pct: Optional[float]) -> Optional[float]:
        if pct is None:
            return None
        return round(pct * 100, 2)

    def _infer_trend(self, change_value: Optional[float]) -> str:
        if change_value is None:
            return "N/A"
        if change_value > 0:
            return "上涨"
        if change_value < 0:
            return "下行"
        return "持平"

    def _safe_float(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def _websearch_fallback_bond(self, symbol: str) -> Optional[Dict[str, Any]]:
        """WebSearch降级：获取债券数据

        Args:
            symbol: 债券代码（如CN10Y, CN10Y_CDB）

        Returns:
            包含债券数据的字典，失败返回None
        """
        if symbol not in self.trusted_sources['bonds']:
            return None

        config = self.trusted_sources['bonds'][symbol]
        print(f"    [WebSearch降级] {config['name']} - 使用可信数据源")

        # 记录降级尝试
        self.enhancement_log['websearch_fallbacks'].append({
            'timestamp': datetime.now().isoformat(),
            'category': 'bond',
            'symbol': symbol,
            'name': config['name'],
            'sources': config['sources'],
            'status': 'attempted'
        })

        # 生成WebSearch提示词
        prompt = f"""
请通过WebSearch获取{config['name']}的最新数据：

**数据源优先级**:
{chr(10).join([f"  {i+1}. {src}" for i, src in enumerate(config['sources'])])}

**搜索关键词**: {config['keywords']}

**需要的数据**:
- 当前收益率 (%)
- 近5日变化 (bp)
- 近120日变化 (bp)
- 数据日期
- 数据来源

**返回格式**: 请以结构化方式提供数据（收益率、变化幅度、数据源）
"""

        print(f"    [提示] 请手动执行WebSearch: {config['keywords']}")
        print(f"    [提示] 可信数据源: {', '.join(config['sources'])}")

        # 返回提示信息（实际数据需要手动填充或通过MCP工具获取）
        return {
            'symbol': symbol,
            'name': config['name'],
            'prompt': prompt,
            'sources': config['sources'],
            'method': 'WebSearch降级',
            'status': 'manual_required'
        }

    async def _websearch_fallback_commodity(self, symbol: str) -> Optional[Dict[str, Any]]:
        """WebSearch降级：获取商品数据

        Args:
            symbol: 商品代码（如GC=F, CL=F等）

        Returns:
            包含商品数据的字典，失败返回None
        """
        if symbol not in self.trusted_sources['commodities']:
            return None

        config = self.trusted_sources['commodities'][symbol]
        print(f"    [WebSearch降级] {config['name']} - 使用可信数据源")

        # 记录降级尝试
        self.enhancement_log['websearch_fallbacks'].append({
            'timestamp': datetime.now().isoformat(),
            'category': 'commodity',
            'symbol': symbol,
            'name': config['name'],
            'sources': config['sources'],
            'status': 'attempted'
        })

        # 生成WebSearch提示词
        prompt = f"""
请通过WebSearch获取{config['name']}的最新数据：

**数据源优先级**:
{chr(10).join([f"  {i+1}. {src}" for i, src in enumerate(config['sources'])])}

**搜索关键词**: {config['keywords']}

**需要的数据**:
- 当前价格
- 单位 ($/oz, $/bbl等)
- 日涨跌幅 (%)
- 年初至今涨跌 (%)
- 数据时间
- 数据来源

**返回格式**: 请以结构化方式提供数据（价格、涨跌幅、数据源）
"""

        print(f"    [提示] 请手动执行WebSearch: {config['keywords']}")
        print(f"    [提示] 可信数据源: {', '.join(config['sources'])}")

        # 返回提示信息（实际数据需要手动填充或通过MCP工具获取）
        return {
            'symbol': symbol,
            'name': config['name'],
            'prompt': prompt,
            'sources': config['sources'],
            'method': 'WebSearch降级',
            'status': 'manual_required'
        }

    def _clear_missing_item(self, category: str, key: str):
        missing = self.market_data.metadata.get('missing_items')
        if not missing or category not in missing:
            return
        missing[category] = [item for item in missing[category] if item.get('key') != key]

    def _format_source_label(self, result: Dict[str, Any]) -> str:
        method = result.get('method', '')
        source = result.get('source', 'MCP Source')
        return f"MCP {method or source}".strip()

    def _log_error(self, category: str, item: str, message: str):
        print(f"    [ERROR] {item}: {message}")
        self.enhancement_log['errors'].append({
            'timestamp': datetime.now().isoformat(),
            'category': category,
            'item': item,
            'message': message
        })

    def _log_enhancement(self, category: str, item: str, status: str, details: str):
        """记录增强操作"""
        self.enhancement_log['enhancements'].append({
            'timestamp': datetime.now().isoformat(),
            'category': category,
            'item': item,
            'status': status,
            'details': details
        })

    def _build_result(self, enhanced: bool) -> Dict[str, Any]:
        """构建返回结果

        Returns:
            包含增强后MarketDataContract的字典
        """
        return {
            'enhanced': enhanced,
            'market_data': self.market_data.model_dump(),
            'log': self.enhancement_log
        }

    def _print_summary(self):
        """打印摘要"""
        enhancements = len(self.enhancement_log['enhancements'])
        errors = len(self.enhancement_log['errors'])
        websearch_fallbacks = len(self.enhancement_log.get('websearch_fallbacks', []))
        websearch_prompts = len(self.enhancement_log.get('websearch_prompts', []))

        print(f"\n{'='*70}")
        print(f"增强完成:")
        print(f"  - 处理项数: {enhancements}")
        print(f"  - 错误数: {errors}")

        if websearch_fallbacks > 0:
            print(f"  - WebSearch降级: {websearch_fallbacks} 项")
            print(f"  - 生成提示词: {websearch_prompts} 个")

            if websearch_prompts > 0:
                print(f"\n  [提示] WebSearch提示词已保存到日志文件")
                print(f"  [提示] 可查看日志获取详细的搜索关键词和数据源")

        print(f"{'='*70}\n")

    def _refresh_metadata_complete(self):
        """刷新数据完整性元数据

        重新计算数据完整度，移除已填充项目的missing_items记录
        """
        missing = self.market_data.metadata.get('missing_items')
        if isinstance(missing, dict):
            for category in list(missing.keys()):
                if not missing[category]:
                    del missing[category]
            if not missing:
                self.market_data.metadata.pop('missing_items', None)

        # 重新计算数据完整度
        total_expected = 0
        total_available = 0

        # 统计各类数据
        total_expected += 5  # 股票指数（假设5个）
        total_available += len([
            idx for idx in self.market_data.stock_indices
            if idx.current_price is not None and idx.current_price > 0
        ])

        total_expected += 6  # 商品（假设6个）
        total_available += len([
            c for c in self.market_data.commodities
            if not self._is_suspicious_numeric(c.current_price) and not self._is_placeholder_source(c.source)
        ])

        total_expected += 3  # 债券（假设3个）
        total_available += len([
            b for b in self.market_data.bonds
            if not self._is_suspicious_numeric(b.current_yield) and not b.is_estimated
        ])

        macro_values = self.market_data.macro_indicators or {}
        total_expected += len(macro_values)
        total_available += len([
            indicator for indicator in macro_values.values()
            if indicator.current_value is not None and not indicator.is_estimated
        ])

        monetary_values = self.market_data.monetary_policy or {}
        total_expected += len(monetary_values)
        total_available += len([
            policy for policy in monetary_values.values()
            if policy.current_value is not None and not policy.is_estimated
        ])

        fund_flow_values = self.market_data.fund_flow or {}
        total_expected += len(fund_flow_values)
        total_available += len([
            flow for flow in fund_flow_values.values()
            if flow.recent_5d is not None and flow.source != 'MCP WebSearch待获取'
        ])

        # 更新completeness
        if total_expected > 0:
            previous = self.market_data.metadata.get('data_completeness')
            completeness = round(total_available / total_expected, 4)
            self.market_data.metadata['data_completeness'] = completeness
            self.enhancement_log.setdefault('data_completeness', []).append({
                'timestamp': datetime.now().isoformat(),
                'before': previous,
                'after': completeness,
                'total_expected': total_expected,
                'total_available': total_available
            })


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='Archived Stage 2a/4: MCP Data Enhancer',
        epilog='Stage 2a模式(默认): 只填充债券+商品\nStage 4模式(--full): 填充所有数据'
    )
    parser.add_argument('--market-data', required=True, help='Path to market_data.json from Stage 1')
    parser.add_argument('--pring-result', help='Path to pring_result.json (optional for Stage 2a)')
    parser.add_argument('--output', required=True, help='Output path for enhanced market_data.json')
    parser.add_argument('--disable-mcp', action='store_true', help='Disable MCP tools')
    parser.add_argument('--log-output', help='Path to save enhancement log')
    parser.add_argument('--websearch-results', help='手动WebSearch结果JSON，用于写入真实数据')
    parser.add_argument('--run-archived', action='store_true',
                        help='显式运行归档工具，仅用于历史比对；当前补数请使用 Stage2/Stage2.5 主链路')
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('--full', action='store_true',
                       help='Stage 2a????: ??+??+??+??')
    mode_group.add_argument('--supplement', action='store_true',
                       help='Stage 4????: ?????+????')

    args = parser.parse_args()

    if not args.run_archived:
        print(
            "[ARCHIVED] scripts/legacy/mcp_data_enhancer.py 已停用为归档工具。\n"
            "当前补数请使用 scripts/stage2_unified_enhancer.py 与 scripts/stage2_5_injector.py。\n"
            "如仅需历史比对，可显式添加 --run-archived。",
            file=sys.stderr,
        )
        raise SystemExit(2)

    # 创建增强器
    enhancer = MCPDataEnhancer(
        market_data_path=args.market_data,
        pring_result_path=args.pring_result if args.pring_result else None,  # Stage 2a模式下可为None
        enable_mcp=not args.disable_mcp,
        websearch_results_path=args.websearch_results
    )

    # 执行增强
    if args.supplement:
        mode = 'supplement'
    elif args.full:
        mode = 'full'
    else:
        mode = 'essential'

    result = await enhancer.enhance(mode=mode)

    # 保存结果
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 保存增强后的market_data.json
    if result['enhanced']:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result['market_data'], f, ensure_ascii=False, indent=2)
        print(f"[OK] 增强后的market_data已保存: {output_path}")
    else:
        print(f"[INFO] MCP未启用,输出原始market_data")

    # 保存增强日志
    if args.log_output:
        log_path = Path(args.log_output)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(result['log'], f, ensure_ascii=False, indent=2)
        print(f"[OK] 增强日志已保存: {log_path}")



    mode_desc = {'essential': 'Stage 2a (Essential)', 'full': 'Stage 2a (Full)', 'supplement': 'Stage 4 (Supplement)'}[mode]
    print(f"\n[??] {mode_desc} ????")

if __name__ == '__main__':
    asyncio.run(main())
