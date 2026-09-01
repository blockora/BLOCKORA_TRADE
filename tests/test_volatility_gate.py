"""BLOCKORA_TRADE — Volatility Gate Tests (pytest-compatible)
Graduated volatility policy:
  - EXTREME_VOLATILITY -> REJECT (NO_TRADE)
  - HIGH_VOLATILITY    -> intraday rules -> PASS-with-flags ya REJECT
  - NORMAL             -> normal validation

Run standalone:  python tests/test_volatility_gate.py
Run with pytest: pytest tests/test_volatility_gate.py -q
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from core.config_manager import ConfigManager
from core.logger_manager import LoggerManager
from engines.regime.market_regime_engine import MarketRegimeEngine
from engines.decision.decision_validator import DecisionValidator
from engines.risk.risk_engine import RiskEngine
from engines.risk.volatility_manager import VolatilityManager

config = ConfigManager(); config.load()
logger = LoggerManager(config); logger.setup()
regime_engine = MarketRegimeEngine(logger, config)
validator = DecisionValidator(config, logger)
risk_engine = RiskEngine(config, logger)
vm = VolatilityManager(config, logger)


# ---- Helpers ----
def make_regime(rtype, adx=60, rsi=75, atr_pct=0.08):
    return {"type": rtype, "adx": adx, "rsi": rsi, "atr_pct": atr_pct}

def make_ctx(regime, **kw):
    d = {
        "fresh": True,
        "liq_stats": {"kept": 5},
        "regime": regime,
        "vix": 14,
        "confidence": 85,
        "spot": 24250,
        "direction": "BULLISH",
        "best_strike": {
            "strike": 24250, "option_type": "CE",
            "entry": 100.0, "stop_loss": 90.0, "target_1": 112.0, "target_2": 116.0,
            "oi": 500000, "change_oi": 75000, "volume": 500000,
            "holding_time": 15, "premium_source": "REAL", "volume_source": "REAL",
        },
    }
    d.update(kw)
    return d


# ---- 1) Regime engine: 3-state classification ----
def test_regime_extreme_rsi():
    r = regime_engine._classify_regime(60, 92, 0.06)
    assert r["type"] == "EXTREME_VOLATILITY", r

def test_regime_extreme_adx():
    r = regime_engine._classify_regime(90, 60, 0.06)
    assert r["type"] == "EXTREME_VOLATILITY", r

def test_regime_extreme_atr():
    r = regime_engine._classify_regime(40, 60, 0.18)
    assert r["type"] == "EXTREME_VOLATILITY", r

def test_regime_high_vol():
    r = regime_engine._classify_regime(60, 75, 0.08)
    assert r["type"] == "HIGH_VOLATILITY", r

def test_regime_normal_band():
    r = regime_engine._classify_regime(20, 55, 0.02)
    assert r["type"] in ("NORMAL", "SIDEWAYS"), r


# ---- 2) Validator: EXTREME always REJECT ----
def test_validator_extreme_reject():
    res = validator.validate(make_ctx(make_regime("EXTREME_VOLATILITY")), skip_market_hours=True)
    assert res["valid"] is False
    assert any("EXTREME_VOLATILITY" in r for r in res["hard_fail"])

# ---- 3) Validator: HIGH_VOLATILITY passes intraday rules (good candidate) ----
def test_validator_high_vol_good_candidate_passes():
    # Fresh volume history (independent test)
    if hasattr(validator.volatility_manager, "_vol_history"):
        validator.volatility_manager._vol_history = []
    res = validator.validate(make_ctx(make_regime("HIGH_VOLATILITY")), skip_market_hours=True)
    # OI +22%? -> 75000/500000 = 15% > 10% OK; RR 1.6 >= 1.5 OK; ATM 24250==24250 OK
    assert res["valid"] is True, res["hard_fail"]

# ---- 4) Validator: HIGH_VOLATILITY rejects bad RR ----
def test_validator_high_vol_bad_rr_rejects():
    bs = {"strike": 24250, "option_type": "CE", "entry": 100.0, "stop_loss": 97.0,
          "target_1": 101.0, "target_2": 102.0, "oi": 500000, "change_oi": 75000,
          "volume": 500000, "holding_time": 15, "premium_source": "REAL"}
    res = validator.validate(
        make_ctx(make_regime("HIGH_VOLATILITY"), best_strike=bs), skip_market_hours=True)
    assert res["valid"] is False
    assert any("min_rr" in r for r in res["hard_fail"])

# ---- 5) Validator: HIGH_VOLATILITY rejects far OTM strike ----
def test_validator_high_vol_far_otm_rejects():
    bs = {"strike": 24450, "option_type": "CE", "entry": 100.0, "stop_loss": 90.0,
          "target_1": 112.0, "target_2": 116.0, "oi": 500000, "change_oi": 75000,
          "volume": 500000, "holding_time": 15, "premium_source": "REAL"}
    res = validator.validate(
        make_ctx(make_regime("HIGH_VOLATILITY"), best_strike=bs), skip_market_hours=True)
    assert res["valid"] is False
    assert any("highvol_atm_range" in r for r in res["hard_fail"])

# ---- 6) Validator: HIGH_VOLATILITY rejects weak OI change ----
def test_validator_high_vol_low_oi_rejects():
    bs = {"strike": 24250, "option_type": "CE", "entry": 100.0, "stop_loss": 90.0,
          "target_1": 112.0, "target_2": 116.0, "oi": 500000, "change_oi": 20000,
          "volume": 500000, "holding_time": 15, "premium_source": "REAL"}
    res = validator.validate(
        make_ctx(make_regime("HIGH_VOLATILITY"), best_strike=bs), skip_market_hours=True)
    # 20000/500000 = 4% < 10% -> reject
    assert any("highvol_oi" in r for r in res["hard_fail"])

# ---- 7) Risk engine: volatility-adjusted position sizing ----
def test_risk_position_normal():
    p = risk_engine.calculate_volatility_adjusted_position({"lot_size": 1}, make_regime("NORMAL"))
    assert p["position_pct"] == 1.0 and p["blocked"] is False

def test_risk_position_high():
    p = risk_engine.calculate_volatility_adjusted_position({"lot_size": 1}, make_regime("HIGH_VOLATILITY"))
    assert p["position_pct"] == 0.5 and p["adjusted_lot_size"] == 0.5

def test_risk_position_extreme():
    p = risk_engine.calculate_volatility_adjusted_position({"lot_size": 1}, make_regime("EXTREME_VOLATILITY"))
    assert p["position_pct"] == 0.0 and p["blocked"] is True

# ---- 8) VolatilityManager direct rules ----
def test_vm_position_size_pct():
    assert vm.position_size_pct("NORMAL") == 1.0
    assert vm.position_size_pct("HIGH_VOLATILITY") == 0.5
    assert vm.position_size_pct("EXTREME_VOLATILITY") == 0.0

def test_vm_max_trades_per_hour():
    ctx = make_ctx(make_regime("HIGH_VOLATILITY"))
    r1 = vm.check_intraday_rules(ctx)
    if r1["valid"]:
        vm.register_trade()
        r2 = vm.check_intraday_rules(ctx)
        assert any("max_trades" in x for x in r2["reject"])

def test_vm_never_crashes_on_bad_data():
    r = vm.check_intraday_rules({})
    assert isinstance(r, dict) and "valid" in r and "reject" in r


# ---- Standalone execution (optional; safe for pytest collection) ----
if __name__ == "__main__":
    passed = failed = 0
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    for name, fn in fns:
        try:
            fn(); passed += 1; print(f"  ✅ {name}")
        except Exception as e:
            failed += 1; print(f"  ❌ {name}: {e}")
    print("=" * 60)
    print(f"  RESULTS: {passed} passed | {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)