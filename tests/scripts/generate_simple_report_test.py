#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
简单报告生成器 - 测试版
基于market_data和pring_result生成Markdown报告
"""

import json
import sys
from pathlib import Path
from datetime import datetime

NA_TEXT = "N/A（待 WebSearch）"

def generate_report(market_data_path, pring_result_path, output_path):
    """生成背景扫描120日报告"""

    # 读取数据
    with open(market_data_path, 'r', encoding='utf-8') as f:
        market_data = json.load(f)

    with open(pring_result_path, 'r', encoding='utf-8') as f:
        pring_result = json.load(f)

    # 生成报告
    report_date = market_data['metadata']['date']
    completeness = market_data['metadata']['data_completeness']

    report = f"""# A股背景扫描120日报告

**报告日期**: {report_date}
**数据完整性**: {completeness:.1%}
**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 一、核心结论

**Pring六阶段判定**: {pring_result['final_stage']}
**置信度**: {pring_result['confidence']:.1%}
**投资建议**: {pring_result['recommendation']}

---

## 二、股票市场

### 主要指数表现

| 指数 | 最新点位 | 近5日涨跌 | 近120日涨跌 | MA50趋势 | MA200趋势 | 趋势评级 |
|------|----------|-----------|-------------|----------|-----------|----------|
"""

    # 添加股票指数数据
    for idx in market_data['stock_indices']:
        above_ma50 = "向上" if idx['above_ma50'] else "向下"
        above_ma200 = "向上" if idx['above_ma200'] else "向下"
        report += f"| {idx['name']} | {idx['current_price']:.2f} | {idx['change_5d']:+.2f}% | {idx['change_120d']:+.1f}% | {above_ma50} | {above_ma200} | {idx['trend_label']} |\n"

    report += """

---

## 三、商品与黄金

| 品种 | 最新报价 | 日涨跌 | 年内涨跌 | 趋势方向 |
|------|----------|--------|----------|----------|
"""

    # 添加商品数据
    for comm in market_data['commodities']:
        # 检查是否为占位数据（0.0或source包含"待获取"）
        current_price = comm.get('current_price')
        is_placeholder = (
            current_price in (None, 0.0) or
            '待获取' in comm.get('source', '') or
            '待MCP' in comm.get('trend', '')
        )

        if is_placeholder:
            latest_price = NA_TEXT
            daily_change = "N/A"
            ytd_change = "N/A"
            trend = "待 WebSearch"
        else:
            latest_price = f"{comm['unit']} {current_price:.2f}".strip()
            daily_change = f"{comm['daily_change']:+.2f}%"
            ytd_change = f"{comm['ytd_change']:+.2f}%"
            trend = comm['trend']

        report += f"| {comm['name']} | {latest_price} | {daily_change} | {ytd_change} | {trend} |\n"

    report += """

---

## 四、债券市场

| 债券品种 | 当前收益率 | 近5日变化 | 近120日变化 | 趋势方向 |
|----------|-----------|----------|-------------|----------|
"""

    # 添加债券数据
    for bond in market_data['bonds']:
        # 检查是否为占位数据（0.0或source包含"待获取"或is_estimated=True）
        current_yield = bond.get('current_yield')
        is_placeholder = (
            current_yield in (None, 0.0) or
            '待获取' in bond.get('source', '') or
            bond.get('is_estimated', False) or
            '待MCP' in bond.get('trend', '')
        )

        if is_placeholder:
            yield_str = NA_TEXT
            bp5_str = "N/A"
            bp120_str = "N/A"
            trend = "待 WebSearch"
        else:
            yield_str = f"{current_yield:.2f}%"
            bp5 = bond.get('change_5d_bp', 0) or 0
            bp120 = bond.get('change_120d_bp', 0) or 0
            bp5_str = f"{bp5:+.1f}bp"
            bp120_str = f"{bp120:+.1f}bp"
            trend = bond['trend']

        report += f"| {bond['name']} | {yield_str} | {bp5_str} | {bp120_str} | {trend} |\n"

    report += """

---

## 五、外汇市场

