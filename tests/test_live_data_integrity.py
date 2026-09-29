"""Regression tests for the live data-integrity defects found in Termux.

Each test corresponds to a concrete live observation:

  1. NIFTY spot frozen at 22683.75 for five cycles while the exchange showed
     ~22704 -> get_live_data()'s cached fallback stamped datetime.now() on a
     reused price, so stale data looked fresh and passed the guard.
  2. Entry 2.10 / SL -2.90 and Entry 1.50 / SL -3.50 -> the stop model was a
     flat `entry - 5`, and the validator's own R:R test then computed
     risk = 5.0 and rr = 2.8, so an impossible trade passed a 2.0 minimum.
  3. "Ranking ATR 12.5" vs "Snapshot ATR 21.7" -> ranking read
     market_data.get("atr", 12.5) and nothing ever wrote that key, so a
     hardcoded default was displayed forever next to the real 5m ATR.
  4. "can't subtract offset-naive and offset-aware datetimes" every cycle ->
     a naive parsed expiry was subtracted from an aware now(), and the
     exception was swallowed so greeks never attached.
  5. "IV: 7.36% / IV source: REAL" beside "Greeks: Unavailable" -> IV was
     labelled REAL at chain level with no per-contract provenance.
  6/7. spot 22683.75 beside OHLC close 22780.25 -> fields assembled from
     different instants, with no age shown.
  8. Bias BULLISH while 5m NEUTRAL / 15m+1h BEARISH -> different measures,
     which is legitimate, but they must come from one snapshot.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.market_snapshot import build_market_snapshot       # noqa: E402
from core.timeutil import (                                  # noqa: E402
    IST, age_seconds, days_to_expiry, humanize_age, ist,
    now_ist, parse_expiry, seconds_to_expiry, to_utc, years_to_expiry,
)
from data.strike_brain import (                              # noqa: E402
    calculate_stop_loss, calculate_targets,
)

main = pytest.importorskip("main")


# ------------------------------------------------------------------ helpers
def future_expiry(days=3):
    return (now_ist() + timedelta(days=days)).strftime("%d%b%Y")


class _Cfg:
    def __init__(self, now=None):
        self._now = now or now_ist()

    def now(self):
        return self._now

    def get(self, key, default=None):
        return "15:30" if key == "market_hours.close" else default

    def get_int(self, key, default=0):
        return default


class _ME:
    detected_expiry = ""


def _app(expiry=None):
    app = main.BlockoraTrade.__new__(main.BlockoraTrade)
    app.config = _Cfg()
    me = _ME()
    type(me).detected_expiry = expiry if expiry is not None else future_expiry()
    app.market_engine = me
    return app


def _chain(iv=14.0, expiry=None):
    def rec(t):
        return {"strike": 22650, "ltp": t, "iv": iv, "oi": 100, "change_oi": 0,
                "volume": 500, "bid": t - 0.5, "ask": t + 0.5,
                "oi_source": "REAL", "volume_source": "REAL",
                "bid_source": "REAL", "ask_source": "REAL"}
    # NOTE: `expiry=""` must stay empty (that is the "unknown expiry" case),
    # so this cannot use `or`.
    _exp = future_expiry() if expiry is None else expiry
    return {"expiry": _exp, "spot_price": 22650,
            "ce_data": {22650: rec(120.0)}, "pe_data": {22650: rec(110.0)}}


# ============================================ 4. datetime policy (naive/aware)
def test_parse_expiry_is_aware_ist():
    exp = parse_expiry("29SEP2026")
    assert exp is not None
    assert exp.tzinfo is not None, "expiry must never be naive"
    assert exp.utcoffset().total_seconds() == 5.5 * 3600
    assert (exp.hour, exp.minute) == (15, 30), "expiry is the session close"


def test_seconds_to_expiry_does_not_raise_mixing_naive_and_aware():
    """The exact live crash: naive expiry minus aware now."""
    secs = seconds_to_expiry("29SEP2026")
    assert secs is not None
    # Past dates return a negative value, never a TypeError.
    assert isinstance(secs, float)


def test_attach_greeks_no_longer_raises_on_real_expiry_string():
    """The live log line: 'can't subtract offset-naive and offset-aware'."""
    app = _app()
    out = app._attach_greeks(_chain(14.0), 22650.0)   # must not raise
    assert "greeks" in out["ce_data"][22650]


