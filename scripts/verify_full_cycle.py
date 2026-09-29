#!/usr/bin/env python3
"""FULL-CYCLE VERIFICATION — every stage after the fixed ranking engine.

Mirrors main.py::run_analysis_cycle() from ranking to persistence with the
log-faithful fixture (31 strikes, PCR 0.85, HIGH_VOLATILITY ADX 38.7/RSI 40.1/
ATR% 0.12). Real engine code paths; stubs only for I/O edges (db=memory,
telegram=offline). Validates requirement #9: the cycle must reach a
legitimate terminal state with NO unhandled exceptions.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engines.ranking.strike_ranking_engine import StrikeRankingEngine
from engines.decision.master_decision_engine import MasterDecisionEngine
from engines.decision.decision_validator import DecisionValidator
from engines.confidence.confidence_engine import ConfidenceEngine
from engines.liquidity.liquidity_engine import LiquidityEngine
from engines.regime.market_regime_engine import MarketRegimeEngine
from engines.risk.risk_engine import RiskEngine
from engines.tracking.momentum_tracker import MomentumTracker
from database.db_manager import DatabaseManager
from core.config_manager import ConfigManager

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from repro_live_ranking_bug import build_live_chain, build_market_data, _Logger, _Cfg


def main():
    log = _Logger()
    spot = 24503.0
    market_data = build_market_data(spot)
    chain = build_live_chain(spot)

    cfg = ConfigManager()
    cfg.load()

    mde = MasterDecisionEngine(config=cfg, logger=log, confidence_engine=None,
                               risk_engine=None, ranking_engine=None)
    analysis = mde.run_analysis(market_data, chain)
    confidence = ConfidenceEngine(cfg, log).calculate(analysis)
    chain_f, liq_stats = LiquidityEngine(log).filter_chain(chain)
    analysis["option_chain"] = chain_f
    analysis["liquidity"] = liq_stats

    # Log-faithful regime from the live report (fixture candles alone read SIDEWAYS)
    regime = {"type": "HIGH_VOLATILITY", "adx": 38.7, "rsi": 40.1, "atr_pct": 0.12}
    analysis["regime"] = regime
    analysis["learning"] = {}

    rk = StrikeRankingEngine(cfg, log)
    ranked = rk.rank(analysis, confidence)
    assert isinstance(ranked, dict) and "best_ce" in ranked and "best_pe" in ranked
    n_ce, n_pe = len(ranked["ce_rankings"]), len(ranked["pe_rankings"])
    print(f"STAGE ranking OK: {n_ce} CE + {n_pe} PE candidates | "
          f"best_ce={ranked['best_ce'].get('strike')}({ranked['best_ce'].get('score')}) "
          f"best_pe={ranked['best_pe'].get('strike')}({ranked['best_pe'].get('score')})")
    assert n_ce > 0 and n_pe > 0, "fixture must produce candidates on both sides"

    # score alias + levels contract
    cand = ranked["best_ce"]
    for k in ("score", "total_score", "entry", "stop_loss", "target_1", "target_2", "target_3"):
        assert k in cand, f"candidate missing contract key: {k}"
    assert cand["entry"] > 0 and cand["stop_loss"] > 0 and cand["target_3"] > cand["target_1"] > cand["entry"]
    print(f"STAGE levels OK: entry={cand['entry']} sl={cand['stop_loss']} "
          f"t1={cand['target_1']} t2={cand['target_2']} t3={cand['target_3']}")

    # ── risk engine ──
    risk_engine = RiskEngine(cfg, log)
    risk_assessment = risk_engine.evaluate(analysis, confidence)
    print(f"STAGE risk OK: {risk_assessment['level']} (score {risk_assessment['score']})")

    # ── top3 + margin (main.py logic) ──
    _ce_ranks = ranked.get("ce_rankings", [])
    _pe_ranks = ranked.get("pe_rankings", [])
    analysis["_top3_ce"] = _ce_ranks[:3]
    analysis["_top3_pe"] = _pe_ranks[:3]
    _dir = str(analysis.get("trade_context", {}).get("direction", "")).upper()
    _bc = ranked.get("best_ce") or {}
    _bp = ranked.get("best_pe") or {}
    if _dir == "BEARISH":
        _best_strike = _bp or _bc
    elif _dir == "BULLISH":
        _best_strike = _bc or _bp
    else:
        _best_strike = _bc if (_bc.get("score", 0) >= _bp.get("score", 0)) else _bp
    # _top3_score_margin via a tiny main-like shim (method lives on BlockoraTrade)
    side = _pe_ranks if _dir == "BEARISH" else _ce_ranks
    if len(side) >= 2:
        margin = round(float(side[0].get("score", side[0].get("total_score", 0))) -
                       float(side[1].get("score", side[1].get("total_score", 0))), 2)
    else:
        margin = 0
    analysis["_best_strike"] = _best_strike.get("strike", 0)
    analysis["_score_margin"] = margin
    print(f"STAGE top3 OK: best={analysis['_best_strike']} margin={margin}")

    # ── momentum tracker (independent) ──
    MomentumTracker(log).update(_bc, _bp, chain_f)
    print("STAGE momentum OK")

    # ── BUY gates that previously crashed (missing methods) ──
    assert hasattr(rk, "is_real_ltp_valid") and hasattr(rk, "classify_price_source")
    print(f"STAGE buy-gates OK: classify={rk.classify_price_source(_best_strike)} "
          f"valid={rk.is_real_ltp_valid(_best_strike)}")

    # ── validator (HIGH_VOLATILITY path, in-session simulation) ──
    validator = DecisionValidator(cfg, log)
    validation = validator.validate({
        "fresh": True, "liq_stats": liq_stats, "regime": regime,
        "vix": 17.4, "confidence": confidence.get("score", 0),
        "best_strike": _best_strike, "spot": spot,
        "direction": analysis.get("trade_context", {}).get("direction", ""),
        "chain": chain_f, "risk_stats": {"trades_today": 0, "daily_pnl": 0.0, "consec_losses": 0},
    }, skip_market_hours=True)
    print(f"STAGE validator OK: valid={validation['valid']} "
          f"hard_fail={validation['hard_fail']}")

    # ── recommendation ──
    rec = mde.generate_recommendation(analysis, confidence, risk_assessment, ranked)
    assert isinstance(rec, dict) and "action" in rec
    # validator override (mirrors main.py)
    if not validation["valid"] and rec["action"] != "NO_TRADE":
        rec["action"] = "NO_TRADE"
        rec["reasons"] = ["Validator: " + ", ".join(validation["reasons"])]
    print(f"STAGE recommendation OK: {rec['action']} conf={rec['confidence']} bias={rec.get('bias')}")

    # ── persistence (real SQLite, in-memory) ──
    from datetime import datetime as _dt
    rec["date"] = _dt.now().strftime("%Y-%m-%d")
    rec["time"] = _dt.now().strftime("%H:%M:%S")
    db = DatabaseManager(cfg, log)
    db.db_path = ":memory:"
    db.initialize()
    try:
        db.store_decision(rec)
        cur = db.connection.cursor()
        cur.execute("SELECT COUNT(*) c, MAX(action) a FROM ai_decisions")
        row = cur.fetchone()
        assert row["c"] == 1, f"expected exactly 1 persisted decision, got {row['c']}"
        assert row["a"] == rec["action"], f"stored action {row['a']} != emitted {rec['action']}"
        print(f"STAGE persistence OK: 1 row, action={row['a']}")
    finally:
        db.close()

    # ── display (format-crash regression: was crashing on missing keys) ──
    import io
    from contextlib import redirect_stdout
    from unittest import mock

    class _BotShim:
        """display_recommendation with I/O edges stubbed."""
        import main as _m  # noqa

    import main as main_mod
    bot = main_mod.BlockoraTrade()
    bot.logger = log
    bot.config = cfg
    bot._validator_rejected = False
    buf = io.StringIO()
    with mock.patch.object(main_mod, "calculate_probabilities", create=True), \
         redirect_stdout(buf):
        try:
            bot.display_recommendation(rec, analysis, ranked, market_data)
        except Exception as e:
            print(f"STAGE display FAILED: {type(e).__name__}: {e}")
            raise
    out = buf.getvalue()
    assert "BEST PICK" in out
    print("STAGE display OK (dashboard rendered without format crash)")

    print()
    print("=" * 70)
    print("FULL CYCLE VERIFIED (sandbox): ranking→risk→validator→recommendation")
    print("→persistence→display all executed; terminal state = "
          f"{rec['action']} (legitimate)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
