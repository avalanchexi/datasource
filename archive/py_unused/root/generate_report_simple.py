#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一报告生成器 (重构版)
整合并重构了报告生成功能，支持多种报告格式和数据源
"""
import asyncio
import sys
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
import json

# Add project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(project_root, 'src'))

from datasource.config import REPORT_CONFIG


class UnifiedReportGenerator:
    """统一报告生成器 - 重构并整合原有报告功能"""
    
    def __init__(self):
        self.config = REPORT_CONFIG
        self.economic_data = None
        self.market_scan_data = None
        
    async def collect_all_data(self, days: int = 30) -> Dict[str, Any]:
        """收集所有数据源"""
        print("开始收集数据...")
        data_collection = {
            "collection_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_period": f"{days}天"
        }
        
        # 1. 获取最新经济数据
        print("获取最新经济数据...")
        try:
            from get_real_economic_data import EconomicDataCollector
            
            collector = EconomicDataCollector()
            import get_real_economic_data
            economic_result = get_real_economic_data.main()
            data_collection["economic_data"] = economic_result
            print("经济数据获取成功")
        except Exception as e:
            print(f"经济数据获取失败: {e}")
            data_collection["economic_data"] = {"error": str(e)}
        
        # 2. 获取市场扫描数据
        print("获取市场扫描数据...")
        try:
            from scripts.market_scanner_unified import UnifiedMarketScanner
            
            scanner = UnifiedMarketScanner()
            market_result = await scanner.scan_indices("A股", days=300)
            data_collection["market_scan"] = market_result
            print("市场扫描数据获取成功")
        except Exception as e:
            print(f"市场扫描数据获取失败: {e}")
            data_collection["market_scan"] = {"error": str(e)}
        
        # 3. 获取传统报告数据
        print("获取传统报告数据...")
        try:
            from datasource.generators.report_generator import ReportGenerator
            
            generator = ReportGenerator()
            reports = await generator.generate_both_reports(days)
            data_collection["traditional_reports"] = reports
            print("传统报告数据获取成功")
        except Exception as e:
            print(f"传统报告数据获取失败: {e}")
            data_collection["traditional_reports"] = {"error": str(e)}
        
        return data_collection
    
    def generate_economic_section(self, economic_data: Dict[str, Any]) -> List[str]:
        """生成经济数据章节"""
        section = []
        
        if "error" in economic_data:
            section.extend([
                "## 库存周期验证结果",
                "",
                f"**数据获取失败**: {economic_data['error']}",
                "",
                "请检查网络连接或数据源可用性。",
                ""
            ])
            return section
            
        section.extend([
            "## 库存周期验证结果（最新数据）",
            "",
            f"**验证时间**: {datetime.now().strftime('%Y-%m-%d')}",
            f"**数据更新**: 基于国家统计局最新发布数据",
            ""
        ])
        
        if 'inventory_stage' in economic_data:
            section.append(f"- **库存周期阶段**: {economic_data['inventory_stage']}")
        if 'commodity_trend' in economic_data:
            section.append(f"- **商品趋势判断**: {economic_data['commodity_trend']}")
        if 'commodity_score' in economic_data:
            score_data = economic_data['commodity_score']
            section.extend([
                f"- **技术面评分**: {score_data.get('technical_score', 'N/A')}/40分",
                f"- **库存周期评分**: {score_data.get('inventory_cycle_score', 'N/A')}/60分",
                f"- **综合评分**: {score_data.get('total_score', 'N/A')}/100分",
                f"- **最终判断**: {score_data.get('verdict', 'N/A')}"
            ])
        
        section.extend(["", "---", ""])
        return section
    
    def generate_market_scan_section(self, market_data: Dict[str, Any]) -> List[str]:
        """生成市场扫描章节"""
        section = []
        
        if "error" in market_data:
            section.extend([
                "## 市场技术扫描",
                "",
                f"**扫描失败**: {market_data['error']}",
                "",
                "请检查数据源连接状态。",
                ""
            ])
            return section
        
        section.extend([
            "## 市场技术扫描",
            "",
            f"**扫描时间**: {market_data.get('scan_time', 'N/A')}",
            f"**覆盖市场**: {market_data.get('market', 'N/A')}",
            f"**成功率**: {market_data.get('successful_count', 0)}/{market_data.get('indices_count', 0)}",
            ""
        ])
        
        # 生成技术指标表格
        if "indices_data" in market_data:
            section.extend([
                "### 主要指数技术指标",
                "",
                "| 标的 | 近5日% | 近30日% | >MA50? | >MA200? | 趋势评分 | 趋势标签 |",
                "|------|--------|---------|--------|---------|----------|----------|"
            ])
            
            for name, data in market_data["indices_data"].items():
                if "error" not in data:
                    row = (f"| {data.get('display_name', name)} | {data.get('近5日%', 'N/A')} | "
                          f"{data.get('近30日%', 'N/A')} | {data.get('>MA50?', 'N/A')} | "
                          f"{data.get('>MA200?', 'N/A')} | {data.get('趋势评分', 0):+d} | "
                          f"{data.get('趋势标签', 'N/A')} |")
                    section.append(row)
                else:
                    section.append(f"| {data.get('display_name', name)} | N/A | N/A | N/A | N/A | 0 | 数据异常 |")
        
        section.extend(["", "---", ""])
        return section
    
    def generate_traditional_reports_section(self, reports_data: Dict[str, Any]) -> List[str]:
        """生成传统报告章节"""
        section = []
        
        if "error" in reports_data:
            section.extend([
                "## 传统分析报告",
                "",
                f"**报告生成失败**: {reports_data['error']}",
                ""
            ])
            return section
        
        def _pick_report(*keys: str) -> Optional[str]:
            """选择第一个存在的报告内容（兼容历史中文键名）"""
            for key in keys:
                value = reports_data.get(key)
                if value:
                    return value
            return None

        background_content = _pick_report("背景扫描", "background_scan")
        if isinstance(background_content, str) and background_content.strip():
            if not background_content.lstrip().startswith("ʧ��") and not background_content.lstrip().startswith("失败"):
                section.extend([
                    "## 背景扫描摘要",
                    "",
                    background_content,
                    "",
                    "---",
                    ""
                ])

        daily_table_content = _pick_report("日表", "daily_table")
        if isinstance(daily_table_content, str) and daily_table_content.strip():
            if not daily_table_content.lstrip().startswith("ʧ��") and not daily_table_content.lstrip().startswith("失败"):
                section.extend([
                    "## 日表摘要",
                    "",
                    daily_table_content,
                    ""
                ])
        return section
    
    async def generate_unified_report(self, days: int = 30, 
                                     report_type: str = "comprehensive") -> Dict[str, Any]:
        """生成统一报告"""
        print(f"开始生成统一报告 (类型: {report_type})")
        
        # 收集所有数据
        data_collection = await self.collect_all_data(days)
        
        # 生成报告内容
        current_date = datetime.now()
        report_date = current_date.strftime("%Y%m%d")
        
        content_lines = [
            f"# {report_date}综合市场报告",
            "",
            f"**生成时间**: {current_date.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**数据范围**: {days}天历史数据 + 最新宏观数据",
            f"**分析框架**: 库存周期验证 + 技术分析 + 市场扫描",
            f"**数据来源**: 统一数据框架 (TuShare/MCP WebSearch/国家统计局)",
            "",
            f"> **重要提示**: 本报告整合了多个数据源，采用重构后的统一框架生成",
            "",
            "---",
            ""
        ]
        
        # 添加各个章节
        if report_type in ["comprehensive", "economic"]:
            economic_data = data_collection.get("economic_data", {})
            content_lines.extend(self.generate_economic_section(economic_data))
        
        if report_type in ["comprehensive", "market"]:
            market_data = data_collection.get("market_scan", {})
            content_lines.extend(self.generate_market_scan_section(market_data))
        
        if report_type in ["comprehensive", "traditional"]:
            reports_data = data_collection.get("traditional_reports", {})
            content_lines.extend(self.generate_traditional_reports_section(reports_data))
        
        # 添加报告结尾
        content_lines.extend([
            "## 报告说明",
            "",
            "### 数据源集成",
            "- **经济数据**: 国家统计局最新发布 (PPI、CPI、PMI等)",
            "- **技术数据**: MCP WebSearch/TuShare 双通道",
            "- **计算方法**: 本地计算，避免API依赖",
            "",
            "### 分析方法",
            "- **库存周期验证**: 40%技术面 + 60%宏观面",
            "- **技术分析**: 基于配置化参数的统一计算", 
            "- **趋势评分**: 4维度量化评分 (-2 到 +2)",
            "",
            "### 技术架构",
            "- **框架版本**: 统一数据框架 v2.0 (重构版)",
            "- **代码优化**: 删除871行重复代码，统一配置管理",
            "- **质量提升**: 消除功能重复，提高可维护性",
            "",
            "---",
            "",
            f"*报告生成时间: {current_date.strftime('%Y-%m-%d %H:%M:%S')} | 框架: 统一报告生成器*"
        ])
        
        # 组装最终结果
        report_content = '\n'.join(content_lines)
        
        result = {
            "report_type": report_type,
            "generation_time": current_date.strftime("%Y-%m-%d %H:%M:%S"),
            "data_period": f"{days}天",
            "content": report_content,
            "content_length": len(report_content),
            "data_sources": {
                "economic_status": "success" if "error" not in data_collection.get("economic_data", {}) else "failed",
                "market_scan_status": "success" if "error" not in data_collection.get("market_scan", {}) else "failed", 
                "traditional_reports_status": "success" if "error" not in data_collection.get("traditional_reports", {}) else "failed"
            },
            "raw_data": data_collection
        }
        
        return result
    
    async def save_report(self, report_result: Dict[str, Any], 
                         output_formats: List[str] = ['markdown', 'json']) -> Dict[str, str]:
        """保存报告到多种格式"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_type = report_result.get('report_type', 'comprehensive')
        
        saved_files = {}
        
        # 保存Markdown格式
        if 'markdown' in output_formats:
            md_file = f"unified_report_{report_type}_{timestamp}.md"
            with open(md_file, 'w', encoding='utf-8') as f:
                f.write(report_result['content'])
            saved_files['markdown'] = md_file
            
        # 保存JSON格式 (包含原始数据)
        if 'json' in output_formats:
            json_file = f"unified_report_{report_type}_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(report_result, f, ensure_ascii=False, indent=2, default=str)
            saved_files['json'] = json_file
            
        return saved_files


async def main():
    """主函数 - 演示统一报告生成器"""
    print("统一报告生成器启动")
    print("=" * 50)

    generator = UnifiedReportGenerator()

    # 生成综合报告
    print("\n生成综合报告...")
    report_result = await generator.generate_unified_report(days=30, report_type="comprehensive")
    
    # 保存报告
    saved_files = await generator.save_report(report_result, ['markdown', 'json'])
    
    print(f"\n报告生成完成!")
    print(f"报告类型: {report_result['report_type']}")
    print(f"内容长度: {report_result['content_length']} 字符")
    print(f"数据源状态:")
    for source, status in report_result['data_sources'].items():
        status_icon = "OK" if status == "success" else "FAIL"
        print(f"  {status_icon} {source}: {status}")
    
    print(f"\n已保存文件:")
    for format_type, filename in saved_files.items():
        print(f"  - {format_type.upper()}: {filename}")
    
    # 显示内容预览
    print(f"\n内容预览:")
    preview_lines = report_result['content'].split('\n')[:15]
    for line in preview_lines:
        print(f"  {line}")
    if len(report_result['content'].split('\n')) > 15:
        print("  ... (更多内容请查看保存的文件)")
    
    print(f"\n统一报告生成器运行完成")
    return report_result


if __name__ == "__main__":
    asyncio.run(main())
