"""C1 跨模块 characterization:搬移前后逐项不变。先对主脚本现函数锁行为,
搬移后(Task 6)断言新模块行为一致。全离线、秒级。
expected 真值采自 main 0187b00 实跑(规划方预计算)。"""
import importlib
from types import SimpleNamespace

import pytest

ERRORS = importlib.import_module("datasource.engines.stage2.errors")
SNIP = importlib.import_module("datasource.engines.stage2.snippet_filters")
EVID = importlib.import_module("datasource.engines.stage2.evidence")
REGEX = importlib.import_module("datasource.engines.stage2.regex_extraction")

ENH = SimpleNamespace(
    _is_tavily_quota_response=ERRORS._is_tavily_quota_response,
    _text_indicates_quota_or_rate_limit=ERRORS._text_indicates_quota_or_rate_limit,
    _host_matches_official_domain=SNIP._host_matches_official_domain,
    _snippet_contains_number=EVID._snippet_contains_number,
    _value_evidence_score=EVID._value_evidence_score,
    _regex_fallback=REGEX._regex_fallback,
    _infer_rrr_type=REGEX._infer_rrr_type,
)


# ---- errors:quota status(_is_tavily_quota_response 读 status_code/status 键)----
@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"status_code": 402}, True),
        ({"status_code": 403}, True),
        ({"status_code": 429}, True),
        ({"status_code": 432}, True),
        ({"status_code": 433}, True),
        ({"status_code": 200}, False),
        ({"status_code": 404}, False),
        ({}, False),
        ({"status": 429}, True),
    ],
)
def test_tavily_quota_response(payload, expected):
    assert ENH._is_tavily_quota_response(payload) is expected


# ---- errors:quota/rate 文本 ----
@pytest.mark.parametrize(
    "text,expected",
    [
        ("rate limit exceeded", True),
        ("payment required", True),
        ("quota exhausted", True),
        ("429 Too Many Requests", True),
        ("ok", False),
        ("", False),
        ("insufficient balance", False),
    ],
)
def test_quota_or_rate_text(text, expected):
    assert ENH._text_indicates_quota_or_rate_limit(text) is expected


# ---- snippet_filters:官方域严格 hostname 匹配 ----
@pytest.mark.parametrize(
    "host,domain,expected",
    [
        ("www.pbc.gov.cn", "pbc.gov.cn", True),
        ("pbc.gov.cn", "pbc.gov.cn", True),
        ("sub.pbc.gov.cn", "pbc.gov.cn", True),
        ("evil-pbc.gov.cn.bad.com", "pbc.gov.cn", False),
    ],
)
def test_host_matches_official_domain(host, domain, expected):
    assert ENH._host_matches_official_domain(host, domain) is expected


# ---- evidence:数值证据仅匹配带单位数字(亿/billion 等)----
@pytest.mark.parametrize(
    "snippet,value,expected",
    [
        ({"content": "北向资金净流入 12.5 亿元"}, 12.5, True),
        ({"title": "成交 3.2 billion"}, 3.2, True),
        ({"content": "净流入 12.5 亿元"}, 99.0, False),
        ({"content": "USDCNY 7.1234 today"}, 7.1234, False),  # 无单位 → False
        ({"content": "x"}, None, False),
    ],
)
def test_snippet_contains_number(snippet, value, expected):
    assert ENH._snippet_contains_number(snippet, value) is expected


# ---- regex_extraction:rrr 类型推断(加权/weighted→weighted;法定/statutory→statutory)----
@pytest.mark.parametrize(
    "text,expected",
    [
        ("加权平均存款准备金率", "weighted"),
        ("weighted average RRR", "weighted"),
        ("法定存款准备金率", "statutory"),
        ("大型存款类金融机构", None),
        ("", None),
    ],
)
def test_infer_rrr_type(text, expected):
    assert ENH._infer_rrr_type(text) == expected


# ---- import-surface:canonical modules expose moved helpers ----
def test_import_surface_canonical_modules():
    for name in [
        "_is_tavily_quota_response",
        "_text_indicates_quota_or_rate_limit",
        "_host_matches_official_domain",
        "_snippet_contains_number",
        "_value_evidence_score",
        "_regex_fallback",
        "_infer_rrr_type",
    ]:
        assert hasattr(ENH, name), f"canonical namespace should expose {name}"


def test_new_modules_export_moved_names():
    assert hasattr(ERRORS, "_is_tavily_quota_response")
    assert hasattr(SNIP, "_host_matches_official_domain")
    assert hasattr(SNIP, "_score_stats")
    assert hasattr(EVID, "_value_evidence_score")
    assert hasattr(REGEX, "_regex_fallback")


def test_moved_fn_identity_via_canonical_namespace():
    # Canonical namespace points at the same function objects as their modules.
    assert ENH._is_tavily_quota_response is ERRORS._is_tavily_quota_response
    assert ENH._value_evidence_score is EVID._value_evidence_score
    assert ENH._regex_fallback is REGEX._regex_fallback
