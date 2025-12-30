"""简单报告生成器（正式版）

基于 market_data_complete.json 与 pring_result.json 生成 Markdown 报告。
原测试脚本已移至此处，供 Stage4 及 CLI 调用。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Any

NA_TEXT = "N/A（待 WebSearch）"


def generate_report(market_data_path: Path, pring_result_path: Path, output_path: Path) -> None:
    """生成背景扫描120日报告"""

    with open(market_data_path, 'r', encoding='utf-8') as f:
        market_data = json.load(f)

    with open(pring_result_path, 'r', encoding='utf-8') as f:
        pring_result = json.load(f)

    report_date = market_data['metadata']['date']
    completeness = market_data['metadata']['data_completeness']

    def _as_list(section: Any) -> list:
        """兼容 dict/list 结构，避免 Stage2.5 注入后的结构差异导致 N/A。"""
        if isinstance(section, dict):
            return list(section.values())
        return section or []

    stock_indices = _as_list(market_data.get('stock_indices', []))
    commodities = _as_list(market_data.get('commodities', []))
    bonds = _as_list(market_data.get('bonds', []))
    forex_list = _as_list(market_data.get('forex', []))

    def _collect_estimated_items() -> list[str]:
        items: list[str] = []
        for bond in bonds:
            if bond.get('is_estimated'):
                name = bond.get('name') or bond.get('symbol') or '债券'
                items.append(f"债券:{name}")
        for indicator in market_data.get('macro_indicators', {}).values():
            if indicator.get('is_estimated'):
                name = indicator.get('indicator_name') or '宏观指标'
                items.append(f"宏观:{name}")
        for policy in market_data.get('monetary_policy', {}).values():
            if policy.get('is_estimated'):
                name = policy.get('policy_name') or '货币政策'
                items.append(f"货币政策:{name}")
        return items

    estimated_items = _collect_estimated_items()

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
    for idx in stock_indices:
        above_ma50 = "向上" if idx['above_ma50'] else "向下"
        above_ma200 = "向上" if idx['above_ma200'] else "向下"
        report += f"| {idx['name']} | {idx['current_price']:.2f} | {idx['change_5d']:+.2f}% | {idx['change_120d']:+.1f}% | {above_ma50} | {above_ma200} | {idx['trend_label']} |\n"

    report += """

---

## 三、商品与黄金

| 品种 | 最新报价 | 日涨跌 | 年内涨跌 | 趋势方向 |
|------|----------|--------|----------|----------|
"""
    for comm in commodities:
        current_price = comm.get('current_price')
        is_placeholder = current_price in (None, 0.0)

        if is_placeholder:
            latest_price = NA_TEXT
        else:
            latest_price = f"{comm.get('unit', '')} {current_price:.2f}".strip()

        daily_change = (
            f"{comm['daily_change']:+.2f}%"
            if comm.get('daily_change') is not None else "N/A"
        )
        ytd_change = (
            f"{comm['ytd_change']:+.2f}%"
            if comm.get('ytd_change') is not None else "N/A"
        )
        trend = comm.get('trend') or ("待 WebSearch" if is_placeholder else "未知")

        report += f"| {comm['name']} | {latest_price} | {daily_change} | {ytd_change} | {trend} |\n"

    report += """

---

## 四、债券市场

| 债券品种 | 当前收益率 | 近5日变化 | 近120日变化 | 趋势方向 |
|----------|-----------|----------|-------------|----------|
"""
    for bond in bonds:
        current_yield = bond.get('current_yield')
        is_placeholder = current_yield in (None, 0.0)

        if is_placeholder:
            yield_str = NA_TEXT
        else:
            suffix = "(估)" if bond.get('is_estimated') else ""
            yield_str = f"{current_yield:.2f}%{suffix}"

        bp5 = bond.get('change_5d_bp')
        bp120 = bond.get('change_120d_bp')
        bp5_str = f"{bp5:+.1f}bp" if bp5 is not None else "N/A"
        bp120_str = f"{bp120:+.1f}bp" if bp120 is not None else "N/A"
        trend = bond.get('trend') or ("待 WebSearch" if is_placeholder else "未知")

        report += f"| {bond['name']} | {yield_str} | {bp5_str} | {bp120_str} | {trend} |\n"

    report += """

---

## 五、外汇市场

| 货币对 | 当前汇率 | 日涨跌 | 近120日变化 | 趋势方向 |
|--------|---------|--------|-------------|----------|
"""
    for forex in forex_list:
        report += f"| {forex['name']} | {forex['current_rate']:.4f} | {forex['daily_change']:+.2f}% | {forex['change_120d']:+.2f}% | {forex['trend']} |\n"

    report += """

---

## 六、宏观经济指标

