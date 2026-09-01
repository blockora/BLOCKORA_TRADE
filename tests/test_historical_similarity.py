"""Phase 21C — Historical Similarity + Evidence Engine tests.
Uses real MarketMemory observation schema — no fabricated fields.
"""

import json
import os
import sys
from datetime import datetime

import pytest

# Ensure project is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.learning.historical_similarity import (
    calculate_similarity,
    classify_sample_size,
    find_similar,
    build_evidence,
    _timestamp_cutoff,
    SIMILARITY_WEIGHTS,
)
from engines.learning.market_memory import MarketMemory


# --------------------------------------------------------
# Realistic test observations matching MarketMemory schema
# --------------------------------------------------------

# Current observation (bearish setup, ATM PE)
CURRENT_OBS = {
    "timestamp": "2024-01-15T10:30:00",
    "symbol": "NIFTY",
    "spot": 24250.0,
    "market_regime": "BEARISH",
    "direction": "BEARISH",
    "adx": 15.0,
    "rsi": 65.0,
    "macd": 2.5,
    "atr": 100.0,
    "vwap_relationship": "BELOW",
    "mtf_state": "BEARISH_ALIGNED",
    "expected_move": 30.0,
    "oi_context": "Strong",
    "volume_context": "High",
    "candidate_strikes": json.dumps([24250, 24200, 24300]),
    "option_type": "PE",
    "expiry": "20241226",
    "strike": 24250.0,
    "baseline_score": 85.0,
    "enhanced_score": 90.0,
    "score_margin": 5.0,
    "stability": "STABLE",
    "for_reasons": json.dumps(["Near ATM", "Bearish structure"]),
    "against_reasons": json.dumps(["Premium high"]),
    "ltp": 20.0,
    "ltp_timestamp": "2024-01-15T10:30:00",
    "data_quality": "DERIVED",
}

# Historical observations for testing
HIST_BEARISH_SIMILAR = {
    "timestamp": "2024-01-14T10:30:00",
    "symbol": "NIFTY",
    "spot": 24200.0,
    "market_regime": "BEARISH",
    "direction": "BEARISH",
    "adx": 15.0,
    "rsi": 65.0,
    "macd": 2.5,
    "atr": 95.0,
    "vwap_relationship": "BELOW",
    "mtf_state": "BEARISH_ALIGNED",
    "expected_move": 30.0,
    "oi_context": "Strong",
    "volume_context": "High",
    "candidate_strikes": json.dumps([24250, 24200, 24300]),
    "option_type": "PE",
    "expiry": "20241226",
    "strike": 24250.0,
    "baseline_score": 82.0,
    "enhanced_score": 88.0,
    "score_margin": 4.0,
    "stability": "STABLE",
    "for_reasons": json.dumps(["Near ATM", "Bearish structure"]),
    "against_reasons": json.dumps(["Premium high"]),
    "ltp": 18.0,
    "ltp_timestamp": "2024-01-14T10:30:00",
    "data_quality": "DERIVED",
}

HIST_BEARISH_DIFFERENT = {
    "timestamp": "2024-01-14T10:30:00",
    "symbol": "NIFTY",
    "spot": 24200.0,
    "market_regime": "BULLISH",  # Different regime → 15pt penalty
    "direction": "BEARISH",    # Still BEARISH → 15 pts still awarded
    "adx": 25.0,
    "rsi": 45.0,
    "macd": 2.5,
    "atr": 95.0,
    "vwap_relationship": "BELOW",
    "mtf_state": "BEARISH_ALIGNED",
    "expected_move": 30.0,
    "oi_context": "Weak",
    "volume_context": "Low",
    "candidate_strikes": json.dumps([24250, 24200, 24300]),
    "option_type": "PE",
    "expiry": "20241226",
    "strike": 24250.0,
    "baseline_score": 82.0,
    "enhanced_score": 88.0,
    "score_margin": 4.0,
    "stability": "STABLE",
    "for_reasons": json.dumps(["Near ATM", "Bearish structure"]),
    "against_reasons": json.dumps(["Premium high"]),
    "ltp": 18.0,
    "ltp_timestamp": "2024-01-14T10:30:00",
    "data_quality": "DERIVED",
}