| 货币对 | 当前汇率 | 日涨跌 | 近120日变化 | 趋势方向 |
|--------|---------|--------|-------------|----------|
"""

    # 添加外汇数据
    for forex in market_data['forex']:
        report += f"| {forex['name']} | {forex['current_rate']:.4f} | {forex['daily_change']:+.2f}% | {forex['change_120d']:+.2f}% | {forex['trend']} |\n"

    report += """

---

## 六、宏观经济指标

| 指标 | 当前值 | 前值 | 变化 | 单位 | 日期 |
|------|--------|------|------|------|------|
"""

    # 添加宏观指标
    for key, indicator in market_data['macro_indicators'].items():
        curr = indicator.get('current_value', 'N/A')
        prev = indicator.get('previous_value', 'N/A')
        change = indicator.get('change_rate', 'N/A')
        unit = indicator.get('unit', '')
        date = indicator.get('date', '')

        is_placeholder = indicator.get('is_estimated') or '待MCP' in indicator.get('source', '')
        if curr is None or is_placeholder:
            curr_str = NA_TEXT
        else:
            curr_str = f"{curr}{unit}"
        if prev is None or is_placeholder:
            prev_str = NA_TEXT
        else:
            prev_str = f"{prev}{unit}"
        if change != 'N/A' and change is not None and not is_placeholder:
            suffix = 'pp' if unit == '%' else unit
            change_str = f"{change:+.1f}{suffix}"
        else:
            change_str = NA_TEXT if is_placeholder else 'N/A'

        report += f"| {indicator['indicator_name']} | {curr_str} | {prev_str} | {change_str} | {unit} | {date} |\n"

    report += """

---

## 七、货币政策

| 政策工具 | 当前值 | 120日变化 | 单位 | 更新日期 |
|----------|--------|-----------|------|----------|
"""

    # 添加货币政策
    for key, policy in market_data['monetary_policy'].items():
        curr = policy.get('current_value', 'N/A')
        change = policy.get('change_from_120d', 'N/A')
        unit = policy.get('unit', '')
        date = policy.get('date', '')

        is_placeholder = policy.get('is_estimated') or '待MCP' in policy.get('source', '')
        if curr is None or is_placeholder:
            curr_str = NA_TEXT
        else:
            curr_str = f"{curr}{unit}"
        if change is None or is_placeholder:
            change_str = NA_TEXT
        else:
            change_str = f"{change:+.1f}pp"

        report += f"| {policy['policy_name']} | {curr_str} | {change_str} | {unit} | {date} |\n"

    leading_summary = pring_result.get('leading_summary')
    if not leading_summary:
        leading_indicator = pring_result.get('leading_indicator') or {}
        status = leading_indicator.get('status')
        bp_change = leading_indicator.get('bp_change')
        lead_days = leading_indicator.get('lead_days')
        shift = leading_indicator.get('applied_shift', 0)
        direction = leading_indicator.get('direction')

        if status == 'ok':
            dir_text = "宽松" if direction == 'easing' else "收紧"
            shift_text = ""
            if shift:
                arrow = "前" if shift < 0 else "后"
                shift_text = f"，阶段预计向{arrow}{abs(shift)}档"
            bp_text = f"{bp_change:+.0f}bp" if bp_change is not None else "未知bp"
            lead_text = f"{lead_days}天" if lead_days is not None else "数十天"
            leading_summary = f"DR007出现{dir_text}信号（{bp_text}，领先期约{lead_text}{shift_text}）"
            if leading_indicator.get('message'):
                leading_summary += f"，{leading_indicator['message']}"
        elif status == 'flat':
            leading_summary = leading_indicator.get('message', 'DR007变化有限，领先指标保持中性')
        elif status == 'missing':
            leading_summary = "缺少DR007/逆回购原始数据，需补充WebSearch"
        else:
            leading_summary = leading_indicator.get('message', '暂无领先指标结论')

    focus_assets = pring_result.get('focus_assets') or []
    focus_assets_summary = "、".join(focus_assets) if focus_assets else "未提供（请检查Pring结果）"

    layer1 = pring_result.get('layer_1_inventory_cycle', {})
    layer2 = pring_result.get('layer_2_monetary_cycle', {})
    layer3 = pring_result.get('layer_3_pring_final', {})
    analysis1 = layer1.get('analysis', '（暂无详细解析，待MCP补充）')
    analysis2 = layer2.get('analysis', '（暂无详细解析，待MCP补充）')
    analysis3 = layer3.get('analysis', '（暂无详细解析，待MCP补充）')

    report += """

