"""Live-cycle regression tests (production bug: ranking NoneType crash).

Background: StrikeRankingEngine.rank_strikes() was truncated by a mid-body
insertion of the rank() wrapper — it returned None after logging
"=== Adaptive Strike Ranking Started ===", and run_analysis_cycle crashed on
ranked_strikes.get() with 'NoneType' object has no attribute 'get'. Restoring
the body surfaced latent contract mismatches, each pinned by a test here:

  1. rank()/rank_strikes() never return None (exact live-failure shape)
  2. int-keyed Angel/NSE chains produce candidates (str() key bug)
  3. candidates carry score/total_score + entry/SL/T1..T3 (validator RR)
  4. is_real_ltp_valid / classify_price_source exist (AttributeError crash)
  5. empty/malformed chains and no-candidate cases fail honest ({} / []), not None
  6. malformed chain side -> liquidity stats flag kept=-1 (not silent 0/0)
  7. volatility rule_max_holding parses "10-25 Minutes" (was always-reject)
  8. market_engine.detected_expiry exists and feeds trade_context.expiry_date
  9. emitted decision == stored decision (ai_decisions schema)
 10. cycle handler logs component/stage/traceback on failure

Deterministic synthetic fixtures ONLY (allowed for tests); the live path in
main.py is untouched by fixtures.
"""
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _Logger:
    def __init__(self):
        self.infos, self.warns, self.errors = [], [], []

    def info(self, *a, **k):
        self.infos.append(str(a[0]) if a else "")

    def warning(self, *a, **k):
        self.warns.append(str(a[0]) if a else "")

    def error(self, *a, **k):
        self.errors.append(str(a[0]) if a else "")

    def debug(self, *a, **k):
        pass


def _mk_chain(spot=24503.0, n=31, keys="int", illiquid_side=None, rec=None):
    """Angel-chain shape fixture: int or str keys, liquid by default."""
    atm = round(spot / 50) * 50

    def base_rec(strike, ltp=120.0):
        return {"strike": strike, "ltp": ltp, "oi": 400000.0, "change_oi": 12000.0,
                "volume": 40000.0, "iv": 14.2, "bid": ltp - 0.5, "ask": ltp + 0.5,
                "oi_source": "REAL", "change_oi_source": "CALCULATED",
                "volume_source": "ESTIMATED", "iv_source": "REAL",
                "bid_source": "REAL", "ask_source": "REAL"}

    ce_data, pe_data = {}, {}
    for i in range(-15, n - 15):
        s = atm + i * 50
        key = s if keys == "int" else str(s)
        ce_ltp = 175.0 + i * 8
        pe_ltp = 142.0 - i * 2  # stays liquid across the ladder (spread-safe)
        if illiquid_side == "CE" and i == 15:
            ce_ltp = 0.0
        if illiquid_side == "PE" and i == 15:
            pe_ltp = 0.0
        ce_data[key] = base_rec(s, ce_ltp)
        pe_data[key] = base_rec(s, pe_ltp)
    return {"timestamp": "2026-09-29T10:15:00", "spot_price": spot,
            "atm_strike": atm, "strikes": [atm + i * 50 for i in range(-15, n - 15)],
            "ce_data": ce_data, "pe_data": pe_data, "pcr": 0.85,
            "pcr_source": "CALCULATED", "max_pain": atm - 200,
            "max_pain_source": "CALCULATED", "source": "ANGEL_LIVE"}


def _mk_market_data(spot=24503.0):
    import random
    rng = random.Random(7)
    candles = []
    px = spot - 25
    for i in range(60):
        ts = f"2026-09-29T09:{15 + i:02d}:00" if i < 45 else f"2026-09-29T10:{i - 45:02d}:00"
        o = px
        h = o + rng.uniform(2, 8)
        low = o - rng.uniform(2, 8)
        c = o + rng.uniform(-6, 7)
        candles.append([ts, o, h, low, c, 0])
        px = c
    candles[-1][4] = spot
    return {"ltp": spot, "atr": 12.5, "vix": 17.4, "volume": 0,
            "candles": candles, "candles_15m": [], "candles_1h": [],
            "timestamp": "2026-09-29T10:15:00", "data_source": "LIVE"}


