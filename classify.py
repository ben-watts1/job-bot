"""Classification logic for Eng/Product jobs while excluding GTM roles."""

from __future__ import annotations

import re
from typing import Literal

Category = Literal["eng", "product", "ignore"]

ENG_KEYWORDS = [
    "software engineer",
    "backend",
    "front ?end",
    "full ?stack",
    "platform",
    "infrastructure",
    "infra",
    "devops",
    "sre",
    "data engineer",
    "ml engineer",
    "machine learning engineer",
    "security",
    "mobile",
    "ios",
    "android",
    "qa",
    "test engineer",
]

PRODUCT_KEYWORDS = [
    "product manager",
    "technical product manager",
    "\\btpm\\b",
    "product owner",
    "product analyst",
    "product ops",
]

GTM_KEYWORDS = [
    "sales",
    "account executive",
    "\\bae\\b",
    "\\bsdr\\b",
    "\\bbdr\\b",
    "marketing",
    "demand gen",
    "customer success",
    "\\bcsm\\b",
    "account manager",
    "partnerships",
    "revenue",
    "revops",
    "sales ops",
    "solutions consultant",
    "implementation",
    "support",
]


def _norm(*parts: str | None) -> str:
    merged = " ".join(p for p in parts if p)
    return re.sub(r"\s+", " ", merged).strip().lower()


def _contains_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def classify_job(title: str, team: str | None = None) -> Category:
    """Return eng/product/ignore with GTM exclusion precedence."""
    blob = _norm(title, team)

    if _contains_any(blob, GTM_KEYWORDS):
        return "ignore"

    # Growth is GTM-only if tied to marketing terms.
    if "growth" in blob and any(k in blob for k in ("marketing", "demand", "acquisition", "seo", "sem")):
        return "ignore"

    if _contains_any(blob, ENG_KEYWORDS):
        return "eng"

    if _contains_any(blob, PRODUCT_KEYWORDS):
        return "product"

    return "ignore"