---

## 八、Pring三层框架分析

### Layer 1：库存周期
- **基本面得分**: {score1}/60
- **周期阶段**: {stage1}
- **商品偏向**: {comm_bias}
- **诊断摘要**: {analysis1}

### Layer 2：货币周期
- **货币宽松度**: {score2}/100
- **周期阶段**: {stage2}
- **权益/债券偏向**: {equity_bias} / {bond_bias}
- **诊断摘要**: {analysis2}

### Layer 3：Pring最终判定
- **基础阶段 → 最终阶段**: {base_stage} → {final_stage}
- **置信度**: {confidence:.1%}
- **DR007领先指标**: {leading_summary}
- **阶段关注资产**: {focus_assets_summary}
- **诊断摘要**: {analysis3}

---

    ## 九、资金流向

| 类别 | 近5日(亿元) | 近120日(亿元) | 趋势 | 来源 | 备注 |
|------|-------------|----------------|------|------|------|
""".format(
        score1=layer1.get('fundamental_score', 0),
        stage1=layer1.get('cycle_stage', '未知'),
        comm_bias=layer1.get('commodity_bias', '未知'),
        analysis1=analysis1,
        score2=layer2.get('monetary_score', 0),
        stage2=layer2.get('cycle_stage', '未知'),
        equity_bias=layer2.get('equity_bias', '未知'),
        bond_bias=layer2.get('bond_bias', '未知'),
        analysis2=analysis2,
        base_stage=layer3.get('base_stage', 'N/A'),
        final_stage=layer3.get('final_stage', 'N/A'),
        confidence=pring_result.get('confidence', 0.0),
        analysis3=analysis3,
        leading_summary=leading_summary,
        focus_assets_summary=focus_assets_summary
    )

    # 添加资金流向
    def _format_flow_amount(value):
        if isinstance(value, (int, float)):
            return f"{value:.2f}"
        return 'N/A'

    for key, flow in market_data['fund_flow'].items():
        report += (
            f"| {key} | {_format_flow_amount(flow.get('recent_5d'))} | "
            f"{_format_flow_amount(flow.get('total_120d'))} | {flow.get('trend', 'N/A')} | "
            f"{flow.get('source', '-')} | {flow.get('note', '-') or '-'} |\n"
        )

    report += f"""

---

## 附录：数据来源

- **API数据源**: TuShare, International Finance
- **MCP增强**: WebSearch (债券、商品、宏观、货币、资金流向)
- **数据完整性**: {completeness:.1%}
- **分析方法**: {pring_result['metadata']['analysis_method']}

---

**免责声明**: 本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。
"""

    # 保存报告
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"[SUCCESS] 报告生成完成！")
    print(f"  - 输出文件: {output_path}")
    print(f"  - 报告日期: {report_date}")
    print(f"  - 数据完整性: {completeness:.1%}")
    print(f"  - Pring阶段: {pring_result['final_stage']}")
    print(f"  - 置信度: {pring_result['confidence']:.1%}")

if __name__ == '__main__':
    # 默认路径
    market_data_file = Path('data/20251117_market_data_complete.json')
    pring_result_file = Path('data/20251117_pring_result_leading.json')
    output_file = Path('reports/20251117背景扫描120_测试版.md')

    if len(sys.argv) > 1:
        market_data_file = Path(sys.argv[1])
    if len(sys.argv) > 2:
        pring_result_file = Path(sys.argv[2])
    if len(sys.argv) > 3:
        output_file = Path(sys.argv[3])

    generate_report(market_data_file, pring_result_file, output_file)