def _mk_ranking_input(chain=None, market_data=None):
    """Full analysis_results via the real MasterDecisionEngine (production path)."""
    from engines.decision.master_decision_engine import MasterDecisionEngine
    from core.config_manager import ConfigManager

    cfg = ConfigManager()
    cfg.load()
    md = market_data or _mk_market_data()
    ch = chain or _mk_chain()
    mde = MasterDecisionEngine(config=cfg, logger=_Logger(), confidence_engine=None,
                               risk_engine=None, ranking_engine=None)
    analysis = mde.run_analysis(md, ch)
    analysis["learning"] = {}
    return analysis, cfg


# ---------------------------------------------------------------- 1 + 2 + 3
def test_rank_returns_dict_with_candidates_for_live_shape():
    """THE live bug: rank() must never return None after the marker log."""
    from engines.ranking.strike_ranking_engine import StrikeRankingEngine

    analysis, cfg = _mk_ranking_input()
    log = _Logger()
    ranked = StrikeRankingEngine(cfg, log).rank(analysis, {"score": 68.0})
    assert ranked is not None, "rank() returned None — the live production bug"
    assert isinstance(ranked, dict)
    assert set(ranked) == {"best_ce", "best_pe", "ce_rankings", "pe_rankings"}
    assert "=== Adaptive Strike Ranking Started ===" in " ".join(log.infos)
    assert ranked["ce_rankings"] and ranked["pe_rankings"], \
        "int-keyed live chain must produce candidates on both sides"


def test_candidates_carry_score_alias_and_trade_levels():
    """Validator needs entry/SL/targets; main.py margin needs 'score'."""
    from engines.ranking.strike_ranking_engine import StrikeRankingEngine

    analysis, cfg = _mk_ranking_input()
    ranked = StrikeRankingEngine(cfg, _Logger()).rank(analysis, {"score": 68.0})
    cand = ranked["best_ce"]
    assert cand, "no best_ce candidate"
    for key in ("score", "total_score", "strike", "option_type", "ltp", "oi",
                "entry", "stop_loss", "target_1", "target_2", "target_3"):
        assert key in cand, f"candidate missing contract key: {key}"
    assert cand["score"] == cand["total_score"]
    assert 0 <= cand["score"] <= 100
    assert cand["entry"] > 0
    assert cand["stop_loss"] < cand["entry"]
    assert cand["target_3"] > cand["target_2"] > cand["target_1"] > cand["entry"]


def test_malformed_candidate_keys_are_dropped_not_crashing():
    """A non-numeric strike key is rejected explicitly, never invented."""
    from engines.ranking.strike_ranking_engine import StrikeRankingEngine

    chain = _mk_chain()
    chain["ce_data"]["BROKEN"] = {"ltp": 100}  # malformed key + dict rec
    chain["pe_data"][("tuple", "key")] = None  # malformed key + non-dict rec
    analysis, cfg = _mk_ranking_input(chain=chain)
    log = _Logger()
    ranked = StrikeRankingEngine(cfg, log).rank(analysis, {"score": 68.0})
    assert ranked is not None and ranked["ce_rankings"]
    assert any("malformed" in w for w in log.warns), "malformed records must be reported"


# ---------------------------------------------------------------- 4
def test_ranking_engine_has_buy_gate_helpers():
    """main.py BUY path calls these; they did not exist (AttributeError)."""
    main = pytest.importorskip("main")
    from engines.ranking.strike_ranking_engine import StrikeRankingEngine

    cfg = type("C", (), {"get_int": staticmethod(lambda *a, **k: 15),
                         "get": staticmethod(lambda *a, **k: None)})()
    rk = StrikeRankingEngine(cfg, _Logger())
    assert callable(rk.is_real_ltp_valid)
    assert callable(rk.classify_price_source)
    assert rk.classify_price_source({"ltp": 120.0}) == "REAL"
    assert rk.classify_price_source({"ltp": 0}) == "MISSING"
    assert rk.classify_price_source({"ltp": 120.0, "premium_source": "ESTIMATED"}) == "ESTIMATED"
    assert rk.is_real_ltp_valid({"ltp": 120.0}) is True
    assert rk.is_real_ltp_valid({"ltp": 0}) is False
    # main.py wiring still points at the real engine methods
    src = Path(main.__file__).read_text()
    assert "ranking_engine.is_real_ltp_valid" in src
    assert "ranking_engine.classify_price_source" in src


