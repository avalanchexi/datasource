#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MCP Tool Adapter (方案C: AI手工执行模式)
职责: 生成AI可执行的MCP工具调用提示词
输出: 结构化的提示词,供AI在对话中执行WebSearch/WebFetch
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
import json


@dataclass
class MCPPrompt:
    """MCP工具调用提示词"""
    tool: str  # 'WebSearch' or 'WebFetch'
    category: str  # 'commodity', 'bond', 'fund_flow', 'financial_news'
    item: str  # 具体项目名称
    query: str  # 搜索查询或URL
    context: str  # 上下文说明
    expected_fields: List[str]  # 期望获取的字段
    data_source_hint: str  # 数据源提示


class MCPToolAdapter:
    """MCP工具适配器 (方案C实现)

    方案C特点:
    - 不直接调用MCP工具
    - 生成结构化提示词,供AI手工执行
    - 收集AI执行结果并验证
    - 适合快速原型和设计验证
    """

    def __init__(self, enable_validation: bool = True):
        """初始化MCP适配器

        Args:
            enable_validation: 是否启用数据验证
        """
        self.enable_validation = enable_validation
        self.prompts_generated: List[MCPPrompt] = []
        self.results_collected: Dict[str, Any] = {}

    # ========== 商品数据填充 ==========

    def generate_commodity_prompts(self, commodity_symbols: List[str]) -> List[MCPPrompt]:
        """生成商品数据获取提示词

        Args:
            commodity_symbols: 商品符号列表 (e.g., ['COMEX黄金', 'WTI原油'])

        Returns:
            MCP提示词列表
        """
        prompts = []

        # 商品映射表 (支持Yahoo符号和中文名称)
        commodity_mapping = {
            # Yahoo符号
            'GC=F': {
                'name': 'COMEX黄金',
                'query': 'COMEX gold futures price today',
                'source': 'Investing.com, Bloomberg, Kitco',
                'fields': ['current_price', 'daily_change', 'ytd_change', 'trend']
            },
            'CL=F': {
                'name': 'WTI原油',
                'query': 'WTI crude oil price today',
                'source': 'Investing.com, Bloomberg, EIA',
                'fields': ['current_price', 'daily_change', 'ytd_change', 'trend']
            },
            'BZ=F': {
                'name': 'Brent原油',
                'query': 'Brent crude oil price today',
                'source': 'Investing.com, Bloomberg, EIA',
                'fields': ['current_price', 'daily_change', 'ytd_change', 'trend']
            },
            'HG=F': {
                'name': 'COMEX铜',
                'query': 'COMEX copper futures price today',
                'source': 'Investing.com, Bloomberg, LME',
                'fields': ['current_price', 'daily_change', 'ytd_change', 'trend']
            },
            'BCOM': {
                'name': 'BCOM指数',
                'query': 'Bloomberg Commodity Index BCOM today',
                'source': 'Bloomberg, Investing.com',
                'fields': ['current_value', 'daily_change', 'ytd_change', 'trend']
            },
            'GSG': {
                'name': 'GSG ETF',
                'query': 'iShares S&P GSCI Commodity-Indexed Trust GSG price',
                'source': 'Yahoo Finance, iShares, Investing.com',
                'fields': ['current_price', 'daily_change', 'ytd_change', 'trend']
            },
            # 中文名称(别名)
            'COMEX黄金': {
                'name': 'COMEX黄金',
                'query': 'COMEX gold futures price today',
                'source': 'Investing.com, Bloomberg, Kitco',
                'fields': ['current_price', 'daily_change', 'ytd_change', 'trend']
            },
            'WTI原油': {
                'name': 'WTI原油',
                'query': 'WTI crude oil price today',
                'source': 'Investing.com, Bloomberg, EIA',
                'fields': ['current_price', 'daily_change', 'ytd_change', 'trend']
            },
            'Brent原油': {
                'name': 'Brent原油',
                'query': 'Brent crude oil price today',
                'source': 'Investing.com, Bloomberg, EIA',
                'fields': ['current_price', 'daily_change', 'ytd_change', 'trend']
            },
            'COMEX铜': {
                'name': 'COMEX铜',
                'query': 'COMEX copper futures price today',
                'source': 'Investing.com, Bloomberg, LME',
                'fields': ['current_price', 'daily_change', 'ytd_change', 'trend']
            },
            'BCOM指数': {
                'name': 'BCOM指数',
                'query': 'Bloomberg Commodity Index BCOM today',
                'source': 'Bloomberg, Investing.com',
                'fields': ['current_value', 'daily_change', 'ytd_change', 'trend']
            },
            'GSG ETF': {
                'name': 'GSG ETF',
                'query': 'iShares S&P GSCI Commodity-Indexed Trust GSG price',
                'source': 'Yahoo Finance, iShares, Investing.com',
                'fields': ['current_price', 'daily_change', 'ytd_change', 'trend']
            }
        }

        for symbol in commodity_symbols:
            if symbol in commodity_mapping:
                config = commodity_mapping[symbol]
                display_name = config.get('name', symbol)
                prompt = MCPPrompt(
                    tool='WebSearch',
                    category='commodity',
                    item=display_name,
                    query=config['query'],
                    context=f"获取{display_name}的最新价格和趋势数据",
                    expected_fields=config['fields'],
                    data_source_hint=config['source']
                )
                prompts.append(prompt)
                self.prompts_generated.append(prompt)

        return prompts

    # ========== 债券数据填充 ==========

    def generate_bond_prompts(self, bond_symbols: List[str]) -> List[MCPPrompt]:
        """生成债券数据获取提示词

        Args:
            bond_symbols: 债券符号列表 (e.g., ['CN10Y', 'CN10Y_CDB'])

        Returns:
            MCP提示词列表
        """
        prompts = []

        bond_mapping = {
            'CN10Y': {
                'query': 'China 10-year government bond yield today',
                'source': 'Investing.com, Trading Economics, Wind',
                'fields': ['current_yield', 'change_5d_bp', 'change_120d_bp', 'trend']
            },
            'CN10Y_CDB': {
                'query': 'China 10-year CDB bond yield today 中国国开债收益率',
                'source': 'Investing.com, Wind, 东方财富网',
                'fields': ['current_yield', 'change_5d_bp', 'change_120d_bp', 'trend']
            },
            'US10Y': {
                'query': 'US 10-year treasury yield today',
                'source': 'Yahoo Finance (^TNX), FRED, Investing.com',
                'fields': ['current_yield', 'change_5d_bp', 'change_120d_bp', 'trend']
            }
        }

        for symbol in bond_symbols:
            if symbol in bond_mapping:
                config = bond_mapping[symbol]
                prompt = MCPPrompt(
                    tool='WebSearch',
                    category='bond',
                    item=symbol,
                    query=config['query'],
                    context=f"获取{symbol}债券收益率数据",
                    expected_fields=config['fields'],
                    data_source_hint=config['source']
                )
                prompts.append(prompt)
                self.prompts_generated.append(prompt)

        return prompts

    # ========== 资金流向填充 ==========

    def generate_fund_flow_prompts(self, flow_keys: List[str]) -> List[MCPPrompt]:
        """生成资金流向获取提示词

        Args:
            flow_keys: 资金流向类型 (e.g., ['northbound', 'southbound', 'etf', 'margin'])

        Returns:
            MCP提示词列表
        """
        prompts = []

        flow_mapping = {
            'northbound': {
                'query': '北向资金 今日净买入 最新数据 新闻',
                'source': '东方财富网, 同花顺, 每日经济新闻',
                'fields': ['current_value', 'recent_5d', 'total_120d', 'trend', 'note']
            },
            'southbound': {
                'query': '南向资金今日流入 最新数据 同花顺',
                'source': '同花顺, 东方财富网, Wind',
                'fields': ['recent_5d', 'total_120d', 'trend', 'note']
            },
            'etf': {
                'query': 'ETF资金流向 今日数据 Choice Wind',
                'source': 'Wind, Choice, 东方财富网',
                'fields': ['recent_5d', 'total_120d', 'trend', 'note']
            },
            'margin': {
                'query': '融资融券余额 最新数据 交易所',
                'source': '上交所, 深交所, Wind, 东方财富网',
                'fields': ['recent_5d', 'total_120d', 'trend', 'note']
            }
        }

        for key in flow_keys:
            if key in flow_mapping:
                config = flow_mapping[key]
                prompt = MCPPrompt(
                    tool='WebSearch',
                    category='fund_flow',
                    item=key,
                    query=config['query'],
                    context=f"获取{key}资金流向数据(近5日和近120日)",
                    expected_fields=config['fields'],
                    data_source_hint=config['source']
                )
                prompts.append(prompt)
                self.prompts_generated.append(prompt)

        return prompts

    # ========== 宏观指标 & 货币政策填充 ==========

    def generate_macro_prompts(self, indicator_items: List[Dict[str, Any]]) -> List[MCPPrompt]:
        """生成宏观指标数据获取提示词"""
        prompts: List[MCPPrompt] = []
        for item in indicator_items:
            prompt = MCPPrompt(
                tool='WebSearch',
                category='macro',
                item=item.get('name', item.get('key', 'macro')),
                query=item.get('query', f"{item.get('name', '宏观指标')} 最新数据"),
                context=item.get('context', '获取宏观指标用于库存周期分析'),
                expected_fields=item.get('expected_fields', ['current_value', 'previous_value', 'change_rate', 'date']),
                data_source_hint=item.get('source_hint', 'stats.gov.cn')
            )
            prompts.append(prompt)
            self.prompts_generated.append(prompt)
        return prompts

    def generate_monetary_prompts(self, policy_items: List[Dict[str, Any]]) -> List[MCPPrompt]:
        """生成货币政策数据获取提示词"""
        prompts: List[MCPPrompt] = []
        for item in policy_items:
            prompt = MCPPrompt(
                tool='WebSearch',
                category='monetary',
                item=item.get('name', item.get('key', 'policy')),
                query=item.get('query', f"{item.get('name', '货币政策')} 最新数据"),
                context=item.get('context', '获取货币政策指标用于Pring货币周期分析'),
                expected_fields=item.get('expected_fields', ['current_value', 'change_from_120d', 'date']),
                data_source_hint=item.get('source_hint', 'pbc.gov.cn')
            )
            prompts.append(prompt)
            self.prompts_generated.append(prompt)
        return prompts

    # ========== 财经要闻填充 ==========

    def generate_financial_news_prompts(self, target_count: int = 10) -> List[MCPPrompt]:
        """生成财经要闻获取提示词

        Args:
            target_count: 目标新闻数量

        Returns:
            MCP提示词列表
        """
        prompts = []

        # 按类别分组查询
        news_categories = [
            {
                'category': 'macro_policy',
                'query': '中国宏观政策 最新新闻 央行 财政部',
                'count': 3
            },
            {
                'category': 'market_dynamics',
                'query': 'A股市场动态 最新消息 沪深300',
                'count': 3
            },
            {
                'category': 'international',
                'query': '国际金融市场 美联储 美股 原油',
                'count': 2
            },
            {
                'category': 'industry_hot',
                'query': '行业热点 科技 消费 新能源',
                'count': 2
            }
        ]

        for cat_config in news_categories:
            prompt = MCPPrompt(
                tool='WebSearch',
                category='financial_news',
                item=cat_config['category'],
                query=cat_config['query'],
                context=f"获取{cat_config['count']}条{cat_config['category']}类财经要闻",
                expected_fields=['title', 'summary', 'source', 'date'],
                data_source_hint='新浪财经, 财联社, 东方财富网, 华尔街见闻'
            )
            prompts.append(prompt)
            self.prompts_generated.append(prompt)

        return prompts

    # ========== 提示词生成和输出 ==========

    def format_prompts_for_ai(self, prompts: List[MCPPrompt]) -> str:
        """格式化提示词供AI执行

        Args:
            prompts: MCP提示词列表

        Returns:
            格式化的Markdown文本
        """
        output = ["# MCP数据获取任务清单", ""]
        output.append(f"**生成时间**: {datetime.now().isoformat()}")
        output.append(f"**任务总数**: {len(prompts)}")
        output.append("")

        # 按类别分组
        categories = {}
        for prompt in prompts:
            if prompt.category not in categories:
                categories[prompt.category] = []
            categories[prompt.category].append(prompt)

        # 输出每个类别
        category_names = {
            'commodity': '商品数据',
            'bond': '债券数据',
            'fund_flow': '资金流向',
            'financial_news': '财经要闻',
            'macro': '宏观指标',
            'monetary': '货币政策'
        }

        for cat_key, cat_name in category_names.items():
            if cat_key in categories:
                output.append(f"## {cat_name} ({len(categories[cat_key])}项)")
                output.append("")

                for i, prompt in enumerate(categories[cat_key], 1):
                    output.append(f"### 任务 {i}: {prompt.item}")
                    output.append(f"- **工具**: `{prompt.tool}`")
                    output.append(f"- **查询**: `{prompt.query}`")
                    output.append(f"- **数据源**: {prompt.data_source_hint}")
                    output.append(f"- **期望字段**: {', '.join(prompt.expected_fields)}")
                    output.append(f"- **上下文**: {prompt.context}")
                    output.append("")
                    output.append("**执行示例**:")
                    output.append(f"```python")
                    output.append(f"# 使用MCP {prompt.tool}工具")
                    output.append(f"query = '{prompt.query}'")
                    output.append(f"# 获取数据后填充字段: {', '.join(prompt.expected_fields)}")
                    output.append(f"```")
                    output.append("")

        output.append("---")
        output.append("**执行说明**:")
        output.append("1. 依次执行上述WebSearch/WebFetch任务")
        output.append("2. 提取所需字段数据")
        output.append("3. 使用 `collect_result()` 方法回传数据")
        output.append("4. 继续下一个任务直到完成")

        return "\n".join(output)

    # ========== 结果收集和验证 ==========

    def collect_result(self, category: str, item: str, data: Dict[str, Any]) -> bool:
        """收集AI执行的MCP结果

        Args:
            category: 数据类别
            item: 数据项
            data: 获取的数据

        Returns:
            验证是否通过
        """
        key = f"{category}_{item}"
        self.results_collected[key] = {
            'category': category,
            'item': item,
            'data': data,
            'timestamp': datetime.now().isoformat(),
            'validated': False
        }

        # 数据验证
        if self.enable_validation:
            is_valid = self._validate_data(category, data)
            self.results_collected[key]['validated'] = is_valid
            return is_valid

        return True

    def _validate_data(self, category: str, data: Dict[str, Any]) -> bool:
        """验证数据完整性

        Args:
            category: 数据类别
            data: 数据字典

        Returns:
            是否有效
        """
        # 基本验证规则
        if category == 'commodity':
            required = ['current_price', 'daily_change']
            return all(field in data for field in required)

        elif category == 'bond':
            required = ['current_yield']
            return all(field in data for field in required)

        elif category == 'fund_flow':
            required = ['recent_5d']
            return all(field in data for field in required)

        elif category == 'financial_news':
            required = ['title']
            return all(field in data for field in required)

        return True

    def get_completion_status(self) -> Dict[str, Any]:
        """获取完成状态

        Returns:
            状态字典
        """
        total_prompts = len(self.prompts_generated)
        total_results = len(self.results_collected)
        validated_results = sum(1 for r in self.results_collected.values() if r['validated'])

        return {
            'total_tasks': total_prompts,
            'completed_tasks': total_results,
            'validated_tasks': validated_results,
            'completion_rate': f"{total_results}/{total_prompts}" if total_prompts > 0 else "0/0",
            'validation_rate': f"{validated_results}/{total_results}" if total_results > 0 else "0/0"
        }

    def export_results_json(self, output_path: str):
        """导出结果为JSON

        Args:
            output_path: 输出路径
        """
        export_data = {
            'metadata': {
                'export_time': datetime.now().isoformat(),
                'total_prompts': len(self.prompts_generated),
                'total_results': len(self.results_collected)
            },
            'results': self.results_collected,
            'status': self.get_completion_status()
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)