| 指标 | 当前值 | 前值 | 变化 | 单位 | 日期 |
|------|--------|------|------|------|------|
"""

    # 仅展示真正的宏观指标；滤除误写入宏观区的商品/外汇/债券/指数键
    non_macro_keys = {
        "GC=F", "CL=F", "BZ=F", "HG=F", "GSG", "BCOM",
        "DXY", "USDCNH", "USDCNY",
        "US10Y", "CN10Y", "CN10Y_CDB",
        "000016"
    }

    for key, indicator in market_data['macro_indicators'].items():
        if key in non_macro_keys:
            continue
        curr = indicator.get('current_value', 'N/A')
        prev = indicator.get('previous_value', 'N/A')
        change = indicator.get('change_rate', 'N/A')
        unit = indicator.get('unit', '')
        date = indicator.get('date', '')

        is_placeholder = indicator.get('is_estimated') or '待MCP' in indicator.get('source', '')
        def _fmt_val(val, suffix="", allow_est=False):
            if val in (None, 'N/A'):
                return NA_TEXT
            if is_placeholder and not allow_est:
                return NA_TEXT
            return f"{val}{suffix}" + ("(估)" if is_placeholder else "")

        curr_str = _fmt_val(curr, unit, allow_est=True)
        prev_str = _fmt_val(prev, unit, allow_est=True)

        if change not in ('N/A', None):
            suffix = 'pp' if unit == '%' else unit
            change_str = _fmt_val(f"{float(change):+.1f}", suffix, allow_est=True)
        else:
            change_str = _fmt_val("0", "pp" if unit == '%' else unit, allow_est=True)

        report += f"| {indicator['indicator_name']} | {curr_str} | {prev_str} | {change_str} | {unit} | {date} |\n"

    report += """

---

## 七、货币政策

| 政策工具 | 当前值 | 120日变化 | 单位 | 更新日期 |
|----------|--------|-----------|------|----------|
"""

    for _, policy in market_data['monetary_policy'].items():
        curr = policy.get('current_value', 'N/A')
        change = policy.get('change_from_120d', 'N/A')
        unit = policy.get('unit', '')
        date = policy.get('date', '')

        is_placeholder = policy.get('is_estimated') or '待MCP' in policy.get('source', '')
        def _fmt_val(val, suffix="", allow_est=False):
            if val in (None, 'N/A'):
                return NA_TEXT
            if is_placeholder and not allow_est:
                return NA_TEXT
            return f"{val}{suffix}" + ("(估)" if is_placeholder else "")

        curr_str = _fmt_val(curr, unit, allow_est=True)
        if change not in ('N/A', None):
            change_str = _fmt_val(f"{float(change):+.1f}", "pp", allow_est=True)
        else:
            change_str = _fmt_val("0", "pp", allow_est=True)

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

    pending_websearch = pring_result.get('pending_websearch') or []
    fallback_used = pring_result.get('fallback_used', False)

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
- **数据完整度**: {data_completeness:.1%}（阈值≥{min_completeness:.0%}）{fallback_hint}
- **待补WebSearch**: {pending_ws}

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
        focus_assets_summary=focus_assets_summary,
        data_completeness=pring_result.get('data_completeness', completeness),
        min_completeness=pring_result.get('metadata', {}).get('min_completeness', 0.8),
        fallback_hint="；allow_fallback=TRUE" if fallback_used else "",
        pending_ws="、".join(map(str, pending_websearch)) if pending_websearch else "无",
    )

    FLOW_LABELS = {
        "northbound": "北向资金",
        "southbound": "南向资金",
        "etf": "ETF资金流",
        "margin": "融资融券",
    }

    def _flow_label(key: str) -> str:
        return FLOW_LABELS.get(key, key)

    def _format_flow_amount(value: Any) -> str:
        if isinstance(value, (int, float)):
            return f"{value:.2f}"
        return 'N/A'

    for key, flow in market_data['fund_flow'].items():
        report += (
            f"| {_flow_label(key)} | {_format_flow_amount(flow.get('recent_5d'))} | "
            f"{_format_flow_amount(flow.get('total_120d'))} | {flow.get('trend', 'N/A')} | "
            f"{flow.get('source', '-')} | {flow.get('note', '-') or '-'} |\n"
        )

    estimated_note = ""
    if estimated_items:
        estimated_text = "、".join(estimated_items)
        estimated_note = (
            f"- **估计值提醒**: 以下指标仍为估计值（is_estimated=True），请谨慎解读：{estimated_text}\n"
        )

    report += f"""

---

## 附录：数据来源

- **API数据源**: TuShare, International Finance
- **MCP增强**: WebSearch (债券、商品、宏观、货币、资金流向)
- **数据完整性**: {completeness:.1%}
- **分析方法**: {pring_result['metadata'].get('analysis_method', 'Pring三层框架')}
{estimated_note}

---

**免责声明**: 本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。
"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"[SUCCESS] 报告生成完成！")
    print(f"  - 输出文件: {output_path}")
    print(f"  - 报告日期: {report_date}")
    print(f"  - 数据完整性: {completeness:.1%}")
    print(f"  - Pring阶段: {pring_result['final_stage']}")
    print(f"  - 置信度: {pring_result['confidence']:.1%}")
    if estimated_items:
        print(f"[WARN] 报告包含估计值指标: {'、'.join(estimated_items)}")


def main(argv: list[str] | None = None) -> None:
    argv = argv or sys.argv[1:]
    market_data_file = Path('data/market_data_complete.json')
    pring_result_file = Path('data/pring_result.json')
    output_file = Path('reports/background_scan_120.md')

    if len(argv) > 0:
        market_data_file = Path(argv[0])
    if len(argv) > 1:
        pring_result_file = Path(argv[1])
    if len(argv) > 2:
        output_file = Path(argv[2])

    generate_report(market_data_file, pring_result_file, output_file)


if __name__ == "__main__":
    main()
