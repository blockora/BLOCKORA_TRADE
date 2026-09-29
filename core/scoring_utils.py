"""BLOCKORA_TRADE v3 — shared scoring normalization helpers.

Every component score is normalized into [0, 10]. These helpers are the ONLY
way components are normalized, so behavior is uniform and testable.
5.0 means "no information / neutral" — never used to mask missing data
(see docs/SCORING.md section 2).
"""
from __future__ import annotations

from typing import Sequence


def clamp(value: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, value))


def band_score(value: float, bands: Sequence[Sequence[float]]) -> float:
    """Piecewise band lookup: bands = [[score, upper], ...] ascending.

    Example (delta fit): [[2, 0.20], [4, 0.30], [7, 0.40], [10, 0.60],
                          [7, 0.70], [4, 0.80], [2, 9.99]]
    returns the score of the first band whose upper bound >= value.
    """
    for score, upper in bands:
        if value <= upper:
            return float(score)
    return float(bands[-1][0]) if bands else 5.0


def threshold_score(value: float, good: float, bad: float) -> float:
    """Linear interpolation: value >= good -> 10; value <= bad -> 0; else linear."""
    if good == bad:
        return 10.0 if value >= good else 0.0
    frac = (value - bad) / (good - bad)
    return clamp(frac * 10.0)


def binary_score(flag: bool, hit: float = 10.0, miss: float = 0.0) -> float:
    return hit if flag else miss


def rr_score(ratio: float) -> float:
    """Spec section 1.7 mapping (kept as HEURISTIC default)."""
    if ratio >= 3.0:
        return 10.0
    if ratio >= 2.0:
        return 8.0
    if ratio >= 1.5:
        return 6.0
    return 3.0


def delta_fit_score(abs_delta: float) -> float:
    """Spec section 1.2 mapping (kept as HEURISTIC default)."""
    if 0.40 <= abs_delta <= 0.60:
        return 10.0
    if 0.30 <= abs_delta < 0.40 or 0.60 < abs_delta <= 0.70:
        return 7.0
    if 0.20 <= abs_delta < 0.30 or 0.70 < abs_delta <= 0.80:
        return 4.0
    return 2.0


def round_tick(price: float, tick: float = 0.05) -> float:
    return round(round(price / tick) * tick, 2)
