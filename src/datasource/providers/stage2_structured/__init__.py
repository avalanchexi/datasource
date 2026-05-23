"""Structured Stage2 provider foundation."""

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.registry import (
    StructuredProviderRegistry,
    build_default_registry,
)

__all__ = [
    "StructuredProviderError",
    "StructuredResult",
    "Stage2StructuredProvider",
    "StructuredProviderRegistry",
    "build_default_registry",
]