def test_expiry_day_calculation_uses_intraday_remainder():
    today = now_ist().strftime("%d%b%Y")
    yrs = years_to_expiry(today)
    if yrs is None:
        pytest.skip("session already closed today")
    assert 0 <= yrs < 1 / 365, "expiry-day tenor must be under a day"
    assert days_to_expiry(today) == 1


def test_hours_to_expiry_is_aware_math():
    exp = parse_expiry(future_expiry(1))
    hours = (exp - now_ist()).total_seconds() / 3600
    assert 0 < hours <= 24.1


def test_timeutil_never_returns_naive():
    for fn in (parse_expiry("29SEP2026"), now_ist(), ist(datetime(2026, 9, 29))):
        assert fn.tzinfo is not None


def test_to_utc_round_trip():
    n = now_ist()
    assert to_utc(n).utcoffset().total_seconds() == 0
    assert ist(to_utc(n)) == n


def test_parse_expiry_rejects_garbage_without_guessing():
    assert parse_expiry("not-a-date") is None
    assert parse_expiry("") is None
    assert parse_expiry(None) is None
    assert years_to_expiry("not-a-date") is None


def test_age_seconds_is_fail_closed():
    assert age_seconds("garbage") is None
    assert age_seconds(None) is None
    assert age_seconds(now_ist().isoformat()) is not None
    assert humanize_age(None) == "Unavailable"


# ===================================== 2. risk levels never invalid
@pytest.mark.parametrize("entry", [0.5, 1.5, 2.1, 3.0, 5.0, 9.99, 10.0, 12.0, 120.25, 250.0])
def test_stop_loss_is_always_positive_and_below_entry(entry):
    sl = calculate_stop_loss(entry, None, "BULLISH")
    assert sl > 0, f"SL {sl} for entry {entry} must be > 0"
    assert sl < entry, f"SL {sl} for entry {entry} must be < entry"


@pytest.mark.parametrize("entry", [0.5, 1.5, 2.1, 5.0, 10.0, 120.25])
def test_targets_strictly_above_entry_and_ordered(entry):
    t1, t2, t3 = calculate_targets(entry, None, "BULLISH")
    assert 0 < entry < t1 <= t2 <= t3, (entry, t1, t2, t3)


def test_live_reported_cases_are_repaired():
    """The exact numbers from the live log."""
    assert calculate_stop_loss(2.10, None, "BULLISH") > 0
    assert calculate_stop_loss(1.50, None, "BULLISH") > 0


def test_high_premium_path_is_unchanged():
    """Above the threshold the original fixed 5-point scalp stop applies."""
    assert calculate_stop_loss(120.25, None, "BULLISH") == 115.25
    assert calculate_targets(120.25, None, "BULLISH") == (127.25, 130.25, 134.25)


def test_stop_loss_rejects_non_numeric():
    assert calculate_stop_loss("abc", None, "BULLISH") == 0.0
    assert calculate_stop_loss(-5, None, "BULLISH") == 0.0


# ------------------------------------- 2b. validator rejects bad geometry
def _validator():
    from core.config_manager import ConfigManager
    from engines.decision.decision_validator import DecisionValidator
    cfg = ConfigManager()
    cfg.load()
    return DecisionValidator(cfg, mock.MagicMock())


def _ctx(bs, regime="SIDEWAYS"):
    return {"fresh": True, "liq_stats": {"removed": 0, "kept": 20},
            "regime": {"type": regime, "adx": 20, "rsi": 50, "atr_pct": 0.01},
            "vix": 14.0, "confidence": 75.0, "best_strike": bs,
            "spot": 22650, "direction": "BULLISH", "chain": {},
            "risk_stats": {"trades_today": 0, "daily_pnl": 0.0, "consec_losses": 0}}


def _good(overrides=None):
    bs = {"strike": 22650, "option_type": "CE", "entry": 100.0, "stop_loss": 95.0,
          "target_1": 110.0, "target_2": 115.0, "target_3": 120.0,
          "oi": 500000, "change_oi": 100000, "volume": 500000,
          "holding_time": 15, "premium_source": "REAL", "volume_source": "REAL"}
    bs.update(overrides or {})
    return bs


def test_validator_accepts_valid_levels():
    res = _validator().validate(_ctx(_good()), skip_market_hours=True)
    assert not any("invalid_risk_levels" in h for h in res["hard_fail"]), res["hard_fail"]


def test_validator_rejects_negative_stop_loss():
    """Live: entry 2.10, SL -2.90 previously produced rr 2.8 and PASSED."""
    res = _validator().validate(
        _ctx(_good({"entry": 2.10, "stop_loss": -2.90})), skip_market_hours=True)
    assert res["valid"] is False
    assert any("invalid_risk_levels" in h for h in res["hard_fail"]), res["hard_fail"]


