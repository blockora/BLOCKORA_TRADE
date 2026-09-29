"""End-to-end v3 pipeline tests: decision engine across scenarios."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import Config
from core.models import Decision, FeatureVector, Quality, TradePlan, UnderlyingTick, DataQuality
from pipeline.data_sources import SyntheticSource
from pipeline.engine import DecisionEngine, MarketDataSource
from pipeline.outcomes import PremiumBar, evaluate_outcome


@pytest.fixture(scope="module")
def cfg():
    return Config.load()


def _engine(cfg, seed=42, regime="range"):
    src = SyntheticSource(seed=seed, regime=regime)
    return DecisionEngine(cfg, MarketDataSource(src, src)), src


# ---------------------------------------------------------------- cycle runs
def test_bull_regime_produces_call_recommendation(cfg):
    eng, _ = _engine(cfg, seed=7, regime="bull")
    rec = eng.run_cycle()
    assert rec.decision in (Decision.RECOMMENDATION, Decision.NO_TRADE)
    if rec.decision == Decision.RECOMMENDATION:
        assert rec.side == "CALL"
        assert rec.plan is not None and rec.plan.t1 > rec.plan.entry > rec.plan.stop_loss
        assert rec.model_score is not None
        assert rec.calibrated_state == "UNAVAILABLE"      # never invented
        assert rec.calibrated_confidence is None


def test_bear_regime_produces_put_recommendation(cfg):
    eng, _ = _engine(cfg, seed=11, regime="bear")
    rec = eng.run_cycle()
    if rec.decision == Decision.RECOMMENDATION:
        assert rec.side == "PUT"
        assert rec.plan is not None and rec.plan.t1 > rec.plan.entry > rec.plan.stop_loss


def test_cycle_runs_deterministically(cfg):
    eng1, _ = _engine(cfg, seed=99, regime="bull")
    eng2, _ = _engine(cfg, seed=99, regime="bull")
    r1, r2 = eng1.run_cycle(), eng2.run_cycle()
    assert (r1.decision, r1.side, r1.strike, r1.model_score) == \
           (r2.decision, r2.side, r2.strike, r2.model_score)


def test_score_is_between_0_and_100(cfg):
    eng, _ = _engine(cfg, seed=3, regime="bull")
    rec = eng.run_cycle()
    if rec.model_score is not None:
        assert 0.0 <= rec.model_score <= 100.0


# ---------------------------------------------------------------- NO_TRADE paths
def test_unhealthy_source_yields_no_trade(cfg):
    src = SyntheticSource(seed=1)
    eng = DecisionEngine(cfg, MarketDataSource(src, src))
    eng.source.is_healthy = lambda: False
    rec = eng.run_cycle()
    assert rec.decision == Decision.NO_TRADE
    assert "F2_source" in rec.no_trade_reason


def test_missing_spot_yields_no_trade(cfg):
    src = SyntheticSource(seed=1)
    orig = src.get_underlying_tick

    def broken(symbol):
        t = orig(symbol)
        return UnderlyingTick(t.symbol, None, t.change_pct, t.quality)

    src.get_underlying_tick = broken
    eng = DecisionEngine(cfg, MarketDataSource(src, src))
    rec = eng.run_cycle()
    assert rec.decision == Decision.NO_TRADE
    assert "F4_missing" in rec.no_trade_reason


def test_empty_chain_yields_no_trade(cfg):
    src = SyntheticSource(seed=1)
    src.get_chain = lambda expiry, strikes: []
    eng = DecisionEngine(cfg, MarketDataSource(src, src))
    rec = eng.run_cycle()
    assert rec.decision == Decision.NO_TRADE
    assert "F4_missing" in rec.no_trade_reason


def test_wide_spread_candidate_fails_hard_filter(cfg):
    """High-scoring candidate with 8% spread must NOT become a recommendation."""
    eng, src = _engine(cfg, seed=21, regime="bull")
    # widen every quote's spread
    orig_chain = src.get_chain

    def wide_chain(expiry, strikes):
        quotes = orig_chain(expiry, strikes)
        for q in quotes:
            mid = (q.bid + q.ask) / 2
            q.bid = round(max(mid * 0.96, 0.05), 2)
            q.ask = round(mid * 1.04, 2)
        return quotes

    src.get_chain = wide_chain
    rec = eng.run_cycle()
    assert rec.decision == Decision.NO_TRADE
    assert "F5_spread" in rec.no_trade_reason


def test_duplicate_signal_blocked_within_dedup_window(cfg):
    """The SAME contract must not win twice within the dedup window.

    The synthetic source is stateful (its RNG advances per get_chain call), so
    to compare like-for-like we freeze the chain snapshot after cycle 1. The
    duplicate candidate must then be vetoed with F14_duplicate; the engine may
    still recommend the NEXT-BEST surviving candidate (correct behavior — F14
    is per-contract, not per-cycle).
    """
    eng, src = _engine(cfg, seed=21, regime="bull")
    captured: dict = {}
    orig_chain = src.get_chain

    def capture_chain(expiry, strikes):
        quotes = orig_chain(expiry, strikes)
        captured["quotes"] = quotes
        return quotes

    src.get_chain = capture_chain
    rec1 = eng.run_cycle()
    if rec1.decision == Decision.RECOMMENDATION:
        assert rec1.strike is not None
        # freeze market data; carry dedup keys into the new engine
        src.get_chain = lambda expiry, strikes: captured["quotes"]
        eng2 = DecisionEngine(cfg, eng.source)
        eng2._recent_keys = eng._recent_keys
        rec2 = eng2.run_cycle()
        dup_key = f"{int(rec1.strike)}_{rec1.side == 'CALL' and 'CE' or 'PE'}_{rec1.expiry}"
        if rec2.decision == Decision.RECOMMENDATION:
            # next-best candidate won; the duplicate must appear as rejected
            assert rec2.strike != rec1.strike
            assert any("F14_duplicate" in r and dup_key.split("_")[0] in r
                       for r in (rec2.rejected_alternatives or [])), \
                   f"duplicate {dup_key} not rejected: {rec2.rejected_alternatives}"
        else:
            assert "F14_duplicate" in (rec2.no_trade_reason or "") or \
                   "filter_veto" in (rec2.no_trade_reason or "")


# ---------------------------------------------------------------- outcome rules
def test_outcome_t1_before_sl_is_win():
    bars = [PremiumBar("2026-09-28T10:00:00", 100, 101, 99, 100),
            PremiumBar("2026-09-28T10:05:00", 100, 108, 99, 107)]
    r = evaluate_outcome(100, 92, 105, bars, "2026-09-28T09:55:00")
    assert r["outcome"] == "WIN_T1"


def test_outcome_sl_before_t1_is_loss():
    bars = [PremiumBar("2026-09-28T10:05:00", 100, 101, 90, 91)]
    r = evaluate_outcome(100, 92, 105, bars, "2026-09-28T10:00:00")
    assert r["outcome"] == "LOSS"


def test_outcome_same_bar_ambiguity_is_loss():
    bars = [PremiumBar("2026-09-28T10:05:00", 100, 110, 88, 100)]
    r = evaluate_outcome(100, 92, 105, bars, "2026-09-28T10:00:00")
    assert r["outcome"] == "LOSS"
    assert "conservative" in r["exit_reason"]


def test_outcome_timeout_neither_level():
    bars = [PremiumBar("2026-09-28T10:05:00", 100, 101, 99.5, 100)] * 30
    r = evaluate_outcome(100, 92, 105, bars, "2026-09-28T10:00:00", max_bars=24)
    assert r["outcome"] == "TIMEOUT"


def test_outcome_ignores_bars_at_or_before_decision():
    """No look-ahead: bars stamped at/before decision_ts must not count."""
    bars = [PremiumBar("2026-09-28T10:00:00", 100, 120, 80, 100),   # would hit both
            PremiumBar("2026-09-28T10:05:00", 100, 100.5, 99.5, 100)]
    r = evaluate_outcome(100, 92, 105, bars, "2026-09-28T10:00:00")
    assert r["outcome"] == "TIMEOUT"   # only the second bar was evaluated


def test_outcome_mfe_mae_tracked():
    bars = [PremiumBar("2026-09-28T10:05:00", 100, 104, 96, 100)]
    r = evaluate_outcome(100, 92, 110, bars, "2026-09-28T10:00:00")
    assert r["mfe"] == pytest.approx(4.0)
    assert r["mae"] == pytest.approx(-4.0)


# ---------------------------------------------------------------- plan/risk sanity
def test_plan_rejected_without_bid_ask(cfg):
    from pipeline.risk import build_plan
    fv = FeatureVector(strike=24500, option_type="CE", expiry="X", ltp=100)
    assert build_plan(fv, 50.0, 1.5, 1.0, 2.0, 3.0) is None


def test_plan_rejected_without_atr(cfg):
    from pipeline.risk import build_plan
    fv = FeatureVector(strike=24500, option_type="CE", expiry="X",
                       ltp=100, bid=99.5, ask=100.5)
    assert build_plan(fv, None, 1.5, 1.0, 2.0, 3.0) is None


# ---------------------------------------------------------------- full loop: decide -> store -> outcome -> store
def test_full_loop_recommendation_to_outcome(cfg, tmp_path):
    """Decide -> persist -> replay premium bars -> persist outcome -> closed."""
    from database.db import Database
    from pipeline.outcomes import PremiumBar, evaluate_outcome

    db = Database(tmp_path / "loop.db")
    db.initialize()
    try:
        eng, _ = _engine(cfg, seed=21, regime="bull")
        rec = eng.run_cycle()
        assert rec.decision in (Decision.RECOMMENDATION, Decision.NO_TRADE)
        rid = db.insert_recommendation({
            "decision_ts": rec.decision_ts, "decision": rec.decision.value,
            "market_bias": rec.market_bias.value if rec.market_bias else None,
            "side": rec.side, "strike": rec.strike, "expiry": rec.expiry,
            "entry": rec.plan.entry if rec.plan else None,
            "stop_loss": rec.plan.stop_loss if rec.plan else None,
            "t1": rec.plan.t1 if rec.plan else None,
            "t2": rec.plan.t2 if rec.plan else None,
            "t3": rec.plan.t3 if rec.plan else None,
            "expected_hold_min": rec.plan.expected_hold_min if rec.plan else None,
            "model_score": rec.model_score,
            "calibrated_state": rec.calibrated_state,
            "trade_grade": rec.trade_grade,
            "key_reasons": rec.key_reasons,
            "rejected_alternatives": rec.rejected_alternatives,
            "no_trade_reason": rec.no_trade_reason,
            "diagnostics": rec.diagnostics,
            "pipeline_version": "3.0.0-test", "weights_hash": cfg.weights_hash(),
            "created_ts": rec.decision_ts,
        })
        if rec.decision == Decision.RECOMMENDATION:
            p = rec.plan
            # Synthetic premium path that rises to T1 shortly AFTER the decision.
            # Timestamps are derived from the real decision_ts: the engine
            # stamps it with wall-clock now_ist(), so hardcoded clock times
            # (e.g. "10:35") can land BEFORE the decision and be correctly
            # discarded by evaluate_outcome's no-look-ahead filter. Deriving
            # them keeps the fixture honest without weakening that filter.
            dts = datetime.fromisoformat(rec.decision_ts)
            t1 = (dts + timedelta(minutes=5)).isoformat()
            t2 = (dts + timedelta(minutes=10)).isoformat()
            bars = [PremiumBar(t1, p.entry, p.entry + 2, p.entry - 1, p.entry + 1),
                    PremiumBar(t2, p.entry + 1, p.t1 + 3, p.entry, p.t1 + 1)]
            res = evaluate_outcome(p.entry, p.stop_loss, p.t1, bars, rec.decision_ts)
            assert res["outcome"] == "WIN_T1"
            oid = db.insert_outcome({
                "recommendation_id": rid, "outcome": res["outcome"],
                "mfe": res["mfe"], "mae": res["mae"],
                "bars_to_outcome": res["bars_to_outcome"],
                "evaluated_ts": "2026-09-29T10:41:00+05:30",
                "source": "LIVE_REPLAY", "data_quality": "OK",
            })
            assert oid > 0
            assert db.open_recommendations() == []   # closed by outcome
        else:
            # NO_TRADE is terminal (never tracked for outcome); row must exist.
            assert db.open_recommendations() == []
            assert db.recent_recommendations()[0]["decision"] == "NO_TRADE"
    finally:
        db.close()


# ------------------------------------------------- evaluate_outcome no-look-ahead guards
# These pin the protections that a "fix" for the TIMEOUT failure must NOT weaken.
ENTRY, SL, T1 = 100.0, 95.0, 107.0


def _bar(iso, high, low):
    return PremiumBar(iso, ENTRY, high, low, ENTRY)


def test_bars_at_or_before_decision_are_rejected():
    """A bar stamped exactly at the decision must NOT be consumed (no look-ahead)."""
    dts = "2026-09-29T12:00:00+05:30"
    bars = [_bar("2026-09-29T12:00:00+05:30", T1 + 5, ENTRY)]  # T1 would hit
    res = evaluate_outcome(ENTRY, SL, T1, bars, dts)
    assert res["outcome"] == "TIMEOUT", res
    assert res["bars_to_outcome"] == 0


def test_pre_decision_bars_never_produce_a_win():
    """Historical bars before the decision are ignored even if they 'hit' T1."""
    dts = "2026-09-29T12:00:00+05:30"
    bars = [_bar("2026-09-29T10:35:00+05:30", T1 + 9, SL - 9)]
    res = evaluate_outcome(ENTRY, SL, T1, bars, dts)
    assert res["outcome"] == "TIMEOUT", res
    assert res["mfe"] == 0.0 and res["mae"] == 0.0


def test_first_bar_after_decision_can_win():
    """A bar strictly after the decision is consumed and T1 resolves."""
    dts = "2026-09-29T12:00:00+05:30"
    bars = [_bar("2026-09-29T12:05:00+05:30", T1 + 3, ENTRY)]
    res = evaluate_outcome(ENTRY, SL, T1, bars, dts)
    assert res["outcome"] == "WIN_T1", res
    assert res["bars_to_outcome"] == 1


def test_same_bar_t1_and_sl_is_conservative_loss():
    """Ambiguous bar (both levels touched in one bar) counts as LOSS, never a win."""
    dts = "2026-09-29T12:00:00+05:30"
    bars = [_bar("2026-09-29T12:05:00+05:30", T1 + 3, SL - 3)]
    res = evaluate_outcome(ENTRY, SL, T1, bars, dts)
    assert res["outcome"] == "LOSS", res
    assert "ambiguity" in res["exit_reason"]


def test_t1_touch_compares_inclusively():
    """high exactly at T1 counts as reached (>= not >)."""
    dts = "2026-09-29T12:00:00+05:30"
    bars = [_bar("2026-09-29T12:05:00+05:30", T1, ENTRY)]
    assert evaluate_outcome(ENTRY, SL, T1, bars, dts)["outcome"] == "WIN_T1"


def test_holding_window_limits_evaluated_bars():
    """Bars beyond max_bars are never consumed."""
    dts = "2026-09-29T12:00:00+05:30"
    bars = [_bar(f"2026-09-29T12:{m:02d}:00+05:30", ENTRY, ENTRY)
            for m in range(1, 10)]
    bars.append(_bar("2026-09-29T13:00:00+05:30", T1 + 3, ENTRY))  # too late
    res = evaluate_outcome(ENTRY, SL, T1, bars, dts, max_bars=3)
    assert res["outcome"] == "TIMEOUT", res
    assert res["bars_to_outcome"] == 3
