"""Official China provider for Stage2 monetary, forex, and macro values."""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Dict, Optional

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.http_fetcher import (
    fetch_text as default_fetch_text,
)
from datasource.providers.stage2_structured.source_tiers import (
    classify_structured_source_tier,
)
from datasource.utils.key_aliases import canonical_monetary_key


FetchText = Callable[[str, Optional[Dict[str, Any]]], Awaitable[str]]

REVERSE_REPO_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125434/125798/index.html"
MLF_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125437/125446/125873/index.html"
USDCNY_URL = "https://www.chinamoney.com.cn/chinese/bkccpr/"
NBS_URL = "https://www.stats.gov.cn/sj/zxfb/"
RESERVE_RATIO_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/125838/index.html"


class OfficialChinaProvider(Stage2StructuredProvider):
    name = "official_china"

    REVERSE_REPO_URL = REVERSE_REPO_URL
    MLF_URL = MLF_URL
    USDCNY_URL = USDCNY_URL
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

    def __init__(self, fetch_text: FetchText = default_fetch_text) -> None:
        self._fetch_text = fetch_text

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

        result = self._parse_result(key, raw_key, task, html, url, reference_date)
        if result is None:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=raw_key,
                reason="missing_value",
                message="Official China source did not contain a parseable value",
                diagnostics={"url": url, "evidence_text": self._evidence(html)},
            )
        return result

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
            return self._parse_monetary_result(key, raw_key, html, url, reference_date)
        if key == "USDCNY":
            return self._parse_usdcny_result(raw_key, html, url, reference_date)
        if key in {"industrial", "industrial_sales"}:
            return self._parse_macro_result(key, raw_key, task, html, url, reference_date)
        return None

    def _parse_monetary_result(self, key, raw_key, html, url, reference_date):
        value = self._parse_rate(html)
        if value is None:
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

        return StructuredResult(
            provider=self.name,
            indicator_key=raw_key,
            category="monetary_policy",
            payload=payload,
            source="Official China structured source",
            source_url=url,
            source_tier=classify_structured_source_tier(url),
            as_of_date=self._parse_date(html) or reference_date,
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
            payload={"value": value, "unit": "", "is_estimated": False},
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
        patterns = [
            r"(?:中标利率|利率|存款准备金率)[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*%",
            r"(?:中标利率|利率|存款准备金率)[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*％",
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return float(match.group(1))
        return None

    @staticmethod
    def _parse_operation_amount(html):
        patterns = [
            r"(?:逆回购操作|MLF\）操作|MLF\)操作|中期借贷便利（MLF）操作|中期借贷便利\(MLF\)操作)([0-9,]+(?:\.[0-9]+)?)\s*亿元",
            r"操作([0-9,]+(?:\.[0-9]+)?)\s*亿元",
        ]
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.IGNORECASE)
            if match:
                return float(match.group(1).replace(",", ""))
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
        if key == "industrial":
            patterns = [
                r"规模以上工业增加值同比实际增长\s*([0-9]+(?:\.[0-9]+)?)\s*%",
                r"工业增加值同比[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*%",
            ]
        else:
            patterns = [
                r"营业收入[^0-9]{0,30}([0-9]+(?:\.[0-9]+)?)\s*%",
                r"销售收入[^0-9]{0,30}([0-9]+(?:\.[0-9]+)?)\s*%",
            ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return float(match.group(1))
        return None

    @staticmethod
    def _parse_date(html):
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
        match = re.search(r"(20\d{2})年(\d{1,2})月份", html)
        if match:
            return "{0}-{1:02d}".format(int(match.group(1)), int(match.group(2)))
        match = re.search(r"(20\d{2})年(\d{1,2})月", html)
        if match:
            return "{0}-{1:02d}".format(int(match.group(1)), int(match.group(2)))
        return None

    @staticmethod
    def _evidence(html):
        normalized = re.sub(r"\s+", " ", html).strip()
        return normalized[:240]


def build_provider() -> OfficialChinaProvider:
    return OfficialChinaProvider()
