#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
资金流向数据流水线测试

测试范围:
1. Stage 1: collect_fund_flow()创建4个占位符
2. Stage 4: 识别占位符并生成MCP提示词
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
from src.datasource.models.market_data_contract import MarketDataContract


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

    def test_stage1_creates_fund_flow_placeholders(self):
        """测试Stage 1创建4个资金流向占位符"""

        async def run_test():
            collector = MarketDataCollector(
                end_date=self.test_date
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

            # 验证每个占位符的数据结构
            for key, flow_data in fund_flow.items():
                self.assertEqual(flow_data.type, key)
                self.assertIsNone(flow_data.recent_5d)
                self.assertIsNone(flow_data.total_120d)
                self.assertEqual(flow_data.trend, '待获取')
                self.assertEqual(flow_data.source, 'MCP WebSearch待获取')
                self.assertIn('需要MCP WebSearch实时获取', flow_data.note)

            print("[OK] Stage 1正确创建了4个资金流向占位符")

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

    def test_manual_updater_script_exists(self):
        """测试手动更新工具脚本存在"""
        updater_path = PROJECT_ROOT / "scripts" / "utility" / "manual_fund_flow_updater.py"
        self.assertTrue(updater_path.exists(), f"手动更新工具不存在: {updater_path}")

        # 验证脚本可导入
        spec = __import__('importlib.util').util.spec_from_file_location(
            "manual_fund_flow_updater", updater_path
        )
        self.assertIsNotNone(spec)

        print(f"[OK] 手动更新工具存在: {updater_path}")

    def test_manual_updater_updates_market_data(self):
        """测试手动更新工具正确更新market_data"""
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
        sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "utility"))
        from manual_fund_flow_updater import update_fund_flow

        # 执行更新
        update_fund_flow(
            market_data_path=str(temp_file),
            flow_type='northbound',
            recent_5d='+132.6亿',
            total_120d='+845.2亿',
            trend='持续流入',
            source='MCP WebSearch实时获取',
            note='数据来源：东方财富网'
        )

        # 验证更新结果
        with open(temp_file, 'r', encoding='utf-8') as f:
            updated_data = json.load(f)

        northbound = updated_data['fund_flow']['northbound']
        self.assertAlmostEqual(northbound['recent_5d'], 132.6, places=2)
        self.assertAlmostEqual(northbound['total_120d'], 845.2, places=2)
        self.assertEqual(northbound['trend'], '流入')
        self.assertEqual(northbound['source'], 'MCP WebSearch实时获取')
        self.assertIn('来源:MCP WebSearch实时获取', northbound['note'])
        self.assertIn('原始5日:+132.6亿', northbound['note'])
        self.assertIn('原始120日:+845.2亿', northbound['note'])

        print("[OK] 手动更新工具正确更新了market_data")

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

        sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "utility"))
        from manual_fund_flow_updater import update_fund_flow

        update_fund_flow(
            market_data_path=str(temp_file),
            flow_type='southbound',
            recent_5d='0',
            total_120d='0',
            trend='震荡',
            source='AKShare官方数据',
            note='零值待确认'
        )

        with open(temp_file, 'r', encoding='utf-8') as f:
            updated = json.load(f)

        southbound = updated['fund_flow']['southbound']
        self.assertEqual(southbound['source'], 'MCP WebSearch实时获取')
        self.assertIn('异常: 零值待WebSearch复核', southbound['note'])
        self.assertIn('来源:AKShare官方数据', southbound['note'])

        print("[OK] 手动更新工具正确更新了market_data")

    def test_stage4_generates_fund_flow_prompts(self):
        """测试Stage 4生成资金流向MCP提示词"""
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

        print(f"[OK] Stage 4正确生成了{len(prompts)}个资金流向MCP提示词")

    def test_integration_stage1_to_stage4(self):
        """集成测试: Stage 1 → Stage 4完整流程"""

        async def run_integration_test():
            # Step 1: Stage 1收集数据
            collector = MarketDataCollector(
                end_date=self.test_date
            )
            fund_flow = await collector.collect_fund_flow()

            # 验证创建了4个占位符
            self.assertEqual(len(fund_flow), 4)

            # Step 2: 模拟扫描占位符
            placeholders = []
            for key, flow_data in fund_flow.items():
                if flow_data.source == 'MCP WebSearch待获取':
                    placeholders.append(key)

            # 验证识别了4个占位符
            self.assertEqual(len(placeholders), 4)

            # Step 3: 生成MCP提示词
            from src.datasource.mcp_adapter import MCPToolAdapter
            adapter = MCPToolAdapter(enable_validation=True)
            prompts = adapter.generate_fund_flow_prompts(placeholders)

            # 验证生成了4个提示词
            self.assertEqual(len(prompts), 4)

            # Step 4: 验证提示词格式化输出
            formatted = adapter.format_prompts_for_ai(prompts)
            self.assertIsInstance(formatted, str)
            self.assertIn('北向资金', formatted)
            self.assertIn('南向资金', formatted)
            self.assertIn('ETF资金流', formatted)
            self.assertIn('融资融券', formatted)

            print("[OK] 集成测试: Stage 1 → Stage 4完整流程成功")

        asyncio.run(run_integration_test())


if __name__ == '__main__':
    # 运行测试
    unittest.main(verbosity=2)
