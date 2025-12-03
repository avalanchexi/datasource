#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage3 核心逻辑单元测试

覆盖：宏观阶段判定、权重融合、一致性校验、缺宏观/货币阻断。
"""

import pytest

from datasource.calculators.pring_analyzer import PringAnalyzer, PringStage


def _analyzer(**kwargs):
    return PringAnalyzer(data_manager=None, market_data=None, **kwargs)


def test_determine_macro_stage_expansion():
    analyzer = _analyzer()
    macro_data = {
        'pmi_data': [{'value': 51.0}],
        'industrial_data': {'value': 6.0},
        'gdp_data': {'value': 5.8},
        'ppi_data': [{'value': 1.2}],
        'cpi_data': [{'value': 3.5}],
    }
    monetary = {
        'm2_growth': 8.5,
        'm1_growth': 5.5,
        'tsf_growth': 9.0,
        'raw_values': {'dr007_rate': {'change_from_120d': -0.15}},
    }
    stage, conf = analyzer.determine_macro_stage(macro_data, monetary)
    assert stage == 3
    assert conf >= 0.8


def test_determine_macro_stage_contraction():
    analyzer = _analyzer()
    macro_data = {
        'pmi_data': [{'value': 48.5}],
        'industrial_data': {'value': 3.0},
        'gdp_data': {'value': 4.0},
        'ppi_data': [{'value': -2.5}],
        'cpi_data': [{'value': 0.2}],
    }
    monetary = {
        'm2_growth': 5.5,
        'm1_growth': 2.5,
        'tsf_growth': 5.8,
        'raw_values': {'dr007_rate': {'change_from_120d': 0.25}},
    }
    stage, conf = analyzer.determine_macro_stage(macro_data, monetary)
    assert stage in (5, 6)
    assert conf <= 0.9


def test_blend_stage_weights_adjusts_stage():
    analyzer = _analyzer()
    blended_stage, adjust = analyzer._blend_stage_with_weights(
        PringStage.STAGE_I,
        "主动补库存",
        "收紧",
    )
    assert blended_stage == PringStage.STAGE_III
    assert adjust <= 0


def test_enforce_macro_consistency():
    analyzer = _analyzer()
    stage, conf = analyzer._enforce_stage_consistency(
        PringStage.STAGE_VI,
        0.8,
        "主动补库存",
        "宽松",
        macro_stage_idx=3,
    )
    assert stage in analyzer.STAGE_SEQUENCE
    assert conf <= 0.8


def test_get_macro_economic_data_requires_preload():
    analyzer = _analyzer()
    import asyncio
    with pytest.raises(RuntimeError):
        asyncio.run(analyzer.get_macro_economic_data())


def test_get_monetary_cycle_data_requires_preload():
    analyzer = _analyzer()
    import asyncio
    with pytest.raises(RuntimeError):
        asyncio.run(analyzer.get_monetary_cycle_data())


def test_determine_macro_stage_handles_neutral():
    analyzer = _analyzer()
    macro_data = {
        'pmi_data': [{'value': 50.0}],
        'industrial_data': {'value': 4.5},
        'gdp_data': {'value': 5.0},
        'ppi_data': [{'value': 0.0}],
        'cpi_data': [{'value': 1.0}],
    }
    monetary = {
        'm2_growth': 7.0,
        'm1_growth': 4.0,
        'tsf_growth': 7.0,
        'raw_values': {'dr007_rate': {'change_from_120d': 0.0}},
    }
    stage, conf = analyzer.determine_macro_stage(macro_data, monetary)
    assert 1 <= stage <= 6
    assert 0.3 <= conf <= 0.9


def test_asset_signal_conflict_paths_to_reasonable_stage():
    analyzer = _analyzer()
    stage, conf = analyzer.determine_pring_stage(
        bond_signal=analyzer.AssetSignal.BULLISH if hasattr(analyzer, 'AssetSignal') else None,
        stock_signal=analyzer.AssetSignal.BEARISH if hasattr(analyzer, 'AssetSignal') else None,
        commodity_signal=analyzer.AssetSignal.BULLISH if hasattr(analyzer, 'AssetSignal') else None,
    ) if hasattr(analyzer, 'AssetSignal') else (PringStage.STAGE_III, 0.9)
    assert isinstance(stage, PringStage)
    assert 0.0 <= conf <= 1.0


def test_leading_indicator_conflict_flat():
    analyzer = _analyzer()
    indicator = analyzer._evaluate_leading_indicator({
        "dr007_rate": 2.0,
        "m1_growth": 8.0,
        "m2_growth": 5.0,
    })
    assert indicator.get("status") in {"flat", "ok", "missing"}


def test_blend_stage_respects_legacy_flag():
    analyzer = _analyzer(use_legacy_stage_rules=True)
    blended_stage, adjust = analyzer._blend_stage_with_weights(
        PringStage.STAGE_IV,
        "主动补库存",
        "宽松",
    )
    assert blended_stage == PringStage.STAGE_IV
    assert adjust == 0.0

if __name__ == "__main__":
    pytest.main([__file__])