def test_validator_rejects_sl_above_entry():
    res = _validator().validate(
        _ctx(_good({"stop_loss": 105.0})), skip_market_hours=True)
    assert res["valid"] is False
    assert any("invalid_risk_levels" in h for h in res["hard_fail"])


def test_validator_rejects_zero_stop_loss():
    res = _validator().validate(_ctx(_good({"stop_loss": 0.0})), skip_market_hours=True)
    assert res["valid"] is False


def test_validator_rejects_target_at_or_below_entry():
    res = _validator().validate(
        _ctx(_good({"target_1": 90.0})), skip_market_hours=True)
    assert res["valid"] is False
    assert any("invalid_risk_levels" in h for h in res["hard_fail"])


def test_validator_tolerates_absent_optional_target():
    """A missing target is unknown, not invalid."""
    res = _validator().validate(
        _ctx(_good({"target_3": 0.0})), skip_market_hours=True)
    assert not any("invalid_risk_levels" in h for h in res["hard_fail"]), res["hard_fail"]


# ==================================== 1. stale spot is detected, not ranked
def test_snapshot_flags_stale_spot():
    old = (now_ist() - timedelta(seconds=600)).isoformat()
    snap = build_market_snapshot(
        {"ltp": 22683.75, "quote_timestamp": old, "data_source": "LIVE"},
        {}, {}, {}, now=now_ist())
    assert snap.is_spot_fresh() is False
    assert snap.tradable is False
    assert any("stale_market_data" in r for r in snap.staleness_reasons)


def test_snapshot_accepts_fresh_spot():
    snap = build_market_snapshot(
        {"ltp": 22704.30,
         "quote_timestamp": now_ist().isoformat(), "data_source": "LIVE"},
        {}, {}, {}, now=now_ist())
    assert snap.is_spot_fresh() is True
    assert snap.tradable is True


def test_snapshot_rejects_spot_with_no_timestamp():
    """No timestamp cannot be proven fresh -> fail closed."""
    snap = build_market_snapshot({"ltp": 22650, "data_source": "LIVE"},
                                 {}, {}, {}, now=now_ist())
    assert snap.is_spot_fresh() is False


def test_snapshot_marks_cached_source_distinctly():
    snap = build_market_snapshot(
        {"ltp": 22683.75, "quote_timestamp": now_ist().isoformat(),
         "data_source": "CACHED"}, {}, {}, {}, now=now_ist())
    assert snap.data_status == "CACHED"
    assert snap.spot_source == "CACHED"


# -------------------------------- 1b. the engine must not re-stamp a cache
def test_market_engine_cached_fallback_keeps_original_timestamp():
    """A reused LTP must not be re-stamped with now()."""
    from core.config_manager import ConfigManager
    from data.market_data_engine import MarketDataEngine

    eng = MarketDataEngine(ConfigManager(), mock.MagicMock())
    original = (now_ist() - timedelta(seconds=900)).isoformat()
    eng._last_good_candles = [[0, 1, 2, 3, 4, 5]]
    eng._last_good_ts = original
    eng.live_data = {"ltp": 22683.75, "quote_timestamp": original,
                     "open": 1, "high": 2, "low": 3, "close": 4}
    eng.connected = False          # force the fallback branch
    out = eng.get_live_data()
    if out is None:               # no candles path taken on this platform
        pytest.skip("fallback branch not reachable without a broker client")
    assert out["quote_timestamp"] == original
    assert out["data_source"] == "CACHED"
    assert out["ltp"] == 22683.75


# =========================================== 3. one ATR, one timeframe
def test_ranking_uses_snapshot_atr_not_a_hardcoded_default():
    import engines.ranking.strike_ranking_engine as mod
    src = Path(mod.__file__).read_text()
    assert 'market_data.get("atr", 12.5)' not in src
    assert "12.5" not in src, "the hardcoded ATR default must be gone entirely"
    # the ATR must be read from the supplied snapshot
    assert 'float(market_data.get("atr") or 0.0)' in src


def test_snapshot_carries_explicit_indicator_timeframe():
    snap = build_market_snapshot(
        {"ltp": 22650, "quote_timestamp": now_ist().isoformat()},
        {}, {"indicators": {"atr": 21.7, "rsi": 51.0, "adx": 22.0}}, {},
        now=now_ist())
    assert snap.atr == 21.7
    assert snap.indicator_timeframe == "5m"
    assert snap.candle_timeframe == "5m"


