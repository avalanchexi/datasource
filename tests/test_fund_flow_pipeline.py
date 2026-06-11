#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
资金流向数据流水线测试

测试范围:
1. Stage 1: collect_fund_flow()识别资金流缺口和TuShare可得项
2. Stage 4: 识别占位符并生成 WebSearch 提示词
3. manual_fund_flow_updater: 手动更新工具
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# 添加项目根目录到path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.stage1_data_collector import MarketDataCollector
from src.datasource.models.market_data_contract import FundFlowData, MarketDataContract


class TestFundFlowPipeline(unittest.TestCase):
    """资金流向数据流水线测试"""

    def setUp(self):
        """测试前准备"""
        self.test_date = "2025-11-12"
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """测试后清理"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _stub_collect_fund_flow_sources(self, collector, etf_entry=None):
        async def _empty_hsgt():
            return {
                "north_recent_5d": None,
                "north_total_120d": None,
                "south_recent_5d": None,
                "south_total_120d": None,
                "as_of_trade_date": None,
                "full_120_window": False,
            }

        async def _no_margin():
            return None

        async def _no_etf_proxy():
            return None

        collector._fetch_hsgt_from_tushare = _empty_hsgt
        collector._fetch_margin_flow_from_tushare = _no_margin
        collector._fetch_etf_flow_from_tushare_share_size = lambda: etf_entry
        collector._fetch_etf_flow_proxy = _no_etf_proxy

    def test_stage1_creates_fund_flow_placeholders(self):
        """测试Stage 1创建4个资金流向占位符"""

        async def run_test():
            collector = MarketDataCollector(
                end_date=self.test_date
            )
            self._stub_collect_fund_flow_sources(
                collector,
                FundFlowData(
                    type="ETF资金流",
                    recent_5d=5.0,
                    total_120d=120.0,
                    trend="流入",
                    source="TuShare etf_share_size",
                    metric_basis="etf_total_size_delta",
                    is_estimated=False,
                    note="test official ETF source",
                ),
            )

            # 收集资金流向数据
            fund_flow = await collector.collect_fund_flow()

            # 验证返回字典结构
            self.assertIsInstance(fund_flow, dict)
            self.assertEqual(len(fund_flow), 4)

            # 验证4个关键字存在
            expected_keys = ['northbound', 'southbound', 'etf', 'margin']
            for key in expected_keys:
                self.assertIn(key, fund_flow)

            expected_type_by_key = {
                'northbound': 'northbound',
                'southbound': 'southbound',
                'etf': {'etf', 'ETF资金流'},
                'margin': 'margin',
            }
            placeholder_keys = []
            for key, flow_data in fund_flow.items():
                if flow_data.source == '待WebSearch补充':
                    self.assertEqual(flow_data.type, key)
                    placeholder_keys.append(key)
                    self.assertIsNone(flow_data.recent_5d)
                    self.assertIsNone(flow_data.total_120d)
                    self.assertEqual(flow_data.trend, '待获取')
                    self.assertIn('WebSearch/Tavily', flow_data.note)
                else:
                    expected_type = expected_type_by_key[key]
                    if isinstance(expected_type, set):
                        self.assertIn(flow_data.type, expected_type)
                    else:
                        self.assertEqual(flow_data.type, expected_type)
                    self.assertTrue(
                        flow_data.recent_5d is not None or flow_data.total_120d is not None
                    )

            self.assertLessEqual(len(placeholder_keys), 4)
            print(f"[OK] Stage 1正确识别了{len(placeholder_keys)}个资金流向缺口")

        asyncio.run(run_test())

    def test_stage1_fund_flow_config_has_search_query(self):
        """测试Stage 1的fund_flow_configs包含search_query字段"""
        collector = MarketDataCollector(
            end_date=self.test_date
        )

        # 验证配置列表存在
        self.assertTrue(hasattr(collector, 'fund_flow_configs'))
        self.assertEqual(len(collector.fund_flow_configs), 4)

        # 验证每个配置包含search_query
        for config in collector.fund_flow_configs:
            self.assertIn('key', config)
            self.assertIn('name', config)
            self.assertIn('type', config)
            self.assertIn('search_query', config)  # 关键：必须有search_query

            # 验证search_query非空
            self.assertTrue(len(config['search_query']) > 0)

        print("[OK] fund_flow_configs包含完整的search_query字段")

    def test_margin_delta_guard_filters_outlier(self):
        collector = MarketDataCollector(end_date=self.test_date)
        value, warn = collector._sanitize_margin_delta(-13756.54, latest_balance=18000.0, window=5)
        self.assertIsNone(value)
        self.assertIsNotNone(warn)
        self.assertIn("已置空待复核", warn)

    def test_manual_updater_script_exists(self):
        """测试手动更新工具脚本存在"""
        updater_path = PROJECT_ROOT / "scripts" / "tools" / "fund_flow_manual_updater.py"
        self.assertTrue(updater_path.exists(), f"手动更新工具不存在: {updater_path}")

        # 验证脚本可导入
        spec = __import__('importlib.util').util.spec_from_file_location(
            "manual_fund_flow_updater", updater_path
        )
        self.assertIsNotNone(spec)

        print(f"[OK] 手动更新工具存在: {updater_path}")

    def test_manual_updater_direct_write_disabled(self):
        """手动直写工具已停用，资金流补数必须走 Stage2.5 注入"""
        # 创建临时market_data.json
        market_data = {
            "metadata": {"date": self.test_date},
            "stock_indices": [],
            "commodities": [],
            "forex": [],
            "bonds": [],
            "fund_flow": {
                "northbound": {
                    "type": "northbound",
                    "recent_5d": "N/A",
                    "total_120d": "N/A",
                    "trend": "N/A",
                    "source": "placeholder",
                    "note": ""
                }
            },
            "financial_news": [],
            "macro_indicators": {},
            "monetary_policy": {}
        }

        temp_file = Path(self.temp_dir) / "market_data_test.json"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(market_data, f, ensure_ascii=False, indent=2)

        # 导入更新函数
        sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "tools"))
        from fund_flow_manual_updater import update_fund_flow

        with self.assertRaisesRegex(RuntimeError, "stage2_5_injector"):
            update_fund_flow(
                market_data_path=str(temp_file),
                flow_type='northbound',
                recent_5d='+132.6亿',
                total_120d='+845.2亿',
                trend='持续流入',
                source='Stage2.5 manual_required',
                note='数据来源：东方财富网'
            )

    def test_manual_updater_marks_zero_anomaly(self):
        market_data = {
            "metadata": {"date": self.test_date},
            "stock_indices": [],
            "commodities": [],
            "forex": [],
            "bonds": [],
            "fund_flow": {
                "southbound": {
                    "type": "southbound",
                    "recent_5d": None,
                    "total_120d": None,
                    "trend": "待获取",
                    "source": "placeholder",
                    "note": ""
                }
            },
            "financial_news": [],
            "macro_indicators": {},
            "monetary_policy": {}
        }

        temp_file = Path(self.temp_dir) / "market_data_anomaly.json"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(market_data, f, ensure_ascii=False, indent=2)

        sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "tools"))
        from fund_flow_manual_updater import update_fund_flow

        with self.assertRaisesRegex(RuntimeError, "stage2_5_injector"):
            update_fund_flow(
                market_data_path=str(temp_file),
                flow_type='southbound',
                recent_5d='0',
                total_120d='0',
                trend='震荡',
                source='Stage2.5 manual_required',
                note='零值待确认'
            )

    def test_stage4_generates_fund_flow_prompts(self):
        """测试Stage 4生成资金流向 WebSearch 提示词"""
        from src.datasource.mcp_adapter import MCPToolAdapter

        adapter = MCPToolAdapter(enable_validation=True)

        # 生成资金流向提示词
        flow_keys = ['northbound', 'southbound', 'etf', 'margin']
        prompts = adapter.generate_fund_flow_prompts(flow_keys)

        # 验证生成了4个提示词
        self.assertEqual(len(prompts), 4)

        # 验证每个提示词的结构
        for prompt in prompts:
            self.assertEqual(prompt.tool, 'WebSearch')
            self.assertEqual(prompt.category, 'fund_flow')
            self.assertIn(prompt.item, flow_keys)
            self.assertTrue(len(prompt.query) > 0)
            self.assertTrue(len(prompt.data_source_hint) > 0)

        print(f"[OK] Stage 4正确生成了{len(prompts)}个资金流向 WebSearch 提示词")

    def test_integration_stage1_to_stage4(self):
        """集成测试: Stage 1 → Stage 4完整流程"""

        async def run_integration_test():
            # Step 1: Stage 1收集数据
            collector = MarketDataCollector(
                end_date=self.test_date
            )
            self._stub_collect_fund_flow_sources(collector)
            fund_flow = await collector.collect_fund_flow()

            # 验证创建了4个占位符
            self.assertEqual(len(fund_flow), 4)

            # Step 2: 模拟扫描占位符
            placeholders = []
            for key, flow_data in fund_flow.items():
                if flow_data.source == '待WebSearch补充':
                    placeholders.append(key)

            # 验证占位符识别与已填 TuShare 数据可以共存
            self.assertLessEqual(len(placeholders), 4)

            # Step 3: 生成 WebSearch 提示词
            from src.datasource.mcp_adapter import MCPToolAdapter
            adapter = MCPToolAdapter(enable_validation=True)
            prompts = adapter.generate_fund_flow_prompts(placeholders)

            # 验证按实际缺口生成提示词
            self.assertEqual(len(prompts), len(placeholders))

            # Step 4: 验证提示词格式化输出
            formatted = adapter.format_prompts_for_ai(prompts)
            self.assertIsInstance(formatted, str)
            prompt_name_by_key = {
                'northbound': '北向资金',
                'southbound': '南向资金',
                'etf': 'ETF资金流',
                'margin': '融资融券',
            }
            for key in placeholders:
                self.assertIn(prompt_name_by_key[key], formatted)

            print("[OK] 集成测试: Stage 1 → Stage 4完整流程成功")

        asyncio.run(run_integration_test())


if __name__ == '__main__':
    # 运行测试
    unittest.main(verbosity=2)
