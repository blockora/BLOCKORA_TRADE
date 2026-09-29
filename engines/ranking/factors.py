"""Single source of truth for the adaptive strike ranking factors.

The ten factors, their maximum point values and the thresholds that trigger a
"why this strike" reason used to be written down twice: once as comments in
StrikeRankingEngine._score_strike() and once as a hardcoded table in the
dashboard. Those two copies could drift apart silently, so the display could
claim a weight the scorer never used.

This module is the one authoritative definition. The scorer imports it to
build its scores, and the dashboard imports it to render them. Changing a
maximum here changes both, with no second edit anywhere else.

Immutability is deliberate: FACTORS is a read-only mapping of frozen
records, so no caller can mutate the weights at runtime and leave the
scorer and the UI disagreeing.

The maximum values are not a policy choice, they are the observed caps of
each scorer branch. They are asserted against the live scorer in
tests/test_ranking_factors_source_of_truth.py.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import NamedTuple, Optional


class FactorSpec(NamedTuple):
    """One ranking factor.

    key:     the name used as the key in the candidate's `scores` dict
    label:   human-readable name for the dashboard
    maximum: the highest number of points this factor can contribute
    reason_threshold: score at or above which the scorer records a "why this
        strike" reason, or None when the factor records no threshold reason.
        This is NOT always equal to `maximum`.
    """

    key: str
    label: str
    maximum: int
    reason_threshold: Optional[int] = None


FACTOR_SPECS = (
    FactorSpec("moneyness", "Moneyness", 15),
    FactorSpec("gamma", "Gamma Impact", 10, reason_threshold=12),
    FactorSpec("move_fit", "Expected-Move Fit", 15, reason_threshold=10),
    FactorSpec("oi", "OI Quality", 12),
    FactorSpec("volume", "Volume Velocity", 10, reason_threshold=8),
    FactorSpec("spread", "Spread Efficiency", 8),
    FactorSpec("trend", "Trend Confluence", 12),
    FactorSpec("vwap", "VWAP Distance", 8),
    FactorSpec("max_pain", "Max Pain", 5),
    FactorSpec("historical", "Historical Win Rate", 5),
)

# Read-only view: FACTORS["gamma"].maximum is the only way to read a weight.
FACTORS = MappingProxyType({spec.key: spec for spec in FACTOR_SPECS})

#: Factor keys in scoring order, for iteration that must stay stable.
FACTOR_KEYS = tuple(spec.key for spec in FACTOR_SPECS)

#: Maximum achievable total, i.e. the denominator for a 0-100 score.
MAX_TOTAL_SCORE = sum(spec.maximum for spec in FACTOR_SPECS)


def maximum_for(key: str) -> int:
    """Maximum points a factor can contribute.

    Raises KeyError for an unknown factor rather than defaulting, so a typo
    in the display or the scorer surfaces immediately instead of silently
    rendering a wrong weight.
    """
    return FACTORS[key].maximum


__all__ = [
    "FACTOR_SPECS",
    "FACTORS",
    "FACTOR_KEYS",
    "MAX_TOTAL_SCORE",
    "FactorSpec",
    "maximum_for",
]