def test_ranking_and_snapshot_share_the_same_atr_value():
    """Same cycle, same number: no second generic 'atr' field."""
    from core.config_manager import ConfigManager
    from engines.ranking.strike_ranking_engine import StrikeRankingEngine

    cfg = ConfigManager()
    cfg.load()
    md = {"ltp": 22650, "quote_timestamp": now_ist().isoformat(), "data_source": "LIVE"}
    analysis = {"market_data": md, "option_chain": _chain(),
                "trade_context": {"expected_move": 40, "direction": "BULLISH",
                                  "vwap": 22650, "expiry_date": future_expiry()},
                "indicators": {"atr": 21.7, "rsi": 51.0, "adx": 22.0},
                "multi_timeframe": {}, "learning": {}}
    snap = build_market_snapshot(md, analysis["option_chain"], analysis, {},
                                 now=now_ist())
    rank_md = dict(md)
    rank_md["atr"] = snap.atr
    ranked = StrikeRankingEngine(cfg, mock.MagicMock()).rank(analysis, 75.0, rank_md)
    assert ranked["ce_rankings"] or ranked["pe_rankings"]
    assert snap.atr == 21.7
    assert rank_md["atr"] == snap.atr


def test_missing_atr_is_none_not_a_fabricated_default():
    snap = build_market_snapshot(
        {"ltp": 22650, "quote_timestamp": now_ist().isoformat()},
        {}, {"indicators": {"rsi": 50}}, {}, now=now_ist())
    assert snap.atr is None


# ============================== 5. IV provenance is truthful per contract
def test_contract_iv_source_is_explicit():
    app = _app()
    out = app._attach_greeks(_chain(14.0), 22650.0)
    r = out["ce_data"][22650]
    assert r["iv_source"] == "NSE_OPTION_CHAIN"
    assert r["greeks_source"] == "DERIVED_BS"
    assert r["premium_source"] == "ANGEL_LIVE"
    assert r["expiry_source"] == "SCRIP_MASTER"


def test_contract_without_iv_is_marked_unavailable_not_real():
    app = _app()
    out = app._attach_greeks(_chain(0), 22650.0)
    r = out["ce_data"][22650]
    assert r["iv_source"] == "UNAVAILABLE"
    assert r["iv"] == 0.0
    assert "greeks" not in r
    assert out["greeks_source"] == "UNAVAILABLE"


def test_iv_and_greeks_never_contradict_each_other():
    """The live 'IV 7.36% / IV source REAL' beside 'Greeks: Unavailable'."""
    app = _app()
    for iv in (0, 7.36, 14.0):
        out = app._attach_greeks(_chain(iv), 22650.0)
        r = out["ce_data"][22650]
        has_greeks = "greeks" in r
        has_iv = r["iv"] > 0
        assert has_greeks == has_iv, f"iv={iv} greeks={has_greeks}"


def test_no_expiry_marks_greeks_unavailable_explicitly():
    app = _app(expiry="")
    out = app._attach_greeks(_chain(14.0, expiry=""), 22650.0)
    assert out["greeks_source"] == "UNAVAILABLE"
    assert "greeks" not in out["ce_data"][22650]


# ================================= 6/7. single consistent snapshot
def test_snapshot_fields_come_from_one_market_data_object():
    md = {"ltp": 22683.75, "open": 22600.0, "high": 22780.25, "low": 22550.0,
          "close": 22780.25, "quote_timestamp": now_ist().isoformat(),
          "data_source": "LIVE"}
    snap = build_market_snapshot(md, {}, {"indicators": {"atr": 21.7}}, {},
                                 now=now_ist())
    assert snap.spot == md["ltp"]
    assert snap.close == md["close"]
    # spot and close are from the same dict, so they cannot disagree
    assert snap.spot == md["ltp"] and snap.high == md["high"]


def test_snapshot_exposes_chain_provenance_and_age():
    chain_ts = (now_ist() - timedelta(seconds=20)).isoformat()
    snap = build_market_snapshot(
        {"ltp": 22650, "quote_timestamp": now_ist().isoformat()},
        {"timestamp": chain_ts, "source": "ANGEL_LIVE"}, {}, {}, now=now_ist())
    assert snap.chain_source == "ANGEL_LIVE"
    assert snap.chain_age_sec is not None
    assert 19 <= snap.chain_age_sec <= 25


