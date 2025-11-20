#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI自动执行器 - 背景扫描报告生成
此脚本为AI提供标准化的执行流程和指令模板
"""

import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

class AIExecutionController:
    """AI执行控制器 - 提供标准化的执行步骤和验证"""

    def __init__(self, target_date: str):
        """
        初始化AI执行控制器

        Args:
            target_date: 目标日期，格式YYYYMMDD
        """
        self.target_date = target_date
        self.formatted_date = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}"
        self.start_date = self._calculate_start_date()
        self.report_filename = f"reports/{target_date}背景扫描120.md"

        # 执行阶段状态
        self.phases = {
            "PHASE_1_SETUP": {"name": "环境准备与验证", "status": "pending"},
            "PHASE_2_DATA_COLLECTION": {"name": "数据收集与计算", "status": "pending"},
            "PHASE_3_DATA_COMPLETION": {"name": "缺失数据补充", "status": "pending"},
            "PHASE_4_REPORT_ENHANCEMENT": {"name": "报告优化与完善", "status": "pending"},
            "PHASE_5_QUALITY_CHECK": {"name": "质量验证与交付", "status": "pending"}
        }

    def _calculate_start_date(self) -> str:
        """计算120日数据窗口的起始日期"""
        target = datetime.strptime(self.formatted_date, "%Y-%m-%d")
        start = target - timedelta(days=120)
        return start.strftime("%Y-%m-%d")

    def get_phase_1_instructions(self) -> Dict:
        """获取阶段1执行指令"""
        return {
            "phase": "PHASE_1_SETUP",
            "name": "环境准备与验证",
            "duration": "5分钟",
            "ai_actions": [
                {
                    "action": "create_todo_list",
                    "tool": "TodoWrite",
                    "description": "创建5个阶段的Todo任务列表",
                    "todo_items": [
                        {"content": "环境准备与验证", "status": "in_progress"},
                        {"content": "数据收集与计算", "status": "pending"},
                        {"content": "缺失数据补充", "status": "pending"},
                        {"content": "报告优化与完善", "status": "pending"},
                        {"content": "质量验证与交付", "status": "pending"}
                    ]
                },
                {
                    "action": "verify_environment",
                    "tool": "Bash",
                    "commands": [
                        "ls -la .env",
                        "ls scripts/utility/background_scan_120d_generator.py"
                    ]
                },
                {
                    "action": "test_datasource",
                    "tool": "Bash",
                    "commands": [
                        "python -c \"from datasource import get_manager; print('DataSource OK')\""
                    ]
                }
            ],
            "success_criteria": [
                ".env文件存在",
                "生成器脚本存在",
                "数据源连接正常"
            ]
        }

    def get_phase_2_instructions(self) -> Dict:
        """获取阶段2执行指令"""
        return {
            "phase": "PHASE_2_DATA_COLLECTION",
            "name": "数据收集与计算",
            "duration": "15分钟",
            "ai_actions": [
                {
                    "action": "update_script_dates",
                    "tool": "Edit",
                    "file": "scripts/utility/background_scan_120d_generator.py",
                    "edits": [
                        {
                            "old_string": "self.end_date = \"2025-09-18\"",
                            "new_string": f"self.end_date = \"{self.formatted_date}\""
                        },
                        {
                            "old_string": "self.start_date = \"2025-05-21\"",
                            "new_string": f"self.start_date = \"{self.start_date}\""
                        },
                        {
                            "old_string": "report_filename = f\"reports/20250918背景扫描120.md\"",
                            "new_string": f"report_filename = f\"reports/{self.target_date}背景扫描120.md\""
                        }
                    ]
                },
                {
                    "action": "execute_data_collection",
                    "tool": "Bash",
                    "commands": [
                        "python scripts/utility/background_scan_120d_generator.py"
                    ]
                },
                {
                    "action": "update_todo",
                    "tool": "TodoWrite",
                    "description": "标记阶段1完成，阶段2进行中"
                }
            ],
            "success_criteria": [
                f"生成报告文件 {self.report_filename}",
                "获取核心股票指数数据",
                "普林格分析完成"
            ]
        }

    def get_phase_3_instructions(self) -> Dict:
        """获取阶段3执行指令"""
        return {
            "phase": "PHASE_3_DATA_COMPLETION",
            "name": "缺失数据补充",
            "duration": "20分钟",
            "ai_actions": [
                {
                    "action": "analyze_na_values",
                    "tool": "Read",
                    "file": self.report_filename,
                    "description": "识别所有N/A值和缺失数据"
                },
                {
                    "action": "supplement_stock_data",
                    "tools": ["WebSearch", "WebFetch"],
                    "targets": [
                        "沪深300指数最新价格",
                        "WTI原油(CL=F)最新行情",
                        "Brent原油(BZ=F)最新行情",
                        "COMEX铜(HG=F)最新行情",
                        "现货黄金(XAUUSD)最新行情",
                        "BCOM指数(GSG)最新行情"
                    ],
                    "sources": ["cn.investing.com"]
                },
                {
                    "action": "supplement_forex_data",
                    "tools": ["WebSearch", "WebFetch"],
                    "targets": [
                        "USD/CNY汇率",
                        "美元指数DXY"
                    ],
                    "sources": ["cn.investing.com/currencies", "cn.investing.com/indices"]
                },
                {
                    "action": "supplement_bond_data",
                    "tools": ["WebSearch", "WebFetch"],
                    "targets": [
                        "中国10年期国债收益率",
                        "美国10年期国债收益率"
                    ],
                    "sources": ["investing.com/rates-bonds"]
                },
                {
                    "action": "supplement_capital_flow",
                    "tools": ["WebSearch", "WebFetch"],
                    "targets": [
                        "北向资金流向",
                        "融资融券余额"
                    ],
                    "sources": ["data.eastmoney.com", "相关财经新闻"]
                },
                {
                    "action": "collect_financial_news",
                    "tools": ["WebSearch", "WebFetch"],
                    "targets": [
                        f"{self.formatted_date}财经要闻",
                        "央行政策动态",
                        "股市重要新闻"
                    ],
                    "sources": ["wallstreetcn.com"]
                }
            ],
            "success_criteria": [
                "主要N/A值已补充",
                "收集5-10条财经要闻",
                "所有关键数据完整"
            ]
        }

    def get_phase_4_instructions(self) -> Dict:
        """获取阶段4执行指令"""
        return {
            "phase": "PHASE_4_REPORT_ENHANCEMENT",
            "name": "报告优化与完善",
            "duration": "10分钟",
            "ai_actions": [
                {
                    "action": "batch_update_report",
                    "tool": "MultiEdit",
                    "file": self.report_filename,
                    "sections_to_update": [
                        "市场结论要点",
                        "股票市场综述表格",
                        "商品与黄金表格",
                        "汇率变化表格",
                        "债券收益率表格",
                        "资金流向表格",
                        "财经要闻章节"
                    ]
                },
                {
                    "action": "enhance_market_conclusions",
                    "description": "生成3-6条核心市场观点",
                    "format": "- 过去120天，XXX指数表现，趋势评级\\n- 汇率/债券/资金流向关键变化"
                },
                {
                    "action": "standardize_formats",
                    "standards": {
                        "百分比": "保留1位小数，如-2.4%",
                        "基点": "保留1位小数，如+15.0bp",
                        "价格": "保留2位小数，如3156.78",
                        "斜率": "保留4位小数，如+0.1234"
                    }
                }
            ],
            "success_criteria": [
                "报告内容丰富完整",
                "格式规范统一",
                "市场结论清晰"
            ]
        }

    def get_phase_5_instructions(self) -> Dict:
        """获取阶段5执行指令"""
        return {
            "phase": "PHASE_5_QUALITY_CHECK",
            "name": "质量验证与交付",
            "duration": "5分钟",
            "ai_actions": [
                {
                    "action": "check_structure_completeness",
                    "tool": "Read",
                    "file": self.report_filename,
                    "required_sections": [
                        "市场结论要点",
                        "股票市场综述",
                        "商品与黄金",
                        "汇率变化",
                        "利率与债券收益率",
                        "资金流向综述",
                        "财经要闻",
                        "普林格阶段推断",
                        "附注说明"
                    ]
                },
                {
                    "action": "validate_data_quality",
                    "checks": [
                        "表格无N/A值",
                        "数值格式正确",
                        "时间戳准确",
                        "数据源引用完整"
                    ]
                },
                {
                    "action": "verify_compliance",
                    "required_statements": [
                        "本报告仅供研究与教学参考",
                        "不构成任何投资建议",
                        "投资有风险，决策需谨慎"
                    ]
                },
                {
                    "action": "generate_summary",
                    "tool": "TodoWrite",
                    "description": "完成所有Todo，生成执行总结",
                    "summary_format": f"📊 报告生成完成！\\n📁 文件路径: {self.report_filename}\\n📈 核心发现: [关键观点摘要]"
                }
            ],
            "success_criteria": [
                "质量验证全部通过",
                "Todo列表全部完成",
                "交付总结生成"
            ]
        }

    def get_execution_sequence(self) -> List[Dict]:
        """获取完整的执行序列"""
        return [
            self.get_phase_1_instructions(),
            self.get_phase_2_instructions(),
            self.get_phase_3_instructions(),
            self.get_phase_4_instructions(),
            self.get_phase_5_instructions()
        ]

    def get_ai_prompt_template(self) -> str:
        """获取AI执行的完整提示模板"""
        return f"""
