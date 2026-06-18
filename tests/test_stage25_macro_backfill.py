from datasource.engines.stage2_5.trend_backfill import (
    MACRO_CHANGE_RATE_CALIBER,
    _macro_change_rate,
)


def test_yoy_pp_uses_point_difference():
    assert MACRO_CHANGE_RATE_CALIBER["ppi"] == "yoy_pp"
    assert _macro_change_rate("ppi", 2.8, 0.5) == (2.3, None)
    assert _macro_change_rate("cpi", 1.2, 1.0)[0] == 0.2


def test_level_uses_percentage():
    assert MACRO_CHANGE_RATE_CALIBER["bdi"] == "level_pct"
    assert _macro_change_rate("bdi", 2818.0, 2916.0)[0] == round(
        (2818 - 2916) / 2916 * 100,
        4,
    )


def test_level_div_by_zero_returns_none():
    assert _macro_change_rate("bdi", 5.0, 0.0) == (
        None,
        "change_rate_pct_div_by_zero",
    )


def test_level_near_zero_returns_none():
    assert _macro_change_rate("bdi", 1.0, 1e-10) == (
        None,
        "change_rate_pct_div_by_zero",
    )


def test_unknown_key_infers_by_unit():
    assert _macro_change_rate("xx", 3.0, 2.0, unit="%") == (
        1.0,
        "caliber_inferred",
    )
    assert _macro_change_rate("xx", 300.0, 200.0, unit="点") == (
        50.0,
        "caliber_inferred",
    )