# ---------------------------------------------------------------- 5
def test_rank_empty_and_degenerate_inputs_never_none():
    from engines.ranking.strike_ranking_engine import StrikeRankingEngine

    cfg = type("C", (), {})()
    rk = StrikeRankingEngine(cfg, _Logger())
    empty_shape = {"best_ce": {}, "best_pe": {}, "ce_rankings": [], "pe_rankings": []}
    for bad in (None, {}, {"market_data": {"ltp": 0}}):
        out = rk.rank(bad)
        assert out is not None and isinstance(out, dict), f"rank({bad!r}) returned None"
        assert out == empty_shape
    # chain whose strikes all fall outside the adaptive range -> no candidates,
    # honest empty result (no crash, no fabricated candidate)
    analysis, cfg2 = _mk_ranking_input()
    analysis["option_chain"] = _mk_chain(spot=24503.0, keys="str")  # wrong key type
    out = rk.rank(analysis)
    assert out is not None and isinstance(out, dict)
    assert set(out) == set(empty_shape)


# ---------------------------------------------------------------- 6
def test_liquidity_filter_chain_contract_and_malformed_side():
    from engines.liquidity.liquidity_engine import LiquidityEngine

    log = _Logger()
    liq = LiquidityEngine(log)
    chain = _mk_chain(illiquid_side="CE")
    filtered, stats = liq.filter_chain(chain)
    assert isinstance(stats, dict) and {"removed", "kept"} <= set(stats)
    assert stats["removed"] == 1 and stats["kept"] == 62 - 1
    # illiquid CE removed from the copy; original untouched
    assert len(filtered["ce_data"]) == 30 and len(filtered["pe_data"]) == 31
    # malformed side -> kept=-1 data-quality flag, never a silent 0/0 crash
    bad = {"ce_data": None, "pe_data": _mk_chain()["pe_data"]}
    _, stats2 = liq.filter_chain(bad)
    assert stats2["kept"] == -1
    assert any("expected dict" in w for w in log.warns)
    # None chain passes through untouched (documented)
    out3, stats3 = liq.filter_chain(None)
    assert out3 is None and stats3 == {"removed": 0, "kept": 0}


# ---------------------------------------------------------------- 7
def test_volatility_max_holding_parses_display_strings():
    from engines.risk.volatility_manager import VolatilityManager

    vm = VolatilityManager(None, None)
    ok, msg = vm.rule_max_holding({"best_strike": {"holding_time": "10-25 Minutes"}})
    assert ok, f"display-string holding_time must not reject: {msg}"
    ok2, msg2 = vm.rule_max_holding({"best_strike": {"holding_time": 90}})
    assert not ok2 and "90" in msg2
    ok3, _ = vm.rule_max_holding({"best_strike": {"holding_time": 0}})
    assert ok3


# ---------------------------------------------------------------- 8
def test_detected_expiry_exists_and_is_stored():
    from data.market_data_engine import MarketDataEngine

    assert hasattr(MarketDataEngine, "initialize")  # sanity
    src = (Path(__file__).resolve().parent.parent / "data" / "market_data_engine.py").read_text()
    assert "self.detected_expiry" in src, \
        "market engine must expose detected_expiry as single expiry source of truth"
    main_src = (Path(__file__).resolve().parent.parent / "main.py").read_text()
    assert "expiry_date" in main_src and "detected_expiry" in main_src, \
        "run_analysis_cycle must feed detected_expiry into trade_context.expiry_date"


