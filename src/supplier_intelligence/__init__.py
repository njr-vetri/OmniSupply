"""
Supplier Intelligence package for OmniSupply platform.
Provides quantitative supplier risk scoring and factor attribution.
"""

from .scoring import (
    score_suppliers,
    DEFAULT_WEIGHTS,
    DEFAULT_ORIENTATIONS,
    RISK_LEVEL_LOW,
    RISK_LEVEL_MEDIUM,
    RISK_LEVEL_HIGH,
    RISK_LEVEL_CRITICAL,
    RISK_LEVEL_UNKNOWN,
)

__all__ = [
    "score_suppliers",
    "DEFAULT_WEIGHTS",
    "DEFAULT_ORIENTATIONS",
    "RISK_LEVEL_LOW",
    "RISK_LEVEL_MEDIUM",
    "RISK_LEVEL_HIGH",
    "RISK_LEVEL_CRITICAL",
    "RISK_LEVEL_UNKNOWN",
]
