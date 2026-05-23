"""Base contracts for Stage2 structured data providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Set


class StructuredProviderError(Exception):
    """Provider-specific error that can be serialized into Stage2 diagnostics."""

    def __init__(
        self,
        provider: str,
        indicator_key: str,
        reason: str,
        message: str,
        diagnostics: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.indicator_key = indicator_key
        self.reason = reason
        self.message = message
        self.diagnostics = dict(diagnostics or {})

    def to_diagnostics(self) -> Dict[str, Any]:
        diagnostics = dict(self.diagnostics)
        diagnostics.update(
            {
                "structured_provider": self.provider,
                "structured_provider_indicator_key": self.indicator_key,
                "structured_provider_error": self.reason,
                "structured_provider_message": self.message,
            }
        )
        return diagnostics


@dataclass(frozen=True)
class StructuredResult:
    """Normalized output from a structured provider."""

    provider: str
    indicator_key: str
    category: str
    payload: Mapping[str, Any]
    source: str
    source_url: str
    source_tier: str
    as_of_date: Optional[str] = None
    confidence: Optional[float] = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    @property
    def note(self) -> str:
        return f"structured_provider:{self.provider}"

    def to_extraction(self) -> Dict[str, Any]:
        extraction = dict(self.payload)
        extraction.update(
            {
                "indicator_key": self.indicator_key,
                "category": self.category,
                "source": self.source,
                "source_url": self.source_url,
                "source_tier": self.source_tier,
                "note": self.note,
            }
        )
        if self.as_of_date is not None:
            extraction["as_of_date"] = self.as_of_date
        if self.confidence is not None:
            extraction["confidence"] = self.confidence
        if self.diagnostics:
            extraction["diagnostics"] = dict(self.diagnostics)
        return extraction

    def audit_snippets(self) -> Iterable[Dict[str, Any]]:
        return [
            {
                "title": self.source,
                "url": self.source_url,
                "content": self.note,
                "score": self.confidence,
                "source_tier": self.source_tier,
                "as_of_date": self.as_of_date,
            }
        ]

    def to_websearch_record(self, task: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "indicator_key": self.indicator_key,
            "category": self.category,
            "task": dict(task),
            "search_backend": "structured",
            "result_type": "structured_success",
            "provider": self.provider,
            "source": self.source,
            "source_url": self.source_url,
            "source_tier": self.source_tier,
            "as_of_date": self.as_of_date,
            "confidence": self.confidence,
            "note": self.note,
            "payload": dict(self.payload),
            "diagnostics": dict(self.diagnostics),
            "results": list(self.audit_snippets()),
        }


class Stage2StructuredProvider:
    name: str
    supported_keys: Set[str]

    async def fetch(
        self,
        task: Mapping[str, Any],
        market_payload: Mapping[str, Any],
        reference_date: str,
    ) -> StructuredResult:
        raise NotImplementedError(
            "Stage2StructuredProvider.fetch must be implemented by subclasses"
        )