# ========== 便捷函数 ==========

def create_mcp_adapter() -> MCPToolAdapter:
    """创建MCP适配器实例"""
    return MCPToolAdapter(enable_validation=True)


def generate_all_prompts(
    commodities: List[str],
    bonds: List[str],
    fund_flows: List[str],
    need_news: bool = True
) -> str:
    """生成所有MCP提示词

    Args:
        commodities: 商品列表
        bonds: 债券列表
        fund_flows: 资金流向列表
        need_news: 是否需要财经要闻

    Returns:
        格式化的提示词文本
    """
    adapter = create_mcp_adapter()
    all_prompts = []

    if commodities:
        all_prompts.extend(adapter.generate_commodity_prompts(commodities))

    if bonds:
        all_prompts.extend(adapter.generate_bond_prompts(bonds))

    if fund_flows:
        all_prompts.extend(adapter.generate_fund_flow_prompts(fund_flows))

    if need_news:
        all_prompts.extend(adapter.generate_financial_news_prompts())

    return adapter.format_prompts_for_ai(all_prompts)


if __name__ == '__main__':
    # 测试示例
    adapter = create_mcp_adapter()

    # 生成商品提示词
    commodity_prompts = adapter.generate_commodity_prompts(['COMEX黄金', 'WTI原油'])

    # 生成债券提示词
    bond_prompts = adapter.generate_bond_prompts(['CN10Y'])

    # 格式化输出
    formatted = adapter.format_prompts_for_ai(commodity_prompts + bond_prompts)
    print(formatted)

    # 获取状态
    print("\n" + "="*70)
    print("完成状态:", adapter.get_completion_status())
