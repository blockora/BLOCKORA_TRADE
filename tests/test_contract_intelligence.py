"""Phase 23 — Contract-Level Strike Intelligence tests.

Verifies the ContractIntelligenceEngine implementation.
No production logic modified. Baseline scores, enhanced scores, and winner
selection remain unchanged.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.ranking.contract_intelligence import (
    contract_identity,
    are_same_contract,
    contract_components,
    classify_quality,
    calculate_moneyness,
    oi_intelligence,
    volume_intelligence,
    premium_intelligence,
    bid_ask_intelligence,
    iv_intelligence,
    option_response_intelligence,
    response_consistency,
    move_fit,
    calculate_contract_evidence,
    calculate_contract_conviction,
    why_against_reasons,
    snapshot_from_analysis,
    contract_identity,
)


# ----------------------- Contract Identity Tests -----------------------

class TestContractIdentity:
    """Test exact contract identity handling."""

    def test_exact_contract_identity(self):
        """Same four components = same contract."""
        id1 = contract_identity("NIFTY", "18AUG2026", 24400.0, "PE")
        id2 = contract_identity("NIFTY", "18AUG2026", 24400.0, "PE")
        assert id1 == id2

    def test_different_strike_not_same(self):
        """Different strike = different contract."""
        id1 = contract_identity("NIFTY", "18AUG2026", 24400.0, "PE")
        id2 = contract_identity("NIFTY", "18AUG2026", 24450.0, "PE")
        assert id1 != id2

    def test_different_expiry_not_same(self):
        """Different expiry = different contract."""
        id1 = contract_identity("NIFTY", "25AUG2026", 24400.0, "PE")
        id2 = contract_identity("NIFTY", "18AUG2026", 24400.0, "PE")
        assert id1 != id2

    def test_different_option_type_not_same(self):
        """Different option type = different contract."""
        id1 = contract_identity("NIFTY", "18AUG2026", 24400.0, "PE")
        id2 = contract_identity("NIFTY", "18AUG2026", 24400.0, "CE")
        assert id1 != id2

    def test_different_symbol_not_same(self):
        """Different symbol = different contract."""
        id1 = contract_identity("NIFTY", "18AUG2026", 24400.0, "PE")
        id2 = contract_identity("BANKNIFTY", "18AUG2026", 24400.0, "PE")
        assert id1 != id2

    def test_are_same_contract_true(self):
        """are_same_contract returns True for identical contracts."""
        assert are_same_contract(
            "NIFTY | 18AUG2026 | 24400 | PE",
            "NIFTY | 18AUG2026 | 24400 | PE",
        ) is True

    def test_are_same_contract_false(self):
        """are_same_contract returns False for different contracts."""
        assert are_same_contract(
            "NIFTY | 18AUG2026 | 24400 | PE",
            "NIFTY | 18AUG2026 | 24450 | PE",
        ) is False


# ----------------------- Contract Components Tests -----------------------

class TestContractComponents:
    """Test contract identity parsing."""

    def test_parse_valid_identity(self):
        """Parse valid contract identity string."""
        symbol, expiry, strike, opt_type = contract_components(
            "NIFTY | 18AUG2026 | 24400 | PE"
        )
        assert symbol == "NIFTY"
        assert expiry == "18AUG2026"
        assert strike == 24400.0
        assert opt_type == "PE"

    def test_parse_identity_float_strike(self):
        """Parse identity with float strike."""
        symbol, expiry, strike, opt_type = contract_components(
            "NIFTY | 18AUG2026 | 24400.5 | PE"
        )
        assert strike == 24400.5


# ----------------------- Moneyness Tests -----------------------

class TestMoneyness:
    """Test moneyness calculation."""

    def test_itm_put(self):
        """PUT with strike below spot is ITM."""
        m = calculate_moneyness(strike=24350.0, spot=24400.0)
        assert m["classification"] == "ITM"
        assert m["atm_classification"] == "NEAR_ATM"

    def test_otm_put(self):
        """PUT with strike above spot is OTM."""
        m = calculate_moneyness(strike=24450.0, spot=24400.0)
        assert m["classification"] == "OTM"
        assert m["atm_classification"] == "NEAR_ATM"

    def test_atm(self):
        """Strike at or very close to spot is ATM."""
        m = calculate_moneyness(strike=24400.0, spot=24400.0)
        assert m["classification"] in ("ITM", "OTM", "ATM")
        assert m["atm_classification"] == "ATM"

    def test_wide_otm(self):
        """Far OTM strike."""
        m = calculate_moneyness(strike=24600.0, spot=24400.0)
        assert m["classification"] == "OTM"
        assert m["quality"] == "LOW"


# ----------------------- OI Intelligence Tests -----------------------

class TestOIIntelligence:
    """Test OI intelligence calculation."""

    def test_oi_real(self):
        """OI quality is REAL when OI available."""
        result = oi_intelligence(oi=9700.0, prev_oi=None)
        assert result["oi_quality"] == "REAL"
        assert result["oi_change"] == "UNAVAILABLE"  # no previous OI

    def test_oi_with_prev_real_change(self):
        """OI CHANGE is REAL when previous valid OI exists."""
        result = oi_intelligence(oi=10500.0, prev_oi=9700.0)
        assert result["oi_quality"] == "REAL"
        assert result["oi_change"] == 800.0
        assert result["oi_change_pct"] == pytest.approx(8.24, abs=0.1)

    def test_oi_current_unavailable_prev_exists(self):
        """OI CHANGE is UNAVAILABLE when current OI unavailable."""
        result = oi_intelligence(oi=0, prev_oi=9700.0)
        assert result["oi_change"] == "UNAVAILABLE"
        assert result["oi_change_pct"] == "UNAVAILABLE"

    def test_oi_both_zero(self):
        """OI quality UNAVAILABLE when OI is 0."""
        result = oi_intelligence(oi=0, prev_oi=0)
        assert result["oi_quality"] == "UNAVAILABLE"


# ----------------------- Volume Intelligence Tests -----------------------

class TestVolumeIntelligence:
    """Test volume intelligence calculation."""

    def test_volume_real(self):
        """Volume quality is REAL when volume available."""
        result = volume_intelligence(volume=8000.0, prev_volume=None)
        assert result["volume_quality"] == "REAL"
        assert result["volume_acceleration"] == "UNAVAILABLE"

    def test_volume_with_prev_acceleration(self):
        """Volume acceleration tracked when previous volume exists."""
        result = volume_intelligence(volume=12000.0, prev_volume=8000.0)
        assert result["volume_quality"] == "REAL"
        # Acceleration is ESTIMATED without second prior point
        assert result["volume_acceleration"] == "ESTIMATED"

    def test_volume_current_unavailable(self):
        """Volume acceleration UNAVAILABLE when current volume unavailable."""
        result = volume_intelligence(volume=None, prev_volume=8000.0)
        assert result["volume_acceleration"] == "UNAVAILABLE"


# ----------------------- Premium Intelligence Tests -----------------------

class TestPremiumIntelligence:
    """Test premium (LTP) intelligence calculation."""

    def test_premium_real(self):
        """LTP quality is REAL when LTP available."""
        result = premium_intelligence(ltp=91.0, prev_ltp=None)
        assert result["ltp_quality"] == "REAL"
        assert result["premium_response"] == "UNAVAILABLE"  # no previous

    def test_premium_with_prev_real_change(self):
        """Premium change is REAL when previous valid LTP exists."""
        result = premium_intelligence(ltp=91.0, prev_ltp=82.0)
        assert result["ltp_quality"] == "REAL"
        assert result["premium_response"] == 9.0
        assert result["premium_response_pct"] == pytest.approx(10.99, abs=0.1)

    def test_premium_current_unavailable(self):
        """Premium response UNAVAILABLE when current LTP unavailable."""
        result = premium_intelligence(ltp=0, prev_ltp=82.0)
        assert result["premium_response"] == "UNAVAILABLE"


# ----------------------- Bid/Ask Intelligence Tests -----------------------

class TestBidAskIntelligence:
    """Test bid/ask quality calculation."""

    def test_bid_ask_good(self):
        """Good spread when spread_pct <= 5."""
        result = bid_ask_intelligence(bid=88.0, ask=92.0, bid_ts="", ask_ts="")
        assert result["spread_quality"] == "GOOD"
        assert result["spread_pct"] <= 5

    def test_bid_ask_acceptable(self):
        """Acceptable spread when 5 < spread_pct <= 10."""
        result = bid_ask_intelligence(bid=88.0, ask=94.0, bid_ts="", ask_ts="")
        assert result["spread_quality"] == "ACCEPTABLE"
        assert 5 < result["spread_pct"] <= 10

    def test_bid_ask_wide(self):
        """Wide spread when spread_pct > 10."""
        result = bid_ask_intelligence(bid=88.0, ask=105.0, bid_ts="", ask_ts="")
        assert result["spread_quality"] == "WIDE"
        assert result["spread_pct"] > 10

    def test_bid_ask_unavailable(self):
        """UNAVAILABLE when bid or ask missing."""
        result = bid_ask_intelligence(bid=None, ask=92.0, bid_ts="", ask_ts="")
        assert result["spread_quality"] == "UNAVAILABLE"


# ----------------------- IV Intelligence Tests -----------------------

class TestIVIntelligence:
    """Test IV intelligence calculation."""

    def test_iv_real(self):
        """IV is REAL when available."""
        result = iv_intelligence(iv=15.5, prev_iv=None)
        assert result["iv_quality"] == "REAL"
        assert result["iv_change"] == "UNAVAILABLE"

    def test_iv_with_prev_real_change(self):
        """IV change is REAL when previous IV exists."""
        result = iv_intelligence(iv=16.0, prev_iv=15.5)
        assert result["iv_quality"] == "REAL"
        assert result["iv_change"] == 0.5
        assert result["iv_change_pct"] == pytest.approx(3.23, abs=0.1)

    def test_iv_unavailable(self):
        """IV is UNAVAILABLE when not provided."""
        result = iv_intelligence(iv=None, prev_iv=None)
        assert result["iv"] == "UNAVAILABLE"
        assert result["iv_quality"] == "UNAVAILABLE"


# ----------------------- Option Response Tests -----------------------

class TestOptionResponse:
    """Test observed option response calculation."""

    def test_positive_response(self):
        """Positive option response: underlying up, premium up."""
        result = option_response_intelligence(
            underlying_change=+20, premium_change=+9
        )
        assert result["underlying_change"] == 20
        assert result["premium_change"] == 9
        assert result["response_consistency"] == "CONSISTENT"

    def test_negative_response(self):
        """Negative option response: underlying down, premium down."""
        result = option_response_intelligence(
            underlying_change=-20, premium_change=-9
        )
        assert result["underlying_change"] == -20
        assert result["premium_change"] == -9
        assert result["response_consistency"] == "CONSISTENT"

    def test_cross_response(self):
        """Cross response: underlying up, premium down → MIXED."""
        result = option_response_intelligence(
            underlying_change=+20, premium_change=-9
        )
        assert result["response_consistency"] == "MIXED"

    def test_zero_underlying(self):
        """Zero underlying change → UNAVAILABLE ratio."""
        result = option_response_intelligence(
            underlying_change=0, premium_change=9
        )
        assert result["premium_response_ratio"] == "UNAVAILABLE"


# ----------------------- Response Consistency Tests -----------------------

class TestResponseConsistency:
    """Test response consistency from multiple observations."""

    def test_consistent_observations(self):
        """CONSISTENT when all observations CONSISTENT."""
        obs = [
            {"response_consistency": "CONSISTENT"},
            {"response_consistency": "CONSISTENT"},
            {"response_consistency": "CONSISTENT"},
        ]
        assert response_consistency(obs) == "CONSISTENT"

    def test_mixed_observations(self):
        """MIXED when observations mixed."""
        obs = [
            {"response_consistency": "CONSISTENT"},
            {"response_consistency": "MIXED"},
            {"response_consistency": "CONSISTENT"},
        ]
        assert response_consistency(obs) == "MIXED"

    def test_insufficient_observations(self):
        """UNAVAILABLE when fewer than 2 observations."""
        assert response_consistency([{"response_consistency": "CONSISTENT"}]) == "UNAVAILABLE"
        assert response_consistency([]) == "UNAVAILABLE"


# ----------------------- Move Fit Tests -----------------------

class TestMoveFit:
    """Test expected-move compatibility."""

    def test_excellent_fit(self):
        """Strike within 10% of expected move."""
        m = move_fit(strike=24400.0, spot=24400.0, expected_move=200)
        assert m["move_fit"] == 10
        assert m["move_fit_quality"] == "STRONG"

    def test_poor_fit(self):
        """Strike way beyond expected move."""
        m = move_fit(strike=24800.0, spot=24400.0, expected_move=200)
        assert m["move_fit"] <= 2

    def test_no_expected_move(self):
        """No expected move → UNAVAILABLE."""
        m = move_fit(strike=24400.0, spot=24400.0, expected_move=0)
        assert m["move_fit"] == 0
        assert m["move_fit_quality"] == "UNAVAILABLE"


# ----------------------- Contract Evidence Tests -----------------------

class TestContractEvidence:
    """Test contract evidence calculation."""

    def test_evidence_basic(self):
        """Basic contract evidence computation."""
        m = calculate_moneyness(24400.0, 24400.0)
        oi = oi_intelligence(9700.0, None)
        vol = volume_intelligence(8000.0, None)
        ba = bid_ask_intelligence(88.0, 92.0, "", "")
        iv = iv_intelligence(15.5, None)
        mf = move_fit(24400.0, 24400.0, 200)
        pre = premium_intelligence(91.0, None)
        resp = option_response_intelligence(20, 9)

        evidence = calculate_contract_evidence(
            moneyness=m, oi_result=oi, volume_result=vol,
            bid_ask_result=ba, iv_result=iv, move_fit_result=mf,
            premium_result=pre, response_result=resp,
        )
        assert 0 <= evidence["evidence_score"] <= 10
        assert "evidence_score_quality" in evidence

    def test_evidence_all_strong(self):
        """Evidence score higher when all components strong."""
        m = calculate_moneyness(24400.0, 24400.0)
        oi = oi_intelligence(9700.0, None)
        vol = volume_intelligence(8000.0, None)
        ba = bid_ask_intelligence(88.0, 92.0, "", "")
        iv = iv_intelligence(15.5, None)
        mf = move_fit(24400.0, 24400.0, 200)
        pre = premium_intelligence(91.0, None)
        resp = option_response_intelligence(20, 9)

        evidence = calculate_contract_evidence(
            moneyness=m, oi_result=oi, volume_result=vol,
            bid_ask_result=ba, iv_result=iv, move_fit_result=mf,
            premium_result=pre, response_result=resp,
        )
        # With all strong components, score should be close to 10
        assert evidence["evidence_score"] >= 7


# ----------------------- Contract Conviction Tests -----------------------

class TestContractConviction:
    """Test contract conviction classification."""

    def test_conviction_high(self):
        """HIGH conviction with strong evidence."""
        conv = calculate_contract_conviction(
            evidence_score=8.0,
            data_quality="REAL",
            score_margin=5.0,
            has_option_response=True,
            response_consistency="CONSISTENT",
            liquidity_quality="GOOD",
        )
        assert conv["conviction"] == "HIGH"

    def test_conviction_low(self):
        """LOW conviction with weak evidence."""
        conv = calculate_contract_conviction(
            evidence_score=2.0,
            data_quality="UNAVAILABLE",
            score_margin=1.0,
            has_option_response=False,
            response_consistency="UNAVAILABLE",
            liquidity_quality="WIDE",
        )
        assert conv["conviction"] == "LOW"

    def test_conviction_must_not_change_winner(self):
        """Conviction flag should not change the winner."""
        conv = calculate_contract_conviction(
            evidence_score=8.0,
            data_quality="REAL",
            score_margin=10.0,
            has_option_response=True,
            response_consistency="CONSISTENT",
            liquidity_quality="GOOD",
        )
        assert conv["conviction_should_not_change_winner"] is True


# ----------------------- WHY/Against Tests -----------------------

class TestWhyAgainst:
    """Test WHY and AGAINST reasons generation."""

    def test_why_against_generated(self):
        """WHY and AGAINST reasons are generated from components."""
        m = calculate_moneyness(24400.0, 24400.0)
        oi = oi_intelligence(9700.0, None)
        vol = volume_intelligence(8000.0, None)
        ba = bid_ask_intelligence(88.0, 92.0, "", "")
        iv = iv_intelligence(15.5, None)
        mf = move_fit(24400.0, 24400.0, 200)
        pre = premium_intelligence(91.0, None)
        resp = option_response_intelligence(20, 9)

        conviction = calculate_contract_conviction(
            evidence_score=8.0,
            data_quality="REAL",
            score_margin=5.0,
            has_option_response=True,
            response_consistency="CONSISTENT",
            liquidity_quality="GOOD",
        )

        why, against = why_against_reasons(
            moneyness=m,
            oi_result=oi,
            volume_result=vol,
            bid_ask_result=ba,
            iv_result=iv,
            move_fit_result=mf,
            premium_result=pre,
            response_result=resp,
            conviction=conviction,
        )

        assert isinstance(why, list)
        assert isinstance(against, list)
        # Should have some WHY reasons (near ATM, strong OI, etc.)
        assert len(why) > 0 or len(against) > 0


# ----------------------- Snapshot from Analysis Tests -----------------------

class TestSnapshotFromAnalysis:
    """Test snapshot_from_analysis integration helper."""

    def test_basic_snapshot(self):
        """Build contract snapshot from analysis results."""
        analysis_results = {
            "trade_context": {
                "direction": "BEARISH",
                "option_type": "PE",
                "expiry": "20241226",
                "expected_move": 30,
            },
            "symbol": "NIFTY",
            "_best_strike": 24400.0,
            "_baseline_scores": {24400.0: 85.0},
            "_enhanced_scores": {24400.0: 94.0},
            "_score_margin": 5.0,
        }
        ranked_strikes = {
            "best_pe": {
                "strike": 24400.0,
                "score": 94.0,
                "oi": 9700.0,
                "volume": 8000,
                "last_price": 91.0,
                "bid": 89.0,
                "ask": 93.0,
                "iv": 15.5,
                "underlying_change": 20.0,
                "premium_change": 9.0,
                "baseline_score": 85.0,
                "enhanced_score": 94.0,
                "score_margin": 5.0,
            },
            "pe_rankings": [
                {"strike": 24400.0, "score": 94.0},
                {"strike": 24450.0, "score": 88.0},
                {"strike": 24350.0, "score": 82.0},
            ],
        }
        market_data = {"ltp": 24400.0, "timestamp": "2024-01-15T10:30:00"}

        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        assert snapshot is not None
        assert "contract_identity" in snapshot
        assert "why" in snapshot
        assert "against" in snapshot
        assert "contract_evidence" in snapshot
        assert "contract_conviction" in snapshot


# ----------------------- Data Quality Tests -----------------------

class TestDataQuality:
    """Test data quality classification."""

    def test_quality_real(self):
        """REAL quality when has_real=True."""
        assert classify_quality(has_real=True) == "REAL"

    def test_quality_derived(self):
        """DERIVED quality when has_derived=True."""
        assert classify_quality(has_derived=True) == "DERIVED"

    def test_quality_estimated(self):
        """ESTIMATED quality when source mentions estimated."""
        assert classify_quality(source="estimated_model") == "ESTIMATED"

    def test_quality_unavailable(self):
        """UNAVAILABLE default."""
        assert classify_quality() == "UNAVAILABLE"


# ----------------------- Integration Tests -----------------------

class TestIntegration:
    """Integration tests for contract intelligence."""

    def test_full_snapshot_regression(self):
        """Regression: snapshot does not modify baseline/enhanced scores."""
        analysis_results = {
            "trade_context": {
                "direction": "BEARISH",
                "option_type": "PE",
                "expiry": "20241226",
                "expected_move": 30,
            },
            "symbol": "NIFTY",
            "_best_strike": 24400.0,
            "_baseline_scores": {24400.0: 85.0},
            "_enhanced_scores": {24400.0: 94.0},
            "_score_margin": 5.0,
        }
        ranked_strikes = {
            "best_pe": {
                "strike": 24400.0,
                "score": 94.0,
                "oi": 9700.0,
                "volume": 8000,
                "last_price": 91.0,
                "bid": 89.0,
                "ask": 93.0,
                "iv": 15.5,
                "underlying_change": 20.0,
                "premium_change": 9.0,
                "baseline_score": 85.0,
                "enhanced_score": 94.0,
                "score_margin": 5.0,
            },
            "pe_rankings": [
                {"strike": 24400.0, "score": 94.0},
                {"strike": 24450.0, "score": 88.0},
                {"strike": 24350.0, "score": 82.0},
            ],
        }
        market_data = {"ltp": 24400.0, "timestamp": "2024-01-15T10:30:00"}

        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)

        # Baseline and enhanced scores must be unchanged
        assert ranked_strikes["best_pe"]["baseline_score"] == 85.0
        assert ranked_strikes["best_pe"]["enhanced_score"] == 94.0

        # Snapshot should have evidence and conviction
        assert snapshot["contract_evidence"]["evidence_score"] >= 0
        assert snapshot["contract_evidence"]["evidence_score"] <= 10
        assert snapshot["contract_conviction"]["conviction_should_not_change_winner"] is True

        # WHY and AGAINST should be truthful (derived from data)
        assert isinstance(snapshot["why"], list)
        assert isinstance(snapshot["against"], list)


# ----------------------- Edge Case Tests -----------------------

class TestEdgeCases:
    """Edge case handling."""

    def test_moneyness_zero_distance(self):
        """Moneyness with zero distance (strike at spot)."""
        m = calculate_moneyness(0, 0)
        # distance=0 → ATM, quality STRONG (best case)
        assert m["quality"] == "STRONG"

    def test_unavailable_components_iv(self):
        """Test UNAVAILABLE when data truly absent."""
        # Test IV unavailable when no data provided
        from engines.ranking.contract_intelligence import iv_intelligence
        result = iv_intelligence()
        assert result["iv"] == "UNAVAILABLE"
        assert result["iv_quality"] == "UNAVAILABLE"

        ba = bid_ask_intelligence(None, None, "", "")
        assert ba["spread_quality"] == "UNAVAILABLE"

        iv = iv_intelligence(None, None)
        assert iv["iv"] == "UNAVAILABLE"

    def test_zero_strike(self):
        """Zero strike handled gracefully."""
        m = calculate_moneyness(0.0, 24400.0)
        assert m["distance"] == 24400.0

    def test_negative_premium_response(self):
        """Negative premium response handled."""
        result = option_response_intelligence(
            underlying_change=-20, premium_change=-9
        )
        assert result["premium_change"] == -9
        assert result["response_consistency"] in ("CONSISTENT", "MIXED")

    # ----------------------- Live Data Field Mapping Tests -----------------------

    def test_winner_strike_from_ranked(self):
        """Winner strike correctly mapped from ranked winner's live data."""
        analysis_results = {
            "trade_context": {"direction": "BULLISH", "option_type": "CE"},
            "symbol": "NIFTY",
        }
        ranked_strikes = {
            "best_ce": {
                "strike": 24250.0,
                "option_type": "CE",
                "last_price": 78.5,
                "openInterest": 12500,
                "totalTradedVolume": 8500,
                "bid": 78.0,
                "ask": 80.0,
                "impliedVolatility": 15.2,
            },
        }
        market_data = {"ltp": 78.5, "timestamp": "2026-08-17T10:30:00"}
        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        assert snapshot["strike"] == 24250.0

    def test_expiry_from_live_chain(self):
        """Expiry correctly available from ranked winner's live chain data."""
        analysis_results = {
            "trade_context": {"direction": "BULLISH", "option_type": "CE"},
            "symbol": "NIFTY",
        }
        ranked_strikes = {
            "best_ce": {
                "strike": 24250.0,
                "option_type": "CE",
                "expiry": "18AUG2026",
            },
        }
        market_data = {"ltp": 78.5, "timestamp": "2026-08-17T10:30:00"}
        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        assert snapshot["expiry"] == "18AUG2026"

    def test_ltp_from_ranked_winner(self):
        """LTP correctly mapped from ranked winner's live data (not 0.0)."""
        analysis_results = {
            "trade_context": {"direction": "BULLISH", "option_type": "CE"},
            "symbol": "NIFTY",
        }
        ranked_strikes = {
            "best_ce": {
                "strike": 24250.0,
                "option_type": "CE",
                "last_price": 78.5,
            },
        }
        market_data = {"ltp": 78.5, "timestamp": "2026-08-17T10:30:00"}
        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        assert snapshot["ltp"] == 78.5

    def test_oi_from_ranked_winner(self):
        """OI correctly mapped from ranked winner's live data."""
        analysis_results = {
            "trade_context": {"direction": "BULLISH", "option_type": "CE"},
            "symbol": "NIFTY",
        }
        ranked_strikes = {
            "best_ce": {
                "strike": 24250.0,
                "option_type": "CE",
                "oi": 12500,
            },
        }
        market_data = {"ltp": 78.5, "timestamp": "2026-08-17T10:30:00"}
        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        assert snapshot["oi"]["oi"] == 12500

    def test_iv_from_ranked_winner(self):
        """IV correctly mapped from ranked winner's live data."""
        analysis_results = {
            "trade_context": {"direction": "BULLISH", "option_type": "CE"},
            "symbol": "NIFTY",
        }
        ranked_strikes = {
            "best_ce": {
                "strike": 24250.0,
                "option_type": "CE",
                "iv": 15.2,
            },
        }
        market_data = {"ltp": 78.5, "timestamp": "2026-08-17T10:30:00"}
        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        assert snapshot["iv"]["iv"] == 15.2

    def test_volume_from_ranked_winner(self):
        """Volume correctly mapped from ranked winner's live data."""
        analysis_results = {
            "trade_context": {"direction": "BULLISH", "option_type": "CE"},
            "symbol": "NIFTY",
        }
        ranked_strikes = {
            "best_ce": {
                "strike": 24250.0,
                "option_type": "CE",
                "volume": 8500,
            },
        }
        market_data = {"ltp": 78.5, "timestamp": "2026-08-17T10:30:00"}
        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        assert snapshot["volume"]["volume"] == 8500

    def test_bid_from_ranked_winner(self):
        """Bid correctly mapped from ranked winner's live data."""
        analysis_results = {
            "trade_context": {"direction": "BULLISH", "option_type": "CE"},
            "symbol": "NIFTY",
        }
        ranked_strikes = {
            "best_ce": {
                "strike": 24250.0,
                "option_type": "CE",
                "bid": 78.0,
                "ask": 80.0,
            },
        }
        market_data = {"ltp": 78.5, "timestamp": "2026-08-17T10:30:00"}
        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        assert snapshot["bid_ask"]["bid"] == 78.0

    def test_ask_from_ranked_winner(self):
        """Ask correctly mapped from ranked winner's live data."""
        analysis_results = {
            "trade_context": {"direction": "BULLISH", "option_type": "CE"},
            "symbol": "NIFTY",
        }
        ranked_strikes = {
            "best_ce": {
                "strike": 24250.0,
                "option_type": "CE",
                "bid": 78.0,
                "ask": 80.0,
            },
        }
        market_data = {"ltp": 78.5, "timestamp": "2026-08-17T10:30:00"}
        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        assert snapshot["bid_ask"]["ask"] == 80.0

    def test_contract_identity_matches_ranking_winner(self):
        """Contract identity matches the ranking winner (symbol + expiry + strike + option_type)."""
        analysis_results = {
            "trade_context": {"direction": "BULLISH", "option_type": "CE"},
            "symbol": "NIFTY",
        }
        ranked_strikes = {
            "best_ce": {
                "strike": 24250.0,
                "option_type": "CE",
                "expiry": "18AUG2026",
            },
        }
        market_data = {"ltp": 78.5, "timestamp": "2026-08-17T10:30:00"}
        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        identity = snapshot["contract_identity"]
        assert "NIFTY" in identity
        assert "18AUG2026" in identity
        assert "24250" in identity
        assert "CE" in identity

    def test_no_fabrication_when_field_absent(self):
        """No fabricated values when field genuinely doesn't exist upstream."""
        analysis_results = {
            "trade_context": {"direction": "BULLISH", "option_type": "CE"},
            "symbol": "NIFTY",
        }
        ranked_strikes = {
            "best_ce": {
                "strike": 24250.0,
                "option_type": "CE",
                # deliberately omit: last_price, openInterest, impliedVolatility,
                # totalTradedVolume, bid, ask, expiry
            },
        }
        market_data = {"ltp": 78.5, "timestamp": "2026-08-17T10:30:00"}
        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        # When no live data upstream: ltp defaults to 0.0 (not fabricated), 
        # oi/iv show 0.0/UNAVAILABLE with UNAVAILABLE quality (not fabricated)
        assert snapshot["ltp"] == 0.0  # no fabrication - defaults to 0.0
        assert snapshot["oi"]["oi"] == 0.0  # no fabrication - defaults to 0.0
        assert snapshot["oi"]["oi_quality"] == "UNAVAILABLE"  # quality marker
        assert snapshot["iv"]["iv"] == "UNAVAILABLE"  # no fabrication - explicitly unavailable
        assert snapshot["iv"]["iv_quality"] == "UNAVAILABLE"  # quality marker
        # expiry falls back to trade_context, which is also blank → UNAVAILABLE
        assert snapshot["expiry"] == "UNAVAILABLE"

    def test_premium_source_real_when_live_verified(self):
        """Premium source is REAL when live LTP verified with timestamp."""
        analysis_results = {
            "trade_context": {"direction": "BULLISH", "option_type": "CE"},
            "symbol": "NIFTY",
        }
        ranked_strikes = {
            "best_ce": {
                "strike": 24250.0,
                "option_type": "CE",
                "last_price": 78.5,
                "premium_source": "REAL",
            },
        }
        market_data = {"ltp": 78.5, "timestamp": "2026-08-17T10:30:00"}
        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        assert snapshot["premium_source"] == "REAL"

    def test_premium_source_estimated_when_no_live_data(self):
        """Premium source is ESTIMATED when no live data available."""
        analysis_results = {
            "trade_context": {"direction": "BULLISH", "option_type": "CE"},
            "symbol": "NIFTY",
        }
        ranked_strikes = {
            "best_ce": {
                "strike": 24250.0,
                "option_type": "CE",
                # no last_price / ltp
            },
        }
        market_data = {"ltp": 78.5, "timestamp": "2026-08-17T10:30:00"}
        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        assert snapshot["premium_source"] == "ESTIMATED"

    def test_direction_logic_preserved(self):
        """Direction logic still correctly determines option type from ranked winner."""
        # Bearish → PE: direction BEARISH picks best_pe → option_type PE
        analysis_results = {
            "trade_context": {"direction": "BEARISH", "option_type": "PE"},
            "symbol": "NIFTY",
        }
        ranked_strikes = {
            "best_pe": {
                "strike": 24250.0,
                "option_type": "PE",
            },
        }
        market_data = {"ltp": 55.0, "timestamp": "2026-08-17T10:30:00"}
        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        assert snapshot["option_type"] == "PE"

        # Bullish → CE: direction BULLISH picks best_ce → option_type CE
        analysis_results2 = {
            "trade_context": {"direction": "BULLISH", "option_type": "CE"},
            "symbol": "NIFTY",
        }
        ranked_strikes2 = {
            "best_ce": {
                "strike": 24250.0,
                "option_type": "CE",
            },
        }
        snapshot2 = snapshot_from_analysis(analysis_results2, ranked_strikes2, market_data)
        assert snapshot2["option_type"] == "CE"

    def test_score_margin_preserved(self):
        """Score margins preserved from ranking engine output."""
        analysis_results = {
            "trade_context": {"direction": "BULLISH", "option_type": "CE"},
            "symbol": "NIFTY",
        }
        ranked_strikes = {
            "best_ce": {
                "strike": 24250.0,
                "option_type": "CE",
                "baseline_score": 85.0,
                "enhanced_score": 94.0,
                "score_margin": 5.0,
            },
        }
        market_data = {"ltp": 78.5, "timestamp": "2026-08-17T10:30:00"}
        snapshot = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        assert snapshot["contract_evidence"]["baseline_score"] == 85.0
        assert snapshot["contract_evidence"]["enhanced_score"] == 94.0
        assert snapshot["contract_evidence"]["score_margin"] == 5.0