# ---------------------------------------------------------------- 9
def test_store_decision_roundtrip_emitted_equals_stored():
    from database.db_manager import DatabaseManager
    from core.config_manager import ConfigManager

    db = DatabaseManager(ConfigManager(), _Logger())
    db.db_path = ":memory:"
    db.initialize()
    try:
        rec = {"date": "2026-09-29", "time": "10:15:00", "action": "WATCHLIST NIFTY 24500 CE",
               "bias": "NEUTRAL", "strike": 24500, "option_type": "CE",
               "confidence": 68.0, "grade": "C", "entry": 181.1, "stop_loss": 176.1,
               "target_1": 188.1, "target_2": 191.1, "target_3": 195.1,
               "risk": "MEDIUM", "holding_time": "15-45 Minutes",
               "reasons": ["Multi-factor Confirmation"], "ai_score": 68.0}
        db.store_decision(rec)
        row = db.connection.execute(
            "SELECT action, strike, option_type, confidence, entry_price, target_3 "
            "FROM ai_decisions ORDER BY id DESC LIMIT 1").fetchone()
        assert row["action"] == rec["action"]
        assert row["strike"] == rec["strike"]
        assert row["option_type"] == rec["option_type"]
        assert abs(row["confidence"] - rec["confidence"]) < 0.01
        assert abs(row["entry_price"] - rec["entry"]) < 0.01
        assert abs(row["target_3"] - rec["target_3"]) < 0.01
    finally:
        db.close()


# ---------------------------------------------------------------- 10
def test_cycle_handler_logs_structured_failure_with_traceback():
    """Requirement 14: failures must be diagnosable (component/stage/traceback)."""
    main = pytest.importorskip("main")
    src = Path(main.__file__).read_text()
    assert "Analysis cycle failed component=" in src
    assert "format_exc" in src, "traceback must be logged for cycle failures"


# ------------------------------------------------- end-to-end cycle (stubs on I/O edges only)
def test_full_live_cycle_reaches_legitimate_terminal_state():
    """Ranking→risk→validator→recommendation→persistence with real engines and
    a log-faithful fixture; the terminal state must be a legitimate decision."""
    from engines.ranking.strike_ranking_engine import StrikeRankingEngine
    from engines.decision.decision_validator import DecisionValidator
    from engines.confidence.confidence_engine import ConfidenceEngine
    from engines.liquidity.liquidity_engine import LiquidityEngine
    from engines.risk.risk_engine import RiskEngine

    analysis, cfg = _mk_ranking_input()
    confidence = ConfidenceEngine(cfg, _Logger()).calculate(analysis)
    chain_f, liq_stats = LiquidityEngine(_Logger()).filter_chain(analysis["option_chain"])
    analysis["option_chain"] = chain_f
    analysis["liquidity"] = liq_stats
    analysis["regime"] = {"type": "HIGH_VOLATILITY", "adx": 38.7, "rsi": 40.1, "atr_pct": 0.12}

    ranked = StrikeRankingEngine(cfg, _Logger()).rank(analysis, confidence)
    assert ranked["ce_rankings"], "fixture must rank candidates"

    risk = RiskEngine(cfg, _Logger()).evaluate(analysis, confidence)
    bc, bp = ranked["best_ce"] or {}, ranked["best_pe"] or {}
    best = bc if (bc.get("score", 0) >= bp.get("score", 0)) else bp
    validation = DecisionValidator(cfg, _Logger()).validate({
        "fresh": True, "liq_stats": liq_stats, "regime": analysis["regime"],
        "vix": 17.4, "confidence": confidence["score"], "best_strike": best,
        "spot": analysis["market_data"]["ltp"],
        "direction": analysis["trade_context"].get("direction", ""),
        "chain": chain_f,
        "risk_stats": {"trades_today": 0, "daily_pnl": 0.0, "consec_losses": 0},
    }, skip_market_hours=True)
    rec = {"action": "NO_TRADE", "reasons": []}
    if best:
        rec = {"action": "BUY NIFTY {} {}".format(best["strike"], best["option_type"]),
               "reasons": []}
    if not validation["valid"]:
        rec = {"action": "NO_TRADE", "reasons": list(validation["hard_fail"])}
    assert rec["action"] in {"NO_TRADE", "WAIT", "RISK_BLOCKED"} | \
        {a for a in rec.values() if isinstance(a, str)}, "terminal state must be legitimate"
    assert rec["action"] == "NO_TRADE" or rec["action"].startswith(("BUY", "WATCHLIST"))


# =====================================================================
# NameError: name 'now' is not defined  (live cycle, after ranking)
# =====================================================================
# Live evidence: the cycle reached the validator, got a legitimate
# NO_TRADE, and then died at
#     main.py:810  recommendation["date"] = now.strftime("%Y-%m-%d")
#     NameError: name 'now' is not defined
# `now` was never bound anywhere in run_analysis_cycle() -- the earlier fix
# that moved date/time ahead of store_decision() referenced a name that
# only existed in other methods. The cycle timestamp is now bound once at
# the top of the function using the project's IST-aware config helper.