def test_snapshot_stale_chain_is_reported():
    chain_ts = (now_ist() - timedelta(seconds=600)).isoformat()
    snap = build_market_snapshot(
        {"ltp": 22650, "quote_timestamp": now_ist().isoformat()},
        {"timestamp": chain_ts, "source": "ANGEL_LIVE"}, {}, {}, now=now_ist())
    assert snap.is_chain_fresh() is False
    assert snap.tradable is False


def test_snapshot_exposes_mtf_for_documentation():
    snap = build_market_snapshot(
        {"ltp": 22650, "quote_timestamp": now_ist().isoformat()}, {},
        {"multi_timeframe": {"t5": "NEUTRAL", "t15": "BEARISH", "t1h": "BEARISH"},
         "trade_context": {"direction": "BULLISH"}}, {}, now=now_ist())
    # Bias and MTF are different measurements and are NOT forced to agree.
    assert snap.bias == "BULLISH"
    assert snap.multi_timeframe["t5"] == "NEUTRAL"
    assert snap.multi_timeframe["t15"] == "BEARISH"


def test_snapshot_serialises_for_persistence():
    snap = build_market_snapshot(
        {"ltp": 22650, "quote_timestamp": now_ist().isoformat()}, {}, {}, {},
        now=now_ist())
    d = snap.as_dict()
    assert d["spot"] == 22650
    assert "spot_age_sec" in d and "data_status" in d


# ============================== spot changes between cycles reach ranking
def test_spot_change_between_cycles_changes_ranking():
    """Two consecutive cycles with different spot must rank differently."""
    from core.config_manager import ConfigManager
    from engines.ranking.strike_ranking_engine import StrikeRankingEngine

    cfg = ConfigManager()
    cfg.load()

    def run(spot):
        md = {"ltp": spot, "quote_timestamp": now_ist().isoformat(),
              "data_source": "LIVE", "atr": 20.0}
        chain = {"expiry": future_expiry(), "pcr": 1.1, "max_pain": spot}
        atm = int(round(spot / 50.0) * 50)
        rec = lambda s: {"strike": s, "ltp": 100.0, "oi": 50000, "change_oi": 9000,
                         "volume": 300000, "iv": 14.0, "bid": 99.5, "ask": 100.5}
        chain["ce_data"] = {atm + d: rec(atm + d) for d in (-100, -50, 0, 50, 100)}
        chain["pe_data"] = {atm + d: rec(atm + d) for d in (-100, -50, 0, 50, 100)}
        analysis = {"market_data": md, "option_chain": chain,
                    "trade_context": {"expected_move": 40, "direction": "BULLISH",
                                      "vwap": spot, "expiry_date": future_expiry()},
                    "indicators": {"atr": 20.0, "rsi": 50, "adx": 25},
                    "multi_timeframe": {}, "learning": {}}
        ranked = StrikeRankingEngine(cfg, mock.MagicMock()).rank(analysis, 75.0, md)
        best = ranked.get("best_ce") or ranked.get("best_pe") or {}
        return best.get("strike"), best.get("score")

    # Two spots that round to different ATM buckets, so a stale-but-reused
    # spot would be visible as an identical selection.
    s1 = run(22683.75)     # ATM bucket 22700
    s2 = run(22480.00)     # ATM bucket 22500
    assert s1[0] != s2[0], "a moved spot must move the selected strike"


def test_cycle_rejects_stale_spot_before_ranking():
    """A stale underlying must never reach rank()."""
    called = {"n": 0}

    app = main.BlockoraTrade.__new__(main.BlockoraTrade)
    app.cycle_count = 1
    app.config = _Cfg()
    app.market_engine = mock.MagicMock()
    app.market_engine.detected_expiry = future_expiry()
    app.freshness_guard = mock.MagicMock()
    app.freshness_guard.check.return_value = (True, [])   # guard does not catch
    app.ranking_engine = mock.MagicMock()
    app.ranking_engine.rank.side_effect = lambda *a, **k: called.__setitem__(
        "n", called["n"] + 1) or {"best_ce": {}, "best_pe": {},
                                  "ce_rankings": [], "pe_rankings": []}
    app.market_engine.get_live_data.return_value = {
        "ltp": 22683.75,
        "quote_timestamp": (now_ist() - timedelta(seconds=900)).isoformat(),
        "data_source": "LIVE", "symbol": "NIFTY", "candles": []}
    app.logger = mock.MagicMock()
    app.option_engine = mock.MagicMock()
    app.option_engine.get_option_chain.return_value = _chain()

    result = app.run_analysis_cycle()
    assert result is None, "stale spot must abort the cycle"
    assert called["n"] == 0, "ranking must never run on a stale underlying"
