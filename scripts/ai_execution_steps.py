#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI背景扫描报告执行步骤脚本
用于AI按标准化流程生成背景扫描报告
"""

EXECUTION_PHASES = {
    "PHASE_1_SETUP": {
        "name": "环境准备与验证",
        "duration_minutes": 5,
        "tasks": [
            {
                "task": "创建Todo任务追踪",
                "action": "使用TodoWrite工具创建5个阶段的任务列表",
                "expected_output": "Todo列表包含5个主要阶段任务"
            },
            {
                "task": "验证项目环境",
                "action": "检查.env文件、项目结构、Python依赖",
                "bash_commands": [
                    "ls -la .env",
                    "ls scripts/utility/background_scan_120d_generator.py",
                    "python -c \"from datasource import get_manager; print('DataSource OK')\""
                ],
                "expected_output": "环境配置正常，数据源可用"
            }
        ]
    },

    "PHASE_2_DATA_COLLECTION": {
        "name": "数据收集与计算",
        "duration_minutes": 15,
        "tasks": [
            {
                "task": "计算数据窗口",
                "action": "根据目标日期计算120日窗口起始日期",
                "formula": "start_date = target_date - 120天"
            },
            {
                "task": "更新脚本配置",
                "action": "使用Edit工具修改background_scan_120d_generator.py中的日期配置",
                "file_edits": [
                    "self.end_date = \"目标日期\"",
                    "self.start_date = \"起始日期\"",
                    "report_filename = f\"reports/{目标日期}背景扫描120.md\""
                ]
            },
            {
                "task": "执行数据收集",
                "action": "运行背景扫描生成器脚本",
                "bash_commands": [
                    "python scripts/utility/background_scan_120d_generator.py"
                ],
                "expected_output": "生成初始报告文件到reports/目录"
            }
        ]
    },

    "PHASE_3_DATA_COMPLETION": {
        "name": "缺失数据补充",
        "duration_minutes": 20,
        "tasks": [
            {
                "task": "分析N/A值",
                "action": "读取生成的报告，识别所有N/A和缺失数据",
                "scan_patterns": ["N/A", "数据获取中", "数据接入中"]
            },
            {
                "task": "补充股票指数数据",
                "action": "使用WebSearch和WebFetch获取缺失的股票指数数据",
                "data_sources": [
                    "cn.investing.com - 沪深300指数",
                    "cn.investing.com - 黄金ETF数据"
                ]
            },
            {
                "task": "补充汇率数据",
                "action": "获取USD/CNY、美元指数等汇率数据",
                "data_sources": [
                    "cn.investing.com/currencies/usd-cny",
                    "cn.investing.com/indices/usdollar"
                ]
            },
            {
                "task": "补充债券收益率",
                "action": "获取中美10年期国债收益率数据",
                "data_sources": [
                    "investing.com/rates-bonds/china-10-year-bond-yield",
                    "investing.com/rates-bonds/u.s.-10-year-bond-yield"
                ]
            },
            {
                "task": "补充资金流向数据",
                "action": "获取北向资金、融资融券等数据",
                "data_sources": [
                    "data.eastmoney.com/hsgt/",
                    "融资融券余额相关新闻"
                ]
            },
            {
                "task": "收集财经要闻",
                "action": "获取当日重要财经新闻",
                "data_sources": [
                    "wallstreetcn.com",
                    "WebSearch当日财经要闻"
                ]
            }
        ]
    },

    "PHASE_4_REPORT_ENHANCEMENT": {
        "name": "报告优化与完善",
        "duration_minutes": 10,
        "tasks": [
            {
                "task": "批量更新报告内容",
                "action": "使用MultiEdit工具批量替换N/A值和补充数据",
                "edit_sections": [
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
                "task": "完善市场结论",
                "action": "基于收集的数据生成3-6条核心市场观点",
                "format": "- 过去120天，XXX指数表现，趋势评级\n- 汇率/债券/资金流向关键变化"
            },
            {
                "task": "格式规范化",
                "action": "确保数值格式符合标准",
                "standards": {
                    "百分比": "保留1位小数，如-2.4%",
                    "基点": "保留1位小数，如+15.0bp",
                    "价格": "保留2位小数，如3156.78",
                    "斜率": "保留4位小数，如+0.1234"
                }
            }
        ]
    },

    "PHASE_5_QUALITY_CHECK": {
        "name": "质量验证与交付",
        "duration_minutes": 5,
        "tasks": [
            {
                "task": "结构完整性检查",
                "action": "验证报告包含所有必需章节",
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
                "task": "数据质量验证",
                "action": "检查表格数据完整性和准确性",
                "validation_rules": [
                    "表格无N/A值",
                    "数值格式正确",
                    "时间戳准确",
                    "数据源引用完整"
                ]
            },
            {
                "task": "合规性检查",
                "action": "确认包含必要的免责声明",
                "required_statements": [
                    "本报告仅供研究与教学参考",
                    "不构成任何投资建议",
                    "投资有风险，决策需谨慎"
                ]
            },
            {
                "task": "生成执行总结",
                "action": "更新Todo状态为完成，提供交付信息",
                "summary_format": "📊 报告生成完成！\n📁 文件路径: reports/YYYYMMDD背景扫描120.md\n📈 核心发现: [关键观点摘要]"
            }
        ]
    }
}

# AI执行标准指令格式
AI_EXECUTION_COMMANDS = {
    "standard_trigger": "执行背景扫描报告生成：YYYYMMDD",
    "examples": [
        "执行背景扫描报告生成：20250918",
        "执行背景扫描报告生成：20251225",
        "执行背景扫描报告生成：20260315"
    ]
}

# 数据源优先级配置
DATA_SOURCE_PRIORITY = {
    "股票数据": ["AKShare", "TuShare", "WebSearch"],
    "汇率数据": ["investing.com", "央行官网", "WebSearch"],
    "债券数据": ["investing.com", "中债网", "WebSearch"],
    "资金流向": ["东方财富网", "交易所数据", "WebSearch"],
    "财经要闻": ["华尔街见闻", "新浪财经", "WebSearch"]
}

# 质量检查清单
QUALITY_CHECKLIST = {
    "结构完整性": [
        "包含9个标准章节",
        "表格格式正确",
        "Markdown语法无误"
    ],
    "数据完整性": [
        "无N/A值",
        "数值格式标准",
        "时间戳准确"
    ],
    "内容质量": [
        "市场结论3-6条",
        "财经要闻5-10条",
        "数据源可追溯"
    ],
    "合规性": [
        "包含免责声明",
        "无投资建议表述",
        "客观中立描述"
    ]
}

if __name__ == "__main__":
    print("AI背景扫描报告执行步骤配置")
    print(f"共{len(EXECUTION_PHASES)}个执行阶段")

    total_time = sum(phase["duration_minutes"] for phase in EXECUTION_PHASES.values())
    print(f"预期总执行时间: {total_time}分钟")

    for phase_id, phase in EXECUTION_PHASES.items():
        print(f"\n{phase_id}: {phase['name']} ({phase['duration_minutes']}分钟)")
        print(f"  包含{len(phase['tasks'])}个任务")