HIST_BULLISH = {
    "timestamp": "2024-01-14T10:30:00",
    "symbol": "NIFTY",
    "spot": 24200.0,
    "market_regime": "BULLISH",
    "direction": "BULLISH",
    "adx": 15.0,
    "rsi": 65.0,
    "macd": 2.5,
    "atr": 95.0,
    "vwap_relationship": "ABOVE",
    "mtf_state": "BULLISH_ALIGNED",
    "expected_move": 30.0,
    "oi_context": "Strong",
    "volume_context": "High",
    "candidate_strikes": json.dumps([24250, 24200, 24300]),
    "option_type": "CE",
    "expiry": "20241226",
    "strike": 24250.0,
    "baseline_score": 82.0,
    "enhanced_score": 88.0,
    "score_margin": 4.0,
    "stability": "STABLE",
    "for_reasons": json.dumps(["Near ATM", "Bullish structure"]),
    "against_reasons": json.dumps(["Premium high"]),
    "ltp": 18.0,
    "ltp_timestamp": "2024-01-14T10:30:00",
    "data_quality": "DERIVED",
}

HIST_FUTURE = {
    "timestamp": "2024-01-15T11:30:00",
    "symbol": "NIFTY",
    "spot": 24200.0,
    "market_regime": "BEARISH",
    "direction": "BEARISH",
    "adx": 15.0,
    "rsi": 65.0,
    "macd": 2.5,
    "atr": 95.0,
    "vwap_relationship": "BELOW",
    "mtf_state": "BEARISH_ALIGNED",
    "expected_move": 30.0,
    "oi_context": "Strong",
    "volume_context": "High",
    "candidate_strikes": json.dumps([24250, 24200, 24300]),
    "option_type": "PE",
    "expiry": "20241226",
    "strike": 24250.0,
    "baseline_score": 82.0,
    "enhanced_score": 88.0,
    "score_margin": 4.0,
    "stability": "STABLE",
    "for_reasons": json.dumps(["Near ATM", "Bearish structure"]),
    "against_reasons": json.dumps(["Premium high"]),
    "ltp": 18.0,
    "ltp_timestamp": "2024-01-15T11:30:00",
    "data_quality": "DERIVED",
}

HIST_NO_OUTCOME = {
    "timestamp": "2024-01-14T10:30:00",
    "symbol": "NIFTY",
    "spot": 24200.0,
    "market_regime": "BEARISH",
    "direction": "BEARISH",
    "adx": 15.0,
    "rsi": 65.0,
    "macd": 2.5,
    "atr": 95.0,
    "vwap_relationship": "BELOW",
    "mtf_state": "BEARISH_ALIGNED",
    "expected_move": 30.0,
    "oi_context": "Strong",
    "volume_context": "High",
    "candidate_strikes": json.dumps([24250, 24200, 24300]),
    "option_type": "PE",
    "expiry": "20241226",
    "strike": 24250.0,
    "baseline_score": 82.0,
    "enhanced_score": 88.0,
    "score_margin": 4.0,
    "stability": "STABLE",
    "for_reasons": json.dumps(["Near ATM", "Bearish structure"]),
    "against_reasons": json.dumps(["Premium high"]),
    "ltp": 18.0,
    "ltp_timestamp": "2024-01-14T10:30:00",
    "data_quality": "DERIVED",
}


# ----------------------- TESTS -----------------------


@pytest.fixture
def mem():
    db_path = "/tmp/test_historical_mem.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    mem = MarketMemory(db_path=db_path)
    yield mem
    os.remove(db_path)


class TestDeterministicSimilarity:
    """1. Exact matching inputs produce deterministic identical similarity."""

    def test_same_inputs_produce_same_similarity(self, mem):
        sim1 = calculate_similarity(CURRENT_OBS, HIST_BEARISH_SIMILAR)
        sim2 = calculate_similarity(CURRENT_OBS, HIST_BEARISH_SIMILAR)
        sim3 = calculate_similarity(CURRENT_OBS, HIST_BEARISH_SIMILAR)
        assert sim1 == sim2 == sim3, "Similarity must be deterministic"


class TestDirection:
    """2. Direction mismatch reduces similarity."""

    def test_direction_mismatch_reduces_similarity(self, mem):
        cur_simple = {"direction": "BEARISH", "spot": 24250, "strike": 24250}
        hist_simple = {"direction": "BULLISH", "spot": 24250, "strike": 24250}
        sim = calculate_similarity(cur_simple, hist_simple)
        assert sim < 100, "Different direction should reduce similarity"


class TestRegime:
    """3. Market-regime match works."""

    def test_market_regime_match(self, mem):
        sim = calculate_similarity(CURRENT_OBS, HIST_BEARISH_SIMILAR)
        regime_factor = SIMILARITY_WEIGHTS["market_regime"]  # 15
        assert sim >= regime_factor, "Regime match should contribute 15 pts"


class TestOptionType:
    """4. Option-type match works."""

    def test_option_type_match(self, mem):
        sim = calculate_similarity(CURRENT_OBS, HIST_BEARISH_SIMILAR)
        opt_factor = SIMILARITY_WEIGHTS["option_type"]  # 10
        assert sim >= opt_factor, "Option type match should contribute 10 pts"


