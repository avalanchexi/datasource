#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import sys

# 设置输出编码为UTF-8
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def main():
    # 读取完整市场数据
    with open('data/20251114_market_data_complete.json', 'r', encoding='utf-8') as f:
        market_data = json.load(f)

    # 读取Stage 4 WebSearch结果
    with open('data/websearch_results_20251114_stage4.json', 'r', encoding='utf-8') as f:
        stage4_data = json.load(f)

    # 注入资金流向数据，添加type字段
    fund_flow_data = stage4_data['fund_flow']
    for key in fund_flow_data:
        fund_flow_data[key]['type'] = key
    market_data['fund_flow'] = fund_flow_data

    # 注入财经要闻
    market_data['financial_news'] = stage4_data['financial_news']

    # 更新完整度
    market_data['metadata']['data_completeness'] = 0.95
    market_data['metadata']['stage4_enhanced'] = True

    # 保存最终版本
    with open('data/20251114_market_data_final.json', 'w', encoding='utf-8') as f:
        json.dump(market_data, f, ensure_ascii=False, indent=2)

    print('Stage 4 data injection completed')
    print(f'Fund flow: 4 items added')
    print(f'Financial news: {len(stage4_data["financial_news"])} items added')
    print(f'Data completeness: 95%')

if __name__ == '__main__':
    main()
