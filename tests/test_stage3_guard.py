#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage3 前置校验单元测试：
- 数据完整性达到阈值且无缺口应通过
- 缺口或完整性不足应直接抛 RuntimeError
"""

import pytest

import scripts.stage3_pring_analyzer as s3


def test_require_data_completeness_pass():
    payload = {
        "metadata": {"data_completeness": 0.85},
        "missing_items": [],
    }
    # 不应抛异常
    s3._require_data_completeness(payload, 0.8)


def test_require_data_completeness_fail_on_missing():
    payload = {
        "metadata": {"data_completeness": 0.85},
        "missing_items": ["cpi", {"key": "pmi_new_orders"}],
    }
    with pytest.raises(RuntimeError):
        s3._require_data_completeness(payload, 0.8)


def test_require_data_completeness_fail_on_low_score():
    payload = {
        "metadata": {"data_completeness": 0.5},
        "missing_items": [],
    }
    with pytest.raises(RuntimeError):
        s3._require_data_completeness(payload, 0.8)


def test_require_data_completeness_fail_on_estimated():
    payload = {
        "metadata": {"data_completeness": 0.9},
        "missing_items": [],
        "bonds": [
            {"symbol": "CN10Y_CDB", "current_yield": 1.97, "is_estimated": True},
        ],
    }
    with pytest.raises(RuntimeError):
        s3._require_data_completeness(payload, 0.8, allow_estimated=False)


def test_require_data_completeness_fail_on_missing_compare_values():
    payload = {
        "metadata": {"data_completeness": 0.9},
        "missing_items": [],
        "macro_indicators": {
            "industrial": {
                "current_value": 5.2,
                "previous_value": None,
                "change_rate": None,
                "is_estimated": False,
            }
        },
    }
    with pytest.raises(RuntimeError):
        s3._require_data_completeness(payload, 0.8)