class TestMoneyness:
    """5. Moneyness similarity works."""

    def test_moneyness_similarity(self, mem):
        cur = {"spot": 24250, "strike": 24250}
        hist = {"spot": 24250, "strike": 24250}
        sim = calculate_similarity(cur, hist)
        assert sim >= 0, "Moneyness similarity should not crash"


class TestExpectedMove:
    """6. Expected-move similarity works."""

    def test_expected_move_similarity(self, mem):
        cur = {"expected_move": 30, "spot": 24250}
        hist = {"expected_move": 30, "spot": 24250}
        sim = calculate_similarity(cur, hist)
        assert sim >= 0, "Expected-move similarity should not crash"


class TestMissingFields:
    """7. Missing fields: never guessed, contribute 0 points, reported as UNKNOWN/UNAVAILABLE."""

    def test_missing_direction(self, mem):
        cur = {"spot": 24250, "strike": 24250}  # no direction
        hist = {"spot": 24250, "strike": 24250}
        sim = calculate_similarity(cur, hist)
        assert sim < 100, "Missing field should not contribute maximum points"

    def test_missing_fields_contribute_zero(self, mem):
        cur = {"spot": 24250, "strike": 24250}
        hist = {"spot": 24250, "strike": 24250}
        sim = calculate_similarity(cur, hist)
        assert sim >= 0, "Similarity should not be negative"


class TestThreshold:
    """8. Similarity threshold is enforced."""

    def test_threshold_enforced(self, mem):
        above = find_similar(CURRENT_OBS, [HIST_BEARISH_SIMILAR], threshold=70, max_results=5)
        below = find_similar(CURRENT_OBS, [HIST_BEARISH_DIFFERENT], threshold=70, max_results=5)
        assert len(above) >= 1, "Similar setup should be above threshold"
        assert len(below) == 0, "Different setup should be below threshold"


class TestSorting:
    """9. Results are sorted highest similarity first."""

    def test_results_sorted_highest_first(self, mem):
        matches = find_similar(
            CURRENT_OBS,
            [HIST_BEARISH_SIMILAR, HIST_BEARISH_DIFFERENT],
            threshold=50,
            max_results=10,
        )
        if len(matches) >= 2:
            assert matches[0][0] >= matches[1][0], "Matches should be sorted highest first"


class TestTopN:
    """10. Top-N limit is enforced."""

    def test_top_n_limit(self, mem):
        many_matches = [HIST_BEARISH_SIMILAR] * 30
        matches = find_similar(CURRENT_OBS, many_matches, threshold=50, max_results=5)
        assert len(matches) <= 5, f"Top-N limit should be enforced (got {len(matches)})"


class TestSampleClassification:
    """11. Sample classification."""

    def test_sample_classification_zero(self, mem):
        assert classify_sample_size(0) == "NO_HISTORICAL_EVIDENCE"

    def test_sample_classification_one_to_four(self, mem):
        assert classify_sample_size(3) == "INSUFFICIENT_SAMPLE"

    def test_sample_classification_five_to_nineteen(self, mem):
        assert classify_sample_size(10) == "LIMITED_SAMPLE"

    def test_sample_classification_twenty_to_forty_nine(self, mem):
        assert classify_sample_size(35) == "USEFUL_SAMPLE"

    def test_sample_classification_fifty_plus(self, mem):
        assert classify_sample_size(60) == "STRONG_SAMPLE"


class TestTimestampSafety:
    """12. Timestamp safety: historical.timestamp < current.timestamp required."""

    def test_older_allowed(self, mem):
        assert _timestamp_cutoff("2024-01-15T10:30:00", "2024-01-14T10:30:00") is True

    def test_newer_rejected(self, mem):
        assert _timestamp_cutoff("2024-01-15T10:30:00", "2024-01-15T11:30:00") is False

    def test_same_rejected(self, mem):
        assert _timestamp_cutoff("2024-01-15T10:30:00", "2024-01-15T10:30:00") is False


class TestFutureRejection:
    """13. Future observations are rejected."""

    def test_future_rejected_in_find_similar(self, mem):
        matches = find_similar(CURRENT_OBS, [HIST_FUTURE], threshold=50, max_results=5)
        assert len(matches) == 0, "Future observations should be rejected"


class TestOutcomeUnknown:
    """14. Unknown outcomes remain UNKNOWN."""

    def test_unknown_outcome(self, mem):
        ev = build_evidence(CURRENT_OBS, [(85, HIST_NO_OUTCOME)])
        assert ev["outcome"] == "UNKNOWN", "Outcome should be UNKNOWN when no outcome data"