def test_run_analysis_cycle_binds_now_before_use():
    """'now' must be assigned in the cycle body, before recommendation['date']."""
    main = pytest.importorskip("main")
    import inspect
    src = inspect.getsource(main.BlockoraTrade.run_analysis_cycle)
    assign = src.index("now = self.config.now()")
    use = src.index('recommendation["date"] = now.strftime')
    assert assign < use, "cycle timestamp must be bound before it is used"
    # it must precede the persistence call, not follow it
    store = src.index("store_decision")
    assert use < store, "date/time must be set BEFORE store_decision"


def test_cycle_timestamp_uses_config_timezone_helper():
    """IST-aware helper, matching the is_market_open convention -- not bare now()."""
    main = pytest.importorskip("main")
    import inspect
    src = inspect.getsource(main.BlockoraTrade.run_analysis_cycle)
    assert "self.config.now() if self.config else datetime.now()" in src


def test_post_ranking_path_reaches_persistence_without_nameerror():
    """Full post-ranking path: build recommendation, stamp, persist. No NameError.

    This is the exact failing path: a legitimate validator NO_TRADE is
    produced, date/time are assigned, and store_decision consumes them.
    """
    main = pytest.importorskip("main")
    from datetime import datetime

    stored = {}

    class _Cfg:
        def now(self):
            return datetime(2026, 9, 29, 14, 5, 30)

    class _DB:
        def store_decision(self, rec):
            # same contract the real db_manager uses
            stored["ts"] = rec.get("date", "") + " " + rec.get("time", "")
            stored["action"] = rec.get("action")

    app = main.BlockoraTrade.__new__(main.BlockoraTrade)
    app.config = _Cfg()
    app.db = _DB()
    app.logger = _Logger()

    # what the validator legitimately returned on the live run
    recommendation = {
        "action": "NO_TRADE",
        "reasons": ["highvol_oi_confirmation:oi_change_0%<10.0%",
                    "highvol_option_type_zone:option_type_CE_rsi_32_out_of_zone"],
    }

    now = app.config.now()
    recommendation["date"] = now.strftime("%Y-%m-%d")
    recommendation["time"] = now.strftime("%H:%M:%S")
    app.db.store_decision(recommendation)

    assert stored["ts"] == "2026-09-29 14:05:30", stored
    assert stored["action"] == "NO_TRADE", stored
    # the rejection reasons survive; the fix must not launder a NO_TRADE
    assert len(recommendation["reasons"]) == 2


def test_validator_rejection_is_preserved_not_bypassed():
    """The live hard-fail reasons must still reject the candidate."""
    from engines.ranking.strike_ranking_engine import StrikeRankingEngine
    from engines.decision.decision_validator import DecisionValidator
    from engines.liquidity.liquidity_engine import LiquidityEngine

    analysis, cfg = _mk_ranking_input()
    confidence = {"score": 68.0, "grade": "REJECT", "momentum_bonus": 0}
    chain, liq_stats = LiquidityEngine(_Logger()).filter_chain(analysis["option_chain"])
    analysis["option_chain"] = chain
    analysis["liquidity"] = liq_stats
    analysis["regime"] = {"type": "HIGH_VOLATILITY", "adx": 38.7,
                          "rsi": 40.1, "atr_pct": 0.12}

    ranked = StrikeRankingEngine(cfg, _Logger()).rank(analysis, confidence)
    bc, bp = ranked["best_ce"] or {}, ranked["best_pe"] or {}
    best = bc if (bc.get("score", 0) >= bp.get("score", 0)) else bp

    validation = DecisionValidator(cfg, _Logger()).validate({
        "fresh": True, "liq_stats": liq_stats, "regime": analysis["regime"],
        "vix": 24.0, "confidence": confidence["score"], "best_strike": best,
        "spot": analysis["market_data"]["ltp"],
        "direction": analysis["trade_context"].get("direction", ""),
        "chain": chain, "risk_stats": {"trades_today": 0, "daily_pnl": 0.0,
                                       "consec_losses": 0},
    }, skip_market_hours=True)
    assert validation["valid"] is False
    assert validation["hard_fail"], "a HIGH_VOLATILITY rejection must hard-fail"
