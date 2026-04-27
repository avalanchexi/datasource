"""Shared text marker predicates."""

from __future__ import annotations

import re


def contains_ytd_marker(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(token in lowered for token in ["累计", "年初至今", "ytd", "year-to-date"]):
        return True
    return bool(re.search(r"1\s*(?:-|—|~|至|到)\s*\d{1,2}\s*月", lowered))
