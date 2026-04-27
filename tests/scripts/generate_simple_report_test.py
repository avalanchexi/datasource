#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""兼容包装：调用正式版 simple_report.generate_report

用于本地/CI 验证 Stage4 报告生成。
"""

import sys
from pathlib import Path
from datetime import datetime
from datasource.generators.simple_report import generate_report
from datasource.utils.run_paths import build_run_paths


def main():
    default_paths = build_run_paths(datetime.now().strftime("%Y-%m-%d"))
    market_data_file = default_paths.market_data_complete
    pring_result_file = default_paths.pring_result
    output_file = default_paths.report_markdown

    if len(sys.argv) > 1:
        market_data_file = Path(sys.argv[1])
    if len(sys.argv) > 2:
        pring_result_file = Path(sys.argv[2])
    if len(sys.argv) > 3:
        output_file = Path(sys.argv[3])

    generate_report(market_data_file, pring_result_file, output_file)


if __name__ == '__main__':
    main()