你现在需要执行背景扫描报告生成任务，目标日期：{self.target_date}

请严格按照以下5个阶段顺序执行：

## 阶段执行概览
- 数据窗口：{self.start_date} 至 {self.formatted_date} (120个自然日)
- 输出文件：{self.report_filename}
- 预期时间：45-60分钟

## 执行要求
1. 每个阶段开始前，使用TodoWrite更新任务状态
2. 遇到N/A值时，必须通过WebSearch和WebFetch从可信网站获取数据
3. 所有数据源必须是权威金融网站（如investing.com、东方财富网等）
4. 报告必须包含9个标准章节
5. 最终报告不能有N/A值

## 开始执行
请从阶段1开始执行，完成一个阶段后再进行下一个阶段。

阶段1: 环境准备与验证 -> 创建Todo列表并验证环境
阶段2: 数据收集与计算 -> 修改脚本配置并执行数据收集
阶段3: 缺失数据补充 -> 通过网络获取所有缺失数据
阶段4: 报告优化与完善 -> 使用MultiEdit批量更新报告
阶段5: 质量验证与交付 -> 检查质量并生成交付总结

开始执行阶段1。
"""

def get_ai_execution_instructions(target_date: str) -> Dict:
    """
    为AI提供完整的执行指令

    Args:
        target_date: 目标日期，格式YYYYMMDD

    Returns:
        包含所有执行指令的字典
    """
    controller = AIExecutionController(target_date)

    return {
        "target_date": target_date,
        "formatted_date": controller.formatted_date,
        "data_window": f"{controller.start_date} 至 {controller.formatted_date}",
        "output_file": controller.report_filename,
        "execution_phases": controller.get_execution_sequence(),
        "ai_prompt": controller.get_ai_prompt_template()
    }

# AI可以直接调用的快速执行函数
def execute_background_scan_report(target_date: str):
    """
    AI执行背景扫描报告生成的主函数

    Usage for AI:
        target_date = "20250918"  # 从用户指令中提取
        instructions = execute_background_scan_report(target_date)
        # 然后按instructions["execution_phases"]逐阶段执行
    """
    return get_ai_execution_instructions(target_date)

if __name__ == "__main__":
    # 示例：生成20250918的执行指令
    instructions = execute_background_scan_report("20250918")
    print("AI执行指令生成完成")
    print(f"目标日期: {instructions['target_date']}")
    print(f"数据窗口: {instructions['data_window']}")
    print(f"执行阶段数: {len(instructions['execution_phases'])}")
