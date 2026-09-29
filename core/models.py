"""BLOCKORA_TRADE v3 — typed data models shared by every pipeline stage.

Missing data is always None (never zero-filled). Quality metadata rides on
every market-data object (docs/SCHEMA.md data models section).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Direction(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGE = "RANGE"
    UNCERTAIN = "UNCERTAIN"


class Quality(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    MISSING = "MISSING"


class Outcome(str, Enum):
    WIN_T1 = "WIN_T1"
    WIN_T2 = "WIN_T2"
    WIN_T3 = "WIN_T3"
    LOSS = "LOSS"
    TIMEOUT = "TIMEOUT"


class Decision(str, Enum):
    RECOMMENDATION = "RECOMMENDATION"
    NO_TRADE = "NO_TRADE"


@dataclass
class DataQuality:
    """Provenance metadata attached to every fetched/derived object."""
    status: Quality = Quality.OK
    data_ts: str | None = None      # source timestamp
    received_ts: str | None = None
    latency_ms: float | None = None
    source: str | None = None
    reason: str | None = None

    def degraded(self, reason: str) -> "DataQuality":
        return DataQuality(Quality.DEGRADED, self.data_ts, self.received_ts,
                           self.latency_ms, self.source, reason)


@dataclass
class OptionQuote:
    """One option contract quote. None = not provided by source (never zero-filled)."""
    strike: float
    option_type: str                 # CE / PE
    expiry: str
    ltp: float | None = None
    bid: float | None = None
    ask: float | None = None
    iv: float | None = None
    volume: int | None = None
    oi: int | None = None
    change_oi: int | None = None
    quality: DataQuality = field(default_factory=DataQuality)

    @property
    def spread_pct(self) -> float | None:
        if self.bid is None or self.ask is None or self.bid <= 0 or self.ask < self.bid:
            return None
        mid = (self.bid + self.ask) / 2.0
        return (self.ask - self.bid) / mid * 100.0 if mid > 0 else None


@dataclass
class UnderlyingTick:
    symbol: str
    ltp: float | None
    change_pct: float | None
    quality: DataQuality = field(default_factory=DataQuality)


@dataclass
class Candle:
    symbol: str
    timeframe: str
    bar_ts: str                      # open time, UTC ISO
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None
    quality: DataQuality = field(default_factory=DataQuality)


@dataclass
class FeatureVector:
    """Per-strike feature vector (docs/SCHEMA.md features table)."""
    strike: float
    option_type: str
    expiry: str
    distance_atm: float | None = None
    ltp: float | None = None
    volume: int | None = None
    oi: int | None = None
    change_oi: int | None = None
    bid: float | None = None
    ask: float | None = None
    spread_pct: float | None = None
    iv: float | None = None
    iv_rank: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    underlying_price: float | None = None
    momentum_5m: float | None = None
    trend_flag: str | None = None
    vwap_rel: str | None = None      # ABOVE / BELOW
    ema_rel: str | None = None
    market_structure: str | None = None
    volatility_state: str | None = None
    liquidity_score: float | None = None
    chain_confirmation: str | None = None
    risk_reward: float | None = None
    data_quality_flags: dict[str, str] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


@dataclass
class ComponentScore:
    family: str
    component: str
    score: float | None              # 0..10, None if UNAVAILABLE
    confidence: str = "REAL"         # REAL / ESTIMATED / UNAVAILABLE


@dataclass
class StrikeCandidate:
    features: FeatureVector
    family_scores: dict[str, float] = field(default_factory=dict)
    components: list[ComponentScore] = field(default_factory=list)
    model_score: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)   # independent/correlated/confirm groups
    filter_results: dict[str, tuple[bool, str | None]] = field(default_factory=dict)


@dataclass
class SideScore:
    side: str                        # CALL / PUT
    score: float                     # 0..100
    valid: bool
    reasons: list[str] = field(default_factory=list)
    contributing: dict[str, float] = field(default_factory=dict)


@dataclass
class TradePlan:
    entry: float
    stop_loss: float
    t1: float
    t2: float
    t3: float
    risk_pct: float | None = None
    reward_risk: float | None = None
    expected_hold_min: int | None = None


@dataclass
class Recommendation:
    decision: Decision
    decision_ts: str
    market_bias: Direction | None = None
    side: str | None = None
    strike: float | None = None
    expiry: str | None = None
    plan: TradePlan | None = None
    model_score: float | None = None
    calibrated_confidence: float | None = None
    calibrated_state: str = "UNAVAILABLE"
    trade_grade: str | None = None
    key_reasons: list[str] = field(default_factory=list)
    rejected_alternatives: list[str] = field(default_factory=list)
    no_trade_reason: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