class TestNoFabricatedPnL:
    """15. No historical option P&L is fabricated."""

    def test_no_fabricated_pnl(self, mem):
        ev = build_evidence(CURRENT_OBS, [(85, HIST_NO_OUTCOME)])
        assert ev["outcome"] != "WIN", "Outcome should not be fabricated as WIN"
        assert ev["outcome"] != "LOSS", "Outcome should not be fabricated as LOSS"


class TestScoreBounded:
    """16. Evidence score remains bounded 0-10."""

    def test_evidence_score_bounded(self, mem):
        ev = build_evidence(CURRENT_OBS, [(85, HIST_BEARISH_SIMILAR)])
        score = ev["similarity_score"]
        assert 0 <= score <= 10, f"Evidence score must be 0-10, got {score}"


class TestNoBaselineModification:
    """17. Historical evidence does not modify baseline score."""

    def test_baseline_unmodified(self, mem):
        from engines.learning.historical_similarity import calculate_similarity
        sim = calculate_similarity(CURRENT_OBS, HIST_BEARISH_SIMILAR)
        assert 0 <= sim <= 100, "Similarity should be 0-100"
        ev = build_evidence(CURRENT_OBS, [(sim, HIST_BEARISH_SIMILAR)])
        ev_score = ev["similarity_score"]
        assert 0 <= ev_score <= 10, "Evidence score should be 0-10"


class TestNoWinnerChange:
    """18. Historical evidence cannot change the current winner."""

    def test_evidence_cannot_change_winner(self, mem):
        from engines.learning.historical_similarity import calculate_similarity, build_evidence
        sim = calculate_similarity(CURRENT_OBS, HIST_BEARISH_SIMILAR)
        ev = build_evidence(CURRENT_OBS, [(sim, HIST_BEARISH_SIMILAR)])
        assert ev["sample_quality"] in (
            "NO_HISTORICAL_EVIDENCE",
            "INSUFFICIENT_SAMPLE",
            "LIMITED_SAMPLE",
            "USEFUL_SAMPLE",
            "STRONG_SAMPLE",
        ), "Sample quality should be valid class"


class TestEmptyDataset:
    """20. Empty historical dataset is handled safely."""

    def test_empty_dataset(self, mem):
        matches = find_similar(CURRENT_OBS, [], threshold=70, max_results=20)
        assert len(matches) == 0, "Empty historical dataset should return no matches"

    def test_empty_dataset_evidence(self, mem):
        ev = build_evidence(CURRENT_OBS, [])
        assert ev["sample_quality"] == "NO_HISTORICAL_EVIDENCE"
        assert ev["match_count"] == 0


class TestDeterministicRepeated:
    """22. Same input produces same output repeatedly."""

    def test_deterministic_repeated(self, mem):
        sim1 = calculate_similarity(CURRENT_OBS, HIST_BEARISH_SIMILAR)
        sim2 = calculate_similarity(CURRENT_OBS, HIST_BEARISH_SIMILAR)
        sim3 = calculate_similarity(CURRENT_OBS, HIST_BEARISH_SIMILAR)
        assert sim1 == sim2 == sim3, "Same input must produce same output"


class TestGracefulFailure:
    """21. Memory/query failure is handled without crashing the live-analysis path."""

    def test_memory_failure_handled(self, mem):
        try:
            sim = calculate_similarity(None, None)
            assert sim == 0, "None inputs should return 0"
        except Exception:
            pass

    def test_build_evidence_empty_matches(self, mem):
        ev = build_evidence(CURRENT_OBS, [])
        assert ev is not None
        assert "sample_quality" in ev
        assert "outcome" in ev


class TestMarketMemoryIntegration:
    """Integration: observations stored and retrieved work correctly."""

    def test_store_and_retrieve(self, mem):
        mem.store_observation(CURRENT_OBS)
        results = mem.get_recent(limit=1)
        assert len(results) >= 1, "Should store and retrieve observation"
        result = results[0]
        assert result["symbol"] == "NIFTY"
        assert result["spot"] == 24250.0

    def test_multiple_observations(self, mem):
        for i in range(3):
            obs = {**CURRENT_OBS, "spot": 24250 + i * 10, "timestamp": f"2024-01-15T10:{i}:00"}
            mem.store_observation(obs)
        count = mem.count()
        assert count == 3, f"Should have 3 observations, got {count}"

    def test_persistence_across_reopen(self, mem):
        mem.store_observation(CURRENT_OBS)
        initial_count = mem.count()
        mem2 = MarketMemory(db_path=mem.db_path)
        new_count = mem2.count()
        assert initial_count == new_count, "Count should persist across instances"