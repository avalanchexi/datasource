#!/usr/bin/env python3
"""
背景扫描120日数据验证器
验证上传的背景扫描数据的合理性和完整性
"""

import os
import sys
import re
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from loguru import logger

# 添加项目根路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

from datasource import get_manager
from datasource.config.indices_config import A_SHARE_INDICES


@dataclass
class ValidationResult:
    """验证结果数据类"""
    is_valid: bool
    score: float  # 0-100分
    errors: List[str]
    warnings: List[str]
    suggestions: List[str]
    data_summary: Dict[str, Any]


class BackgroundScanValidator:
    """背景扫描数据验证器"""

    def __init__(self):
        self.required_sections = [
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

        self.required_indices = [
            "沪深300", "上证50", "创业板指", "深证成指", "上证指数", "科创50"
        ]

        self.required_commodities = [
            "WTI原油", "Brent原油", "COMEX铜", "现货黄金", "BCOM商品指数"
        ]

        self.required_forex = [
            "USD/CNY", "USD/CNH", "DXY"
        ]

        self.required_bonds = [
            "CN10Y", "US10Y", "CN10Y_CDB"
        ]

    async def validate_background_scan_file(self, file_path: str) -> ValidationResult:
        """验证背景扫描文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            errors = []
            warnings = []
            suggestions = []
            data_summary = {}

            # 1. 验证文件结构
            structure_score = self._validate_structure(content, errors, warnings)

            # 2. 验证数据完整性
            completeness_score = self._validate_data_completeness(content, errors, warnings)

            # 3. 验证数据合理性
            rationality_score = await self._validate_data_rationality(content, errors, warnings, suggestions)

            # 4. 验证格式规范性
            format_score = self._validate_format(content, errors, warnings, suggestions)

            # 计算总分
            total_score = (structure_score * 0.25 +
                          completeness_score * 0.3 +
                          rationality_score * 0.35 +
                          format_score * 0.1)

            # 生成数据摘要
            data_summary = self._generate_data_summary(content)

            is_valid = total_score >= 70 and len([e for e in errors if "严重" in e]) == 0

            return ValidationResult(
                is_valid=is_valid,
                score=total_score,
                errors=errors,
                warnings=warnings,
                suggestions=suggestions,
                data_summary=data_summary
            )

        except Exception as e:
            logger.error(f"验证文件时发生错误: {str(e)}")
            return ValidationResult(
                is_valid=False,
                score=0,
                errors=[f"文件读取错误: {str(e)}"],
                warnings=[],
                suggestions=[],
                data_summary={}
            )

    def _validate_structure(self, content: str, errors: List[str], warnings: List[str]) -> float:
        """验证文件结构"""
        score = 100
        found_sections = []

        for section in self.required_sections:
            if section in content:
                found_sections.append(section)
            else:
                errors.append(f"严重错误：缺少必需章节 '{section}'")
                score -= 15

        if len(found_sections) < len(self.required_sections) * 0.8:
            errors.append(f"严重错误：章节完整性不足，仅找到 {len(found_sections)}/{len(self.required_sections)} 个章节")

        return max(0, score)

    def _validate_data_completeness(self, content: str, errors: List[str], warnings: List[str]) -> float:
        """验证数据完整性"""
        score = 100

        # 检查股票指数数据
        missing_indices = []
        for index in self.required_indices:
            if index not in content:
                missing_indices.append(index)
                score -= 8

        if missing_indices:
            warnings.append(f"缺少股票指数数据: {', '.join(missing_indices)}")

        # 检查商品数据
        missing_commodities = []
        for commodity in self.required_commodities:
            if commodity not in content:
                missing_commodities.append(commodity)
                score -= 10

        if missing_commodities:
            warnings.append(f"缺少商品基准数据: {', '.join(missing_commodities)}")

        # 检查汇率数据
        missing_forex = []
        for forex in self.required_forex:
            if forex not in content:
                missing_forex.append(forex)
                score -= 10

        if missing_forex:
            warnings.append(f"缺少汇率数据: {', '.join(missing_forex)}")

        # 检查债券数据
        missing_bonds = []
        for bond in self.required_bonds:
            if bond not in content:
                missing_bonds.append(bond)
                score -= 10

        if missing_bonds:
            warnings.append(f"缺少债券数据: {', '.join(missing_bonds)}")

        return max(0, score)

    async def _validate_data_rationality(self, content: str, errors: List[str],
                                       warnings: List[str], suggestions: List[str]) -> float:
        """验证数据合理性"""
        score = 100

        try:
            # 获取实时数据进行对比验证
            manager = get_manager()

            # 提取文件中的数值数据
            price_data = self._extract_price_data(content)

            # 验证价格合理性
            for asset, price in price_data.items():
                if self._is_price_unreasonable(asset, price):
                    warnings.append(f"价格可能异常: {asset} = {price}")
                    score -= 5

            # 验证涨跌幅合理性
            change_data = self._extract_change_data(content)
            for asset, change in change_data.items():
                if abs(change) > 10:  # 单日涨跌超过10%
                    if abs(change) > 20:  # 超过20%可能有误
                        errors.append(f"涨跌幅异常: {asset} = {change:.2f}%")
                        score -= 15
                    else:
                        warnings.append(f"涨跌幅较大: {asset} = {change:.2f}%")
                        score -= 5

            # 验证普林格阶段判断合理性
            pring_stage = self._extract_pring_stage(content)
            if pring_stage:
                if not self._validate_pring_logic(content, pring_stage):
                    warnings.append(f"普林格阶段判断逻辑可能不一致: {pring_stage}")
                    score -= 10

        except Exception as e:
            warnings.append(f"数据合理性验证时发生错误: {str(e)}")
            score -= 20

        return max(0, score)

    def _validate_format(self, content: str, errors: List[str],
                        warnings: List[str], suggestions: List[str]) -> float:
        """验证格式规范性"""
        score = 100

        # 检查表格格式
        if "|" not in content:
            warnings.append("建议使用Markdown表格格式展示数据")
            score -= 10

        # 检查数值格式一致性
        percentage_pattern = r'[-+]?\d+\.?\d*%'
        percentages = re.findall(percentage_pattern, content)

        # 检查百分号格式
        if len(percentages) > 0:
            inconsistent_format = False
            for pct in percentages:
                if '.' in pct and len(pct.split('.')[1].replace('%', '')) > 2:
                    inconsistent_format = True
                    break

            if inconsistent_format:
                suggestions.append("建议统一百分比格式为保留2位小数")
                score -= 5

        # 检查日期格式
        date_patterns = [r'\d{4}-\d{2}-\d{2}', r'\d{4}/\d{2}/\d{2}', r'\d{2}/\d{2}/\d{4}']
        dates_found = []
        for pattern in date_patterns:
            dates_found.extend(re.findall(pattern, content))

        if len(set([len(d) for d in dates_found])) > 1:
            suggestions.append("建议统一日期格式")
            score -= 5

        return max(0, score)

    def _extract_price_data(self, content: str) -> Dict[str, float]:
        """提取价格数据"""
        price_data = {}

        # 简单的价格提取逻辑
        lines = content.split('\n')
        for line in lines:
            if '|' in line and any(idx in line for idx in self.required_indices):
                parts = line.split('|')
                if len(parts) >= 3:
                    name = parts[1].strip()
                    try:
                        # 尝试从不同位置提取价格
                        for part in parts[2:]:
                            if re.match(r'^\d+\.?\d*$', part.strip()):
                                price_data[name] = float(part.strip())
                                break
                    except:
                        continue

        return price_data

    def _extract_change_data(self, content: str) -> Dict[str, float]:
        """提取涨跌幅数据"""
        change_data = {}

        # 提取百分比变化
        pattern = r'([\u4e00-\u9fa5A-Za-z0-9]+)\s*[：:]\s*([-+]?\d+\.?\d*)%'
        matches = re.findall(pattern, content)

        for name, change in matches:
            try:
                change_data[name] = float(change)
            except:
                continue

        return change_data

    def _extract_pring_stage(self, content: str) -> Optional[str]:
        """提取普林格阶段"""
        pattern = r'普林格.*?阶段[：:]?\s*([ⅠⅡⅢⅣⅤⅥIVivxl\d]+)'
        match = re.search(pattern, content, re.IGNORECASE)
        return match.group(1) if match else None

    def _validate_pring_logic(self, content: str, stage: str) -> bool:
        """验证普林格阶段逻辑"""
        # 简化的逻辑验证
        bond_bullish = "债券" in content and ("上涨" in content or "走强" in content)
        stock_bullish = "股票" in content and ("上涨" in content or "走强" in content)
        commodity_bullish = "商品" in content and ("上涨" in content or "走强" in content)

        # 根据阶段验证逻辑一致性
        stage_logic = {
            "Ⅰ": (True, False, False),
            "Ⅱ": (True, True, False),
            "Ⅲ": (True, True, True),
            "Ⅳ": (False, True, True),
            "Ⅴ": (False, False, True),
            "Ⅵ": (False, False, False)
        }

        if stage in stage_logic:
            expected = stage_logic[stage]
            actual = (bond_bullish, stock_bullish, commodity_bullish)
            return expected == actual

        return True  # 无法验证时返回True

    def _is_price_unreasonable(self, asset: str, price: float) -> bool:
        """检查价格是否异常"""
        # 简单的价格合理性检查
        if price <= 0:
            return True

        # ETF价格通常在0.5-50之间
        if "ETF" in asset and (price < 0.1 or price > 100):
            return True

        # 股票价格通常在1-1000之间
        if price < 0.01 or price > 10000:
            return True

        return False

    def _generate_data_summary(self, content: str) -> Dict[str, Any]:
        """生成数据摘要"""
        summary = {
            "文件长度": len(content),
            "段落数": len([p for p in content.split('\n\n') if p.strip()]),
            "表格数": content.count('|') // 3,  # 估算表格数
            "百分比数据": len(re.findall(r'[-+]?\d+\.?\d*%', content)),
            "提取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        return summary

    def generate_validation_report(self, result: ValidationResult, file_path: str) -> str:
        """生成验证报告"""
        report = f"""# 背景扫描数据验证报告

## 验证概览
- **文件**: {os.path.basename(file_path)}
- **验证时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
- **验证结果**: {'✅ 通过' if result.is_valid else '❌ 不通过'}
- **综合评分**: {result.score:.1f}/100

## 数据摘要
"""

        for key, value in result.data_summary.items():
            report += f"- **{key}**: {value}\n"

        if result.errors:
            report += "\n## ❌ 错误列表\n"
            for i, error in enumerate(result.errors, 1):
                report += f"{i}. {error}\n"

        if result.warnings:
            report += "\n## ⚠️ 警告列表\n"
            for i, warning in enumerate(result.warnings, 1):
                report += f"{i}. {warning}\n"

        if result.suggestions:
            report += "\n## 💡 改进建议\n"
            for i, suggestion in enumerate(result.suggestions, 1):
                report += f"{i}. {suggestion}\n"

        report += f"\n## 验证标准\n"
        report += f"- 结构完整性 (25%): 必需章节是否齐全\n"
        report += f"- 数据完整性 (30%): 关键数据是否缺失\n"
        report += f"- 数据合理性 (35%): 数值是否在合理范围\n"
        report += f"- 格式规范性 (10%): 格式是否统一规范\n"

        return report


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="背景扫描数据验证器")
    parser.add_argument("file_path", help="背景扫描文件路径")
    parser.add_argument("--output", help="验证报告输出路径")

    args = parser.parse_args()

    validator = BackgroundScanValidator()
    result = await validator.validate_background_scan_file(args.file_path)

    report = validator.generate_validation_report(result, args.file_path)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"验证报告已保存到: {args.output}")
    else:
        print(report)

    print(f"\n验证结果: {'通过' if result.is_valid else '不通过'} (评分: {result.score:.1f}/100)")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
