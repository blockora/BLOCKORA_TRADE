"""Tests: data models — missing data stays None, spread math, quality propagation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import (Decision, Direction, DataQuality, FeatureVector,
                         OptionQuote, Outcome, Quality)


def test_quote_missing_fields_are_none():
    q = OptionQuote(strike=24500.0, option_type="CE", expiry="2026-10-01")
    assert q.ltp is None and q.bid is None and q.iv is None and q.volume is None
    assert q.spread_pct is None


def test_quote_spread_pct():
    q = OptionQuote(strike=24500.0, option_type="CE", expiry="2026-10-01", bid=9.90, ask=10.10)
    assert abs(q.spread_pct - (0.20 / 10.0 * 100)) < 1e-9


def test_quote_spread_invalid_bid_ask_returns_none():
    q = OptionQuote(strike=24500.0, option_type="CE", expiry="2026-10-01", bid=0.0, ask=10.0)
    assert q.spread_pct is None
    q2 = OptionQuote(strike=24500.0, option_type="CE", expiry="2026-10-01", bid=11.0, ask=10.0)
    assert q2.spread_pct is None


def test_quality_defaults_and_degradation():
    dq = DataQuality(source="TEST")
    assert dq.status == Quality.OK
    d2 = dq.degraded("old data")
    assert d2.status == Quality.DEGRADED and d2.reason == "old data"
    assert dq.status == Quality.OK  # original untouched


def test_feature_vector_payload_drops_private_only():
    fv = FeatureVector(strike=24500.0, option_type="CE", expiry="2026-10-01")
    payload = fv.to_payload()
    assert payload["strike"] == 24500.0
    assert "data_quality_flags" in payload


def test_enums():
    assert Direction.BULLISH.value == "BULLISH"
    assert Outcome.LOSS.value == "LOSS"
    assert Decision.NO_TRADE.value == "NO_TRADE"
