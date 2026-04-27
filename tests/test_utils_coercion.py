import pytest

from datasource.utils.coercion import (
    is_legacy_713_placeholder,
    is_stage2_number_placeholder,
    is_stage2_task_placeholder,
    to_float,
)
from datasource.utils.text_markers import contains_ytd_marker


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("", None),
        ("N/A", None),
        ("1.25", 1.25),
        (2, 2.0),
        ("abc", None),
    ],
)
def test_to_float_returns_none_for_non_numeric(value, expected):
    assert to_float(value) == expected


@pytest.mark.parametrize("value", [None, "", "N/A", 0, 0.0, "0", "0.0000000001", "abc"])
def test_stage2_number_placeholder_matches_stage2_and_stage25_semantics(value):
    assert is_stage2_number_placeholder(value) is True


@pytest.mark.parametrize("value", [1, "1.2", -0.1])
def test_stage2_number_placeholder_accepts_non_zero_numbers(value):
    assert is_stage2_number_placeholder(value) is False


@pytest.mark.parametrize("value", [7.13, "7.13", 7.1300001])
def test_legacy_713_placeholder_is_separate_contract(value):
    assert is_legacy_713_placeholder(value) is True


@pytest.mark.parametrize("value", [None, 0, 0.0, 7.13, "7.13"])
def test_stage2_task_placeholder_keeps_legacy_713_semantics(value):
    assert is_stage2_task_placeholder(value) is True


@pytest.mark.parametrize("value", ["", "N/A", "abc", 1.0])
def test_stage2_task_placeholder_does_not_copy_stage25_non_numeric_semantics(value):
    assert is_stage2_task_placeholder(value) is False


@pytest.mark.parametrize(
    "text",
    [
        "今年累计净流入 123 亿元",
        "年初至今收益率为 8%",
        "YTD return improved",
        "year-to-date performance",
        "1-3月累计值",
    ],
)
def test_contains_ytd_marker_detects_supported_markers(text):
    assert contains_ytd_marker(text) is True


@pytest.mark.parametrize("text", ["普通文本", "", None])
def test_contains_ytd_marker_rejects_plain_text(text):
    assert contains_ytd_marker(text) is False
