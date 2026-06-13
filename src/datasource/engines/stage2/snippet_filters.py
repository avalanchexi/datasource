"""Snippet freshness, scoring, domain, and keyword filters for Stage2."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

_REPORT_MONTH_KEYS = {"industrial", "industrial_sales"}


def _parse_date_str(text: str) -> Optional[datetime]:
    """尝试解析片段中的日期字符串为 UTC 时间，失败返回 None。"""
    if not text:
        return None
    text = str(text).strip()
    # 直接解析 ISO 格式
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    # 匹配 YYYY-MM-DD / YYYY/MM/DD
    m = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        try:
            y, mo, d = map(int, m.groups())
            return datetime(y, mo, d, tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _extract_dates(snippets: Optional[List[Dict[str, Any]]]) -> List[datetime]:
    dates: List[datetime] = []
    for snip in snippets or []:
        # 优先使用 Tavily 的 published_date 字段
        dt_val = snip.get("published_date")
        if dt_val:
            parsed = _parse_date_str(dt_val)
            if parsed:
                dates.append(parsed)
                continue
        # 其次尝试从片段文本中提取日期
        content = snip.get("content") or snip.get("snippet") or ""
        parsed = _parse_date_str(content)
        if parsed:
            dates.append(parsed)
    return dates


def _is_stale(snippets: Optional[List[Dict[str, Any]]], max_age_days: Optional[int]) -> bool:  # noqa: E501
    """若所有可解析日期均早于 max_age_days，则判定为过期；无日期信息则返回 False。"""
    if not max_age_days:
        return False
    dates = _extract_dates(snippets)
    if not dates:
        return False
    now = datetime.now(timezone.utc)
    fresh_found = any((now - dt) <= timedelta(days=max_age_days) for dt in dates)  # noqa: E501
    if fresh_found:
        return False
    return True


def _prefer_fresh_snippets(snippets: Optional[List[Dict[str, Any]]], max_age_days: Optional[int]) -> List[Dict[str, Any]]:  # noqa: E501
    """优先返回满足时效性的片段；若没有新鲜片段则原样返回。"""
    if not snippets:
        return []
    if not max_age_days:
        return snippets
    fresh = []
    now = datetime.now(timezone.utc)
    for snip in snippets:
        dt_val = snip.get("published_date") or ""
        parsed = _parse_date_str(dt_val) if dt_val else None
        if not parsed:
            parsed = _parse_date_str(snip.get("content") or snip.get("snippet") or "")  # noqa: E501
        if parsed and (now - parsed) <= timedelta(days=max_age_days):
            fresh.append(snip)
    return fresh or snippets


def _extract_report_month(text: str) -> Optional[Tuple[int, int]]:
    """从文本中提取报告月份(年,月)，优先识别'YYYY年1-XX月'再识别'YYYY年MM月'。"""
    if not text:
        return None
    candidates: List[Tuple[int, int]] = []
    # 例如：2025年1-11月 / 2025年1—11月 / 2025年1至11月
    range_pat = re.compile(r"(20\d{2})\s*年\s*1\s*(?:-|—|~|至|到)\s*(\d{1,2})\s*月")  # noqa: E501
    for y, m in range_pat.findall(text):
        try:
            year = int(y)
            month = int(m)
            if 1 <= month <= 12:
                candidates.append((year, month))
        except Exception:
            continue
    # 例如：2025年12月 / 2025年12月份
    month_pat = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月")
    for y, m in month_pat.findall(text):
        try:
            year = int(y)
            month = int(m)
            if 1 <= month <= 12:
                candidates.append((year, month))
        except Exception:
            continue
    if not candidates:
        return None
    return max(candidates)


def _prefer_latest_report_snippets(
    snippets: Optional[List[Dict[str, Any]]], indicator_key: Optional[str]
) -> List[Dict[str, Any]]:
    """对月度宏观指标优先保留最新报告月份的片段。"""
    if not snippets:
        return []
    if not indicator_key or indicator_key not in _REPORT_MONTH_KEYS:
        return snippets
    tagged: List[Tuple[Tuple[int, int], Dict[str, Any]]] = []
    for snip in snippets:
        text = " ".join(
            [
                str(snip.get("title") or ""),
                str(snip.get("snippet") or ""),
                str(snip.get("content") or ""),
            ]
        )
        rep = _extract_report_month(text)
        if rep:
            tagged.append((rep, snip))
    if not tagged:
        return snippets
    latest = max(rep for rep, _ in tagged)
    filtered = [snip for rep, snip in tagged if rep == latest]
    return filtered or snippets


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    if pct <= 0:
        return values[0]
    if pct >= 100:
        return values[-1]
    k = (len(values) - 1) * pct / 100.0
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[int(k)]
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1


def _score_stats(snippets: List[Dict[str, Any]]) -> Dict[str, Any]:
    scores = []
    for s in snippets:
        score = s.get("score")
        if isinstance(score, (int, float)):
            scores.append(float(score))
    if not scores:
        return {
            "score_count": 0,
            "score_min": None,
            "score_p50": None,
            "score_p95": None,
            "score_max": None,
        }
    return {
        "score_count": len(scores),
        "score_min": min(scores),
        "score_p50": _percentile(scores, 50),
        "score_p95": _percentile(scores, 95),
        "score_max": max(scores),
    }


def _filter_by_domain(
    snippets: List[Dict[str, Any]],
    preferred: Optional[List[str]],
    indicator_key: Optional[str] = None,
    fallback_to_original: bool = True,
) -> List[Dict[str, Any]]:
    """过滤掉不在白名单域名中的搜索结果；若过滤后为空则回退原列表。"""
    if not preferred:
        return snippets
    noisy_path_tokens = {
        "investing.com": ["/news/"],
        "marketwatch.com": ["/story/", "/press-release/"],
    }
    # 仅对实时类指标启用路径噪音过滤，避免误伤宏观新闻类指标
    noisy_filter_keys = {
        "USDCNY",
        "USDCNH",
        "DXY",
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "US10Y",
        "CN10Y",
        "CN10Y_CDB",
        "GC=F",
        "CL=F",
        "BZ=F",
        "HG=F",
        "BCOM",
        "GSG",
        "bdi",
    }
    apply_noisy_filter = indicator_key in noisy_filter_keys if indicator_key else True  # noqa: E501
    filtered: List[Dict[str, Any]] = []
    for snip in snippets:
        url = snip.get("url") or ""
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc
            path = parsed.path or ""
            matched_domain = None
            for d in preferred:
                if netloc.endswith(d):
                    matched_domain = d
                    break
            if matched_domain:
                # drop obvious news pages for numeric indicators
                if apply_noisy_filter:
                    blocked_tokens = noisy_path_tokens.get(matched_domain)
                    if blocked_tokens and any(tok in path for tok in blocked_tokens):  # noqa: E501
                        continue
                filtered.append(snip)
        except Exception:
            continue
    if filtered:
        return filtered
    return snippets if fallback_to_original else []


def _official_extract_domains(extract_policy: Dict[str, Any]) -> List[str]:
    if not extract_policy.get("official_domains_only"):
        return []
    domains = extract_policy.get("official_domains") or []
    return [str(domain).strip().lower() for domain in domains if str(domain).strip()]  # noqa: E501


def _host_matches_official_domain(host: str, domain: str) -> bool:
    host = host.strip().lower().rstrip(".")
    domain = domain.strip().lower().rstrip(".")
    return bool(host and domain and (host == domain or host.endswith(f".{domain}")))  # noqa: E501


def _filter_by_official_extract_domain(
    snippets: List[Dict[str, Any]],
    official_domains: Optional[List[str]],
) -> List[Dict[str, Any]]:
    if not official_domains:
        return snippets
    domains = [str(domain).strip().lower().rstrip(".") for domain in official_domains if str(domain).strip()]  # noqa: E501
    if not domains:
        return snippets
    filtered: List[Dict[str, Any]] = []
    for snip in snippets:
        url = snip.get("url") or ""
        try:
            host = (urlparse(url).hostname or "").lower().rstrip(".")
        except Exception:
            continue
        if any(_host_matches_official_domain(host, domain) for domain in domains):  # noqa: E501
            filtered.append(snip)
    return filtered


def _snippet_blob(snippet: Dict[str, Any]) -> str:
    return " ".join(
        [
            str(snippet.get("title") or ""),
            str(snippet.get("snippet") or ""),
            str(snippet.get("content") or ""),
            str(snippet.get("url") or ""),
        ]
    ).lower()


def _filter_by_keyword_rules(
    snippets: List[Dict[str, Any]],
    required_keywords: Optional[List[str]] = None,
    exclude_keywords: Optional[List[str]] = None,
    fallback_to_original: bool = True,
) -> List[Dict[str, Any]]:
    if not snippets:
        return []
    required = [str(token).lower() for token in (required_keywords or []) if str(token).strip()]  # noqa: E501
    excluded = [str(token).lower() for token in (exclude_keywords or []) if str(token).strip()]  # noqa: E501
    filtered: List[Dict[str, Any]] = []
    for snip in snippets:
        text = _snippet_blob(snip)
        if excluded and any(token in text for token in excluded):
            continue
        if required and not any(token in text for token in required):
            continue
        filtered.append(snip)
    if filtered:
        return filtered
    return snippets if fallback_to_original else []


def _snippets_have_issuer(
    snippets: List[Dict[str, Any]],
    issuer_hint: Optional[str],
    issuer_aliases: Optional[List[str]] = None,
) -> bool:
    if not issuer_hint and not issuer_aliases:
        return False
    hint_tokens = [str(issuer_hint or "").lower()] + [
        str(alias).lower() for alias in (issuer_aliases or []) if str(alias).strip()  # noqa: E501
    ]
    hint_tokens = [token for token in hint_tokens if token]
    if not hint_tokens:
        return False
    for snip in snippets:
        text = _snippet_blob(snip)
        if any(token in text for token in hint_tokens):
            return True
    return False


def _snippets_have_expected_period(
    snippets: List[Dict[str, Any]],
    expected_period_tokens: Optional[List[str]],
) -> bool:
    tokens = [str(token).lower() for token in (expected_period_tokens or []) if str(token).strip()]  # noqa: E501
    if not tokens:
        return False
    for snip in snippets:
        text = _snippet_blob(snip)
        if any(token in text for token in tokens):
            return True
    return False


def _strict_indicator_tokens(indicator_key: Optional[str]) -> List[str]:
    key = str(indicator_key or "").strip().lower()
    mapping = {
        "gc=f": ["gc=f", "gold", "黄金", "comex"],
        "cl=f": ["cl=f", "wti", "原油", "nymex"],
        "bz=f": ["bz=f", "brent", "布伦特", "ice"],
        "hg=f": ["hg=f", "copper", "铜", "comex"],
        "bcom": ["bcom", "bloomberg commodity index", "彭博商品指数"],
        "gsg": ["gsg"],
        "usdcny": ["usdcny", "usd/cny", "在岸", "中间价", "美元", "人民币"],
        "usdcnh": ["usdcnh", "usd/cnh", "离岸"],
        "dxy": ["dxy", "美元指数"],
        "cn10y_cdb": ["国开债", "国开", "开发债", "政策性金融债", "中债估值", "cdb", "国家开发银行"],
        "rrr": ["rrr", "存款准备金率"],
        "reverse_repo": ["逆回购", "reverse repo"],
        "mlf": ["mlf", "中期借贷便利"],
    }
    return [token.lower() for token in mapping.get(key, []) if token]
