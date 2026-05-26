"""Official China provider for Stage2 monetary, forex, and macro values."""

from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urljoin
from typing import Any, Awaitable, Callable, Dict, Optional

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.http_fetcher import (
    fetch_json as default_fetch_json,
    fetch_text as default_fetch_text,
)
from datasource.providers.stage2_structured.source_tiers import (
    classify_structured_source_tier,
)
from datasource.utils.key_aliases import canonical_monetary_key


FetchText = Callable[[str, Optional[Dict[str, Any]]], Awaitable[str]]
FetchJson = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Dict[str, Any]]]

REVERSE_REPO_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/125475/index.html"
MLF_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125437/125446/125873/index.html"
USDCNY_URL = "https://www.chinamoney.com.cn/chinese/bkccpr/"
USDCNY_API_URL = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew"
NBS_URL = "https://www.stats.gov.cn/sj/zxfb/"
RESERVE_RATIO_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125434/125798/index.html"


class OfficialChinaProvider(Stage2StructuredProvider):
    name = "official_china"

    REVERSE_REPO_URL = REVERSE_REPO_URL
    MLF_URL = MLF_URL
    USDCNY_URL = USDCNY_URL
    USDCNY_API_URL = USDCNY_API_URL
    NBS_URL = NBS_URL
    RESERVE_RATIO_URL = RESERVE_RATIO_URL

    supported_keys = {
        "reverse_repo",
        "reverse_repo_7d",
        "mlf",
        "mlf_rate",
        "USDCNY",
        "industrial",
        "industrial_sales",
        "reserve_ratio",
        "rrr",
    }

    def __init__(
        self,
        fetch_text: FetchText = default_fetch_text,
        fetch_json: FetchJson = default_fetch_json,
    ) -> None:
        self._fetch_text = fetch_text
        self._fetch_json = fetch_json

    async def fetch(self, task, market_payload, reference_date):
        raw_key = str(task.get("indicator_key") or "")
        key = self._canonical_key(raw_key)
        if key not in self._canonical_supported_keys():
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=raw_key,
                reason="unsupported_key",
                message="Official China provider does not support {0}".format(raw_key),
            )

        if key == "USDCNY":
            return await self._fetch_usdcny(raw_key, reference_date)

        url = self._url_for_key(key)
        params = None
        try:
            html = await self._fetch_text(url, params)
        except StructuredProviderError:
            raise
        except Exception as exc:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=raw_key,
                reason="fetch_error",
                message=str(exc),
                diagnostics={"url": url, "params": params},
            )

        html, source_url = await self._follow_detail_page(
            key, html, url, task, reference_date
        )
        result = self._parse_result(key, raw_key, task, html, source_url, reference_date)
        if result is None:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=raw_key,
                reason="missing_value",
                message="Official China source did not contain a parseable value",
                diagnostics={"url": url, "evidence_text": self._evidence(html)},
            )
        return result

    async def _fetch_usdcny(self, raw_key, reference_date):
        params = None
        try:
            data = await self._fetch_json(self.USDCNY_API_URL, params)
        except Exception:
            try:
                html = await self._fetch_text(self.USDCNY_URL, None)
            except Exception as exc:
                raise StructuredProviderError(
                    provider=self.name,
                    indicator_key=raw_key,
                    reason="fetch_error",
                    message=str(exc),
                    diagnostics={"url": self.USDCNY_API_URL, "params": params},
                )
            result = self._parse_usdcny_result(raw_key, html, self.USDCNY_URL, reference_date)
            if result is None:
                raise StructuredProviderError(
                    provider=self.name,
                    indicator_key=raw_key,
                    reason="missing_value",
                    message="Official China source did not contain a parseable value",
                    diagnostics={"url": self.USDCNY_URL, "evidence_text": self._evidence(html)},
                )
            return result

        parsed = self._parse_usdcny_json(data)
        if parsed is None:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=raw_key,
                reason="missing_value",
                message="ChinaMoney JSON did not contain USD/CNY",
                diagnostics={"url": self.USDCNY_API_URL},
            )
        value, as_of_date = parsed
        return StructuredResult(
            provider=self.name,
            indicator_key=raw_key,
            category="forex",
            payload={"value": value, "unit": "CNY", "is_estimated": False},
            source="Official China structured source",
            source_url=self.USDCNY_URL,
            source_tier=classify_structured_source_tier(self.USDCNY_URL),
            as_of_date=as_of_date or reference_date,
            confidence=0.95,
            diagnostics={
                "api_url": self.USDCNY_API_URL,
                "evidence_text": "USD/CNY {0}".format(value),
            },
        )

    async def _follow_detail_page(self, key, html, url, task, reference_date):
        detail_url = None
        target_date = self._target_operation_date(task)
        if key == "reverse_repo":
            detail_url = self._find_link(
                html,
                url,
                include_tokens=("公开市场业务交易公告",),
                exclude_tokens=("公开市场买断式逆回购",),
                target_date=target_date,
                date_match_mode="exact",
            )
        elif key == "mlf":
            detail_url = self._find_link(
                html,
                url,
                include_tokens=("中期借贷便利",),
                exclude_tokens=(),
                target_date=target_date,
                date_match_mode="month",
            )
        elif key == "industrial":
            detail_url = self._find_link(
                html,
                url,
                include_tokens=("规模以上工业增加值",),
                exclude_tokens=(),
            )
        elif key == "industrial_sales":
            detail_url = self._find_link(
                html,
                url,
                include_tokens=("规模以上工业企业",),
                optional_tokens=("营业收入", "利润"),
                exclude_tokens=(),
            )
            if detail_url is None and self._parse_macro_value(key, html) is None:
                for page_url in self._nbs_paginated_urls(url):
                    page_html = await self._fetch_text(page_url, None)
                    detail_url = self._find_link(
                        page_html,
                        page_url,
                        include_tokens=("规模以上工业企业",),
                        optional_tokens=("营业收入", "利润"),
                        exclude_tokens=(),
                    )
                    if detail_url is not None:
                        break

        if detail_url is None:
            return html, url
        try:
            return await self._fetch_text(detail_url, None), detail_url
        except Exception:
            return html, url

    @classmethod
    def _canonical_supported_keys(cls):
        return {cls._canonical_key(key) for key in cls.supported_keys}

    @staticmethod
    def _canonical_key(key):
        monetary_key = canonical_monetary_key(key)
        if monetary_key != str(key or "").strip():
            return monetary_key
        return str(key or "").strip()

    @classmethod
    def _url_for_key(cls, key):
        if key == "reverse_repo":
            return cls.REVERSE_REPO_URL
        if key == "mlf":
            return cls.MLF_URL
        if key == "USDCNY":
            return cls.USDCNY_URL
        if key in {"industrial", "industrial_sales"}:
            return cls.NBS_URL
        if key == "reserve_ratio":
            return cls.RESERVE_RATIO_URL
        return cls.NBS_URL

    def _parse_result(self, key, raw_key, task, html, url, reference_date):
        if key in {"reverse_repo", "mlf", "reserve_ratio"}:
            return self._parse_monetary_result(key, raw_key, task, html, url, reference_date)
        if key == "USDCNY":
            return self._parse_usdcny_result(raw_key, html, url, reference_date)
        if key in {"industrial", "industrial_sales"}:
            return self._parse_macro_result(key, raw_key, task, html, url, reference_date)
        return None

    def _parse_monetary_result(self, key, raw_key, task, html, url, reference_date):
        value = self._parse_rate(html)
        if value is None:
            if key == "mlf" and "多重价位" in html:
                operation_amount = self._parse_operation_amount(html)
                raise StructuredProviderError(
                    provider=self.name,
                    indicator_key=raw_key,
                    reason="multi_price_no_unified_rate",
                    message="MLF announcement uses multiple-price bidding and has no unified rate",
                    diagnostics={
                        "url": url,
                        "operation_amount": operation_amount,
                        "evidence_text": self._evidence(html),
                    },
                )
            return None

        payload = {"value": value, "unit": "%", "is_estimated": False}
        operation_amount = self._parse_operation_amount(html)
        if operation_amount is not None and key in {"reverse_repo", "mlf"}:
            payload["operation_amount"] = operation_amount

        diagnostics = {
            "evidence_text": self._evidence(html),
            "canonical_indicator_key": key,
        }
        if key == "mlf" and "多重价位" in html:
            payload["policy_name"] = "MLF多重价位参考值"
            payload["manual_reason"] = "多重价位，参考值，口径不适用"
            diagnostics["note"] = "MLF公告包含多重价位，利率按公告参考/中标利率语境解析。"

        operation_date = self._parse_date(html) or self._parse_date_from_url(url)
        target_date = self._target_operation_date(task)
        if key in {"reverse_repo", "mlf"}:
            if operation_date is None:
                raise StructuredProviderError(
                    provider=self.name,
                    indicator_key=raw_key,
                    reason="period_mismatch",
                    message="PBoC operation notice does not expose a parseable operation date",
                    diagnostics={"url": url, "evidence_text": self._evidence(html)},
                )
            if target_date and not self._operation_date_matches(key, operation_date, target_date):
                raise StructuredProviderError(
                    provider=self.name,
                    indicator_key=raw_key,
                    reason="period_mismatch",
                    message="PBoC operation notice date does not match the task period",
                    diagnostics={
                        "url": url,
                        "operation_date": operation_date,
                        "target_date": target_date,
                        "evidence_text": self._evidence(html),
                    },
                )

        return StructuredResult(
            provider=self.name,
            indicator_key=raw_key,
            category="monetary_policy",
            payload=payload,
            source="Official China structured source",
            source_url=url,
            source_tier=classify_structured_source_tier(url),
            as_of_date=operation_date or reference_date,
            confidence=0.9,
            diagnostics=diagnostics,
        )

    def _parse_usdcny_result(self, raw_key, html, url, reference_date):
        value = self._parse_usdcny_value(html)
        if value is None:
            return None

        return StructuredResult(
            provider=self.name,
            indicator_key=raw_key,
            category="forex",
            payload={"value": value, "unit": "CNY", "is_estimated": False},
            source="Official China structured source",
            source_url=url,
            source_tier=classify_structured_source_tier(url),
            as_of_date=self._parse_date(html) or reference_date,
            confidence=0.9,
            diagnostics={"evidence_text": self._evidence(html)},
        )

    def _parse_macro_result(self, key, raw_key, task, html, url, reference_date):
        value = self._parse_macro_value(key, html)
        if value is None:
            return None

        value_type = "yoy_month" if key == "industrial" else "yoy_ytd"
        payload = {
            "value": value,
            "unit": "%",
            "is_estimated": False,
            "value_type": value_type,
            "report_period": self._report_period(task, html, reference_date),
        }
        if key == "industrial" and value_type == "yoy_month":
            payload["yoy_month"] = value
        if key == "industrial_sales" and value_type == "yoy_ytd":
            payload["yoy_ytd"] = value

        return StructuredResult(
            provider=self.name,
            indicator_key=raw_key,
            category="macro_indicators",
            payload=payload,
            source="Official China structured source",
            source_url=url,
            source_tier=classify_structured_source_tier(url),
            as_of_date=self._parse_date(html) or reference_date,
            confidence=0.9,
            diagnostics={
                "evidence_text": self._evidence(html),
                "canonical_indicator_key": key,
            },
        )

    @staticmethod
    def _parse_rate(html):
        normalized = OfficialChinaProvider._normalize_text(html)
        patterns = [
            r"7\s*天\s*([0-9]+(?:\s*\.\s*[0-9]+)?)\s*%",
            r"(?:中标利率|利率|存款准备金率)[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*%",
            r"(?:中标利率|利率|存款准备金率)[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*％",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                return float(re.sub(r"\s+", "", match.group(1)))
        return None

    @staticmethod
    def _parse_operation_amount(html):
        normalized = OfficialChinaProvider._normalize_text(html)
        patterns = [
            r"(?:逆回购操作|MLF\）操作|MLF\)操作|中期借贷便利（MLF）操作|中期借贷便利\(MLF\)操作)([0-9,]+(?:\.[0-9]+)?)\s*亿元",
            r"开展了?\s*([0-9,]+(?:\.[0-9]+)?)\s*亿元[^，。；;]{0,40}(?:逆回购操作|MLF\）操作|MLF\)操作|中期借贷便利（MLF）操作|中期借贷便利\(MLF\)操作)",
            r"操作([0-9,]+(?:\.[0-9]+)?)\s*亿元",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                return float(match.group(1).replace(",", ""))
        return None

    @staticmethod
    def _parse_usdcny_json(data):
        try:
            headers = list(data["data"]["head"])
            records = list(data.get("records") or data["data"].get("records") or [])
            index = headers.index("USD/CNY")
            first = records[0]
            values = list(first["values"])
            return float(values[index]), str(first.get("date") or "")
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    @staticmethod
    def _parse_usdcny_value(html):
        patterns = [
            r"USD/CNY[^0-9]{0,40}([0-9]+\.[0-9]+)",
            r"人民币汇率中间价[^0-9]{0,40}([0-9]+\.[0-9]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.IGNORECASE)
            if match:
                return float(match.group(1))
        return None

    @staticmethod
    def _parse_macro_value(key, html):
        html = OfficialChinaProvider._normalize_text(html)
        if key == "industrial":
            month_pattern = (
                r"\d{1,2}\s*月份，(?:规模以上)?工业增加值同比(?:实际)?\s*"
                r"(增长|下降|减少|回落)?\s*(-?[0-9]+(?:\.[0-9]+)?)\s*%"
            )
            for match in re.finditer(month_pattern, html):
                prefix = html[max(0, match.start() - 8) : match.start()]
                if "—" in prefix or "-" in prefix:
                    continue
                return OfficialChinaProvider._signed_percent_value(
                    match.group(1),
                    match.group(2),
                )
            patterns = [
                r"工业增加值同比[^。；;—-]*?(增长|下降|减少|回落)\s*(-?[0-9]+(?:\.[0-9]+)?)\s*%",
                r"工业增加值同比[^-0-9—]{0,20}()(-?[0-9]+(?:\.[0-9]+)?)\s*%",
            ]
        else:
            patterns = [
                r"营业收入[^。；;]*?(增长|下降|减少|回落)\s*(-?[0-9]+(?:\.[0-9]+)?)\s*%",
                r"销售收入[^。；;]*?(增长|下降|减少|回落)\s*(-?[0-9]+(?:\.[0-9]+)?)\s*%",
                r"营业收入[^-0-9]{0,30}()(-?[0-9]+(?:\.[0-9]+)?)\s*%",
                r"销售收入[^-0-9]{0,30}()(-?[0-9]+(?:\.[0-9]+)?)\s*%",
            ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                if key == "industrial" and OfficialChinaProvider._has_ytd_prefix(
                    html, match.start()
                ):
                    continue
                return OfficialChinaProvider._signed_percent_value(
                    match.group(1),
                    match.group(2),
                )
        return None

    @staticmethod
    def _signed_percent_value(direction, value_text):
        value = float(value_text)
        if value < 0:
            return value
        if direction in {"下降", "减少", "回落"}:
            return -value
        return value

    @staticmethod
    def _has_ytd_prefix(text, match_start):
        prefix = text[max(0, match_start - 24) : match_start]
        return bool(re.search(r"1\s*[—-]\s*\d{1,2}\s*月份", prefix))

    @staticmethod
    def _parse_date(html):
        pub_match = re.search(
            r'(?:PubDate|createDate)["\']?\s+content=["\'](20\d{2})[/-](\d{1,2})[/-](\d{1,2})',
            html,
            flags=re.IGNORECASE,
        )
        if pub_match:
            year, month, day = pub_match.groups()
            return "{0}-{1:02d}-{2:02d}".format(int(year), int(month), int(day))

        match = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", html)
        if match:
            year, month, day = match.groups()
            return "{0}-{1:02d}-{2:02d}".format(int(year), int(month), int(day))

        match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", html)
        if match:
            year, month, day = match.groups()
            return "{0}-{1:02d}-{2:02d}".format(int(year), int(month), int(day))
        return None

    @staticmethod
    def _parse_date_from_url(url):
        match = re.search(r"(20\d{2})(\d{2})(\d{2})", str(url or ""))
        if not match:
            return None
        year, month, day = match.groups()
        return "{0}-{1}-{2}".format(year, month, day)

    @staticmethod
    def _target_operation_date(task):
        if not isinstance(task, dict):
            return None
        for field in ("ref_date", "reference_date"):
            raw = task.get(field)
            if isinstance(raw, str) and re.match(r"20\d{2}-\d{2}-\d{2}$", raw.strip()):
                return raw.strip()
        return None

    @staticmethod
    def _operation_date_matches(key, operation_date, target_date):
        if not target_date:
            return True
        if key == "mlf":
            return str(operation_date or "")[:7] == str(target_date)[:7]
        return str(operation_date or "")[:10] == str(target_date)[:10]

    @staticmethod
    def _date_tokens(date_text):
        match = re.match(r"(20\d{2})-(\d{2})-(\d{2})$", str(date_text or "").strip())
        if not match:
            return set()
        year, month, day = match.groups()
        month_i = int(month)
        day_i = int(day)
        return {
            f"{year}{month}{day}",
            f"{year}-{month}-{day}",
            f"{year}年{month_i}月{day_i}日",
            f"{year}年{int(month)}月",
            f"{year}{month}",
        }

    @staticmethod
    def _link_matches_date(label, url, target_date, mode):
        if not target_date:
            return True
        haystack = f"{label} {url}"
        tokens = OfficialChinaProvider._date_tokens(target_date)
        if mode == "month":
            return any(token in haystack for token in tokens if len(token) in {6, 8} or "月" in token)
        return any(token in haystack for token in tokens if token.count("-") == 2 or token.endswith("日") or len(token) == 8)

    @staticmethod
    def _report_period(task, html, reference_date):
        expected_period = task.get("expected_period")
        if expected_period:
            return str(expected_period)

        parsed = OfficialChinaProvider._parse_year_month(html)
        if parsed is not None:
            return parsed

        return reference_date[:7]

    @staticmethod
    def _parse_year_month(html):
        normalized = OfficialChinaProvider._normalize_text(html)
        match = re.search(r"(20\d{2})年1[—-](\d{1,2})月", normalized)
        if match:
            return "{0}-{1:02d}".format(int(match.group(1)), int(match.group(2)))
        match = re.search(r"(20\d{2})年(\d{1,2})月份", html)
        if match:
            return "{0}-{1:02d}".format(int(match.group(1)), int(match.group(2)))
        match = re.search(r"(20\d{2})年(\d{1,2})月", normalized)
        if match:
            return "{0}-{1:02d}".format(int(match.group(1)), int(match.group(2)))
        return None

    @staticmethod
    def _evidence(html):
        normalized = OfficialChinaProvider._normalize_text(html)
        return normalized[:240]

    @staticmethod
    def _normalize_text(text):
        raw = str(text or "")
        raw = re.sub(
            r"<meta\b[^>]*\bcontent=[\"']([^\"']+)[\"'][^>]*>",
            r" \1 ",
            raw,
            flags=re.IGNORECASE,
        )
        without_tags = re.sub(r"<[^>]+>", " ", raw)
        unescaped = html_lib.unescape(without_tags)
        return re.sub(r"\s+", " ", unescaped).strip()

    @staticmethod
    def _find_link(
        html,
        base_url,
        *,
        include_tokens,
        optional_tokens=(),
        exclude_tokens=(),
        target_date=None,
        date_match_mode="exact",
    ):
        pattern = re.compile(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.DOTALL)
        for match in pattern.finditer(html):
            href = match.group(1)
            label = OfficialChinaProvider._normalize_text(match.group(2))
            title_match = re.search(
                r"title=[\"']([^\"']+)[\"']",
                match.group(0),
                flags=re.IGNORECASE,
            )
            if title_match:
                label = "{0} {1}".format(label, html_lib.unescape(title_match.group(1)))
            if not all(token in label for token in include_tokens):
                continue
            if optional_tokens and not any(token in label for token in optional_tokens):
                continue
            if any(token in label for token in exclude_tokens):
                continue
            candidate_url = urljoin(base_url, href)
            if candidate_url.rstrip("/") == str(base_url or "").rstrip("/"):
                continue
            if not OfficialChinaProvider._link_matches_date(
                label,
                candidate_url,
                target_date,
                date_match_mode,
            ):
                continue
            return candidate_url
        return None

    @staticmethod
    def _nbs_paginated_urls(base_url):
        root = base_url.rstrip("/")
        return ["{0}/index_{1}.html".format(root, page) for page in range(1, 4)]


def build_provider() -> OfficialChinaProvider:
    return OfficialChinaProvider()
