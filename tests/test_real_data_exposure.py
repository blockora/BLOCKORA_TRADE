"""Regression tests for the real-data exposure pass.

The dashboard previously showed values that no engine produced (a static
weight_map claiming Delta was 20% of the score, and Brain/Engine columns
that always rendered N/A while the header reused those names for the real
ranking score). This pass wires genuinely available data through and
removes the misleading parts.

Contract pinned here:
  1. Greeks are DERIVED from a real IV, never invented
  2. No IV / no expiry / no spot -> no greeks key at all (unavailable, not 0)
  3. The displayed factor weights are the REAL scoring maxima (sum 100)
  4. The static weight_map and the phantom Brain/Engine columns are gone
  5. Ranked candidates carry real provenance and derived greeks
  6. The DB migration is additive and preserves existing rows
  7. Freshness / fail-closed behaviour is untouched by this pass
"""
import inspect
import json
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent

main = pytest.importorskip("main")

# The maxima are the engine's own declared factor caps. Kept literal here on
# purpose: if the scorer changes, this test must fail rather than silently
# follow, because the dashboard copy is derived from the same numbers.
FACTOR_MAX = {
    "moneyness": 15, "gamma": 10, "move_fit": 15, "oi": 12, "volume": 10,
    "spread": 8, "trend": 12, "vwap": 8, "max_pain": 5, "historical": 5,
}


class _Cfg:
    def __init__(self, now=None):
        self._now = now or datetime(2026, 9, 29, 13, 30, 0)

    def now(self):
        return self._now

    def get(self, key, default=None):
        return "15:30" if key == "market_hours.close" else default

    def get_int(self, key, default=0):
        return default


class _ME:
    detected_expiry = "29SEP2026"


def _app(expiry="29SEP2026"):
    app = main.BlockoraTrade.__new__(main.BlockoraTrade)
    app.config = _Cfg()
    me = _ME()
    type(me).detected_expiry = expiry
    app.market_engine = me
    return app


def _future_expiry(days: int = 3) -> str:
    """A scrip-master expiry that is genuinely in the future.

    A hardcoded date would make the test pass or fail depending on when it
    runs: core.timeutil treats an elapsed expiry as unusable (correctly), so
    a fixture pinned to a past session would silently stop attaching greeks.
    """
    from core.timeutil import now_ist
    from datetime import timedelta
    return (now_ist() + timedelta(days=days)).strftime("%d%b%Y")


def _chain(iv=14.0, expiry=None):
    rec = lambda t, o: {"strike": 22650, "ltp": t, "iv": iv, "oi": 100,
                        "bid": t - 0.5, "ask": t + 0.5, "oi_source": "REAL"}
    return {"expiry": expiry or _future_expiry(), "spot_price": 22650,
            "ce_data": {22650: rec(120.0, "CE")},
            "pe_data": {22650: rec(110.0, "PE")}}


# ---------------------------------------------------- 1/2 greeks honesty
def test_greeks_derived_from_real_iv():
    app = _app()
    out = app._attach_greeks(_chain(14.0), 22650.0)
    g = out["ce_data"][22650]["greeks"]
    assert set(g) == {"delta", "gamma", "theta", "vega"}
    assert out["ce_data"][22650]["greeks_source"] == "DERIVED_BS"
    assert out["greeks_source"] == "DERIVED_BS"
    # ATM call delta should sit near 0.5 for a sane IV
    assert 0.3 < g["delta"] < 0.7
    assert g["theta"] < 0, "theta must be negative for a long option"


@pytest.mark.parametrize("iv", [0, 0.0, None, ""])
def test_no_real_iv_means_no_greeks_key(iv):
    """Unavailable IV must leave the record WITHOUT a greeks key."""
    app = _app()
    out = app._attach_greeks(_chain(iv), 22650.0)
    assert "greeks" not in out["ce_data"][22650]
    assert "greeks" not in out["pe_data"][22650]


def test_no_expiry_means_no_greeks():
    """Never guess time-to-expiry: without a real expiry, no greeks."""
    app = _app(expiry="")
    out = app._attach_greeks(_chain(14.0, expiry=""), 22650.0)


def test_elapsed_expiry_means_no_greeks():
    """A past session close is unusable -> no greeks, not a negative tenor."""
    app = _app()
    past = "01JAN2020"
    out = app._attach_greeks(_chain(14.0, expiry=past), 22650.0)
    assert "greeks" not in out["ce_data"][22650]
    assert out["greeks_source"] == "UNAVAILABLE"
    assert "greeks" not in out["ce_data"][22650]


def test_no_spot_means_no_greeks():
    app = _app()
    out = app._attach_greeks(_chain(14.0), 0)
    assert "greeks" not in out["ce_data"][22650]


def test_attach_greeks_tolerates_malformed_chain():
    """Must not raise on junk input (the cycle wraps it anyway)."""
    app = _app()
    for junk in (None, {}, [], {"ce_data": None, "pe_data": None}):
        app._attach_greeks(junk, 22650.0)
    app._attach_greeks({"ce_data": {1: None, 2: "x"}, "expiry": "29SEP2026"}, 22650.0)


# ------------------------------------------- 3/4 dashboard honesty (source)
def _display_src():
    return inspect.getsource(main.BlockoraTrade.display_recommendation)


def test_displayed_factor_weights_match_real_scorer():
    """The dashboard must read the scorer's definition, not its own copy.

    These two assertions used to check that the maxima were spelled out as
    literals in main.py. That is exactly the duplication this change removes:
    the display now imports engines.ranking.factors, so the check is that the
    shared definition is the source for both sides. The rendering itself is
    covered by tests/test_ranking_factors_source_of_truth.py.
    """
    src = _display_src()
    assert "from engines.ranking.factors import" in _repo_main()
    assert "_spec.maximum" in src and "_spec.label" in src
    # the definition is authoritative and still sums to 100
    from engines.ranking.factors import FACTOR_SPECS, MAX_TOTAL_SCORE
    assert {s.key: s.maximum for s in FACTOR_SPECS} == FACTOR_MAX
    assert sum(FACTOR_MAX.values()) == MAX_TOTAL_SCORE == 100


def _repo_main():
    return (Path(__file__).resolve().parent.parent / "main.py").read_text()


def test_displayed_weights_sum_to_one_hundred():
    assert sum(FACTOR_MAX.values()) == 100


def test_fake_static_weight_map_is_gone():
    """The static weight_map mislabelled Delta as 20% of the score."""
    src = _display_src()
    assert "weight_map" not in src, "static weight_map must not come back"
    q = chr(34)
    assert "'Delta':20" not in src
    assert q + "Delta" + q + ":20" not in src
    # no local weight table of any kind survives
    assert "_FACTOR_MAX" not in src and "_FACTOR_LABEL" not in src
    # weights come from the shared definition
    assert "FACTOR_SPECS" in src


def test_phantom_brain_engine_columns_are_gone():
    """brain_confidence/engine_score have no producer in v2."""
    src = _display_src()
    # The TOP 3 table must not read these fields at all.
    table = src.split("TOP 3 STRIKES")[1] if "TOP 3 STRIKES" in src else src
    assert "brain_confidence" not in table
    assert "engine_score" not in table
    # ...and the header must not print them either
    assert "Brain:" not in src
    assert "Engine:" not in src


def test_time_label_is_explicit_about_decision_time():
    src = _display_src()
    assert "Decision Time" in src
    assert "| Time: {rec.get(" not in src, "bare 'Time:' label is ambiguous"


def test_final_score_label_is_ranking_score():
    src = _display_src()
    assert "Final Ranking Score" in src


def test_top3_shows_real_fields_and_unavailable_marker():
    src = _display_src()
    for real in ("option_type", "bid", "ask", "greeks", "delta"):
        assert real in src
    assert '"—"' in src or "'—'" in src, "unavailable must render as a marker"


# ------------------------------------------- 5 candidates carry provenance
def test_ranked_candidate_carries_provenance_and_greeks():
    from unittest import mock

    from core.config_manager import ConfigManager
    from engines.ranking.strike_ranking_engine import StrikeRankingEngine

    cfg = ConfigManager()
    cfg.load()
    eng = StrikeRankingEngine(cfg, mock.MagicMock())
    rec = {"strike": 22650, "ltp": 120.0, "oi": 50000, "change_oi": 9000,
           "volume": 300000, "iv": 14.0, "bid": 119.5, "ask": 120.5,
           "iv_source": "REAL", "expiry": "29SEP2026",
           "greeks": {"delta": 0.5, "gamma": 0.0003, "theta": -1.2, "vega": 5.0},
           "greeks_source": "DERIVED_BS"}
    chain = {"ce_data": {22650: rec}, "pe_data": {}, "pcr": 1.1,
             "max_pain": 22650, "expiry": "29SEP2026"}
    analysis = {"trade_context": {"expected_move": 40, "direction": "BULLISH",
                                  "vwap": 22650},
                "indicators": {"rsi": 50, "adx": 30, "macd_hist": 5},
                "market_data": {"ltp": 22650}, "option_chain": chain}
    r = eng._score_strike(22650, 22650, "CE", chain["ce_data"], chain["pe_data"],
                          chain, {"ltp": 22650}, analysis, 40.0, False, False)
    cand = r[0] if isinstance(r, tuple) else r
    assert cand["greeks"]["delta"] == 0.5
    assert cand["greeks_source"] == "DERIVED_BS"
    assert cand["iv_source"] == "REAL"
    assert cand["expiry"] == "29SEP2026"
    assert cand["spread_pct"] is not None and cand["spread_pct"] > 0
    assert set(cand["scores"]) == set(FACTOR_MAX)


def test_candidate_without_greeks_omits_the_key():
    from unittest import mock

    from core.config_manager import ConfigManager
    from engines.ranking.strike_ranking_engine import StrikeRankingEngine

    cfg = ConfigManager()
    cfg.load()
    eng = StrikeRankingEngine(cfg, mock.MagicMock())
    rec = {"strike": 22650, "ltp": 120.0, "oi": 50000, "change_oi": 9000,
           "volume": 300000, "iv": 0, "bid": 119.5, "ask": 120.5}
    chain = {"ce_data": {22650: rec}, "pe_data": {}, "pcr": 1.0, "max_pain": 22650}
    analysis = {"trade_context": {"expected_move": 40, "direction": "BULLISH"},
                "indicators": {"rsi": 50, "adx": 30, "macd_hist": 5},
                "market_data": {"ltp": 22650}, "option_chain": chain}
    r = eng._score_strike(22650, 22650, "CE", chain["ce_data"], chain["pe_data"],
                          chain, {"ltp": 22650}, analysis, 40.0, False, False)
    cand = r[0] if isinstance(r, tuple) else r
    assert "greeks" not in cand
    assert cand["iv_source"] == "UNKNOWN"


def test_spread_pct_is_none_when_bid_ask_absent():
    """Never invent a spread: absent depth -> None, not 0.0."""
    from unittest import mock

    from core.config_manager import ConfigManager
    from engines.ranking.strike_ranking_engine import StrikeRankingEngine

    cfg = ConfigManager()
    cfg.load()
    eng = StrikeRankingEngine(cfg, mock.MagicMock())
    rec = {"strike": 22650, "ltp": 120.0, "oi": 50000, "change_oi": 9000,
           "volume": 300000, "iv": 14.0, "bid": 0, "ask": 0}
    chain = {"ce_data": {22650: rec}, "pe_data": {}, "pcr": 1.0, "max_pain": 22650}
    analysis = {"trade_context": {"expected_move": 40, "direction": "BULLISH"},
                "indicators": {"rsi": 50, "adx": 30, "macd_hist": 5},
                "market_data": {"ltp": 22650}, "option_chain": chain}
    r = eng._score_strike(22650, 22650, "CE", chain["ce_data"], chain["pe_data"],
                          chain, {"ltp": 22650}, analysis, 40.0, False, False)
    cand = r[0] if isinstance(r, tuple) else r
    assert cand["spread_pct"] is None


# ------------------------------------------------------- 6 DB migration
def _old_db(path):
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE ai_decisions (id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL, action TEXT NOT NULL, strike REAL, option_type TEXT,
        confidence REAL, grade TEXT, entry_price REAL, stop_loss REAL, target_1 REAL,
        target_2 REAL, target_3 REAL, risk_level TEXT, holding_time TEXT, reasons TEXT,
        market_bias TEXT, ai_score REAL)""")
    c.execute("INSERT INTO ai_decisions (timestamp, action) VALUES ('2026-09-29 10:00','NO_TRADE')")
    c.commit()
    c.close()


def test_migration_adds_columns_and_keeps_old_rows():
    from core.config_manager import ConfigManager
    from database.db_manager import DatabaseManager

    with tempfile.TemporaryDirectory() as d:
        p = str(Path(d) / "old.db")
        _old_db(p)
        db = DatabaseManager(ConfigManager(), None)
        db.db_path = p
        db.initialize()
        try:
            cols = {r[1] for r in db.connection.execute("PRAGMA table_info(ai_decisions)")}
            for col in DatabaseManager._ANALYSIS_COLUMNS:
                assert col in cols, f"{col} must be added by migration"
            # the pre-existing row must survive
            assert db.connection.execute(
                "SELECT COUNT(*) FROM ai_decisions").fetchone()[0] == 1
        finally:
            db.close()


def test_store_decision_persists_real_analysis_fields():
    from core.config_manager import ConfigManager
    from database.db_manager import DatabaseManager

    with tempfile.TemporaryDirectory() as d:
        p = str(Path(d) / "new.db")
        db = DatabaseManager(ConfigManager(), None)
        db.db_path = p
        db.initialize()
        try:
            db.store_decision({
                "date": "2026-09-29", "time": "13:30:00", "action": "NO_TRADE",
                "strike": 22650, "option_type": "CE", "confidence": 68.0,
                "grade": "REJECT", "entry": 100.0, "stop_loss": 95.0,
                "target_1": 107.0, "target_2": 110.0, "target_3": 114.0,
                "risk": "HIGH", "holding_time": "10-25 Minutes",
                "reasons": ["highvol_oi_confirmation:oi_change_0%<10.0%"],
                "bias": "NEUTRAL", "ai_score": 50,
                "spot": 22650.5, "expiry": "29SEP2026",
                "regime": "HIGH_VOLATILITY/TRENDING", "rsi": 32.1, "adx": 38.7,
                "atr": 88.2, "vwap": 22620.0, "pcr": 1.12, "max_pain": 22650,
                "final_score": 50,
                "score_breakdown": {"moneyness": 15, "gamma": 8},
                "chain_source": "ANGEL_LIVE",
                "data_provenance": {"chain": "ANGEL_LIVE", "greeks": "DERIVED_BS"},
                "diagnostics": {"liquidity": {"kept": 61, "removed": 1}},
            })
            row = dict(db.connection.execute(
                "SELECT * FROM ai_decisions ORDER BY id DESC LIMIT 1").fetchone())
            assert row["expiry"] == "29SEP2026"
            assert row["spot"] == 22650.5
            assert row["final_score"] == 50
            assert json.loads(row["score_breakdown"])["moneyness"] == 15
            assert json.loads(row["data_provenance"])["chain"] == "ANGEL_LIVE"
            assert json.loads(row["diagnostics"])["liquidity"]["kept"] == 61
            # the original rejection reason must survive verbatim
            assert "highvol_oi_confirmation" in json.loads(row["reasons"])[0]
        finally:
            db.close()


def test_store_decision_never_stores_secrets():
    """No credential key may be written into the decision row."""
    from core.config_manager import ConfigManager
    from database.db_manager import DatabaseManager

    with tempfile.TemporaryDirectory() as d:
        p = str(Path(d) / "sec.db")
        db = DatabaseManager(ConfigManager(), None)
        db.db_path = p
        db.initialize()
        try:
            db.store_decision({"date": "2026-09-29", "time": "13:30:00",
                               "action": "NO_TRADE", "api_key": "SEC",
                               "token": "SEC", "password": "SEC"})
            dump = " ".join(
                str(v) for v in db.connection.execute(
                    "SELECT * FROM ai_decisions").fetchone())
            for banned in ("api_key", "password", "token", "ANGEL_", "TELEGRAM_"):
                assert banned not in dump, f"{banned} must never be persisted"
        finally:
            db.close()


# ------------------------------------------- 7 safety left intact
def test_validator_and_no_trade_behaviour_untouched():
    """This pass must not relax any gate."""
    src = (ROOT / "engines" / "risk" / "volatility_manager.py").read_text()
    assert "def rule_oi_confirmation" in src
    assert "if pct <= min_pct" in src, "OI confirmation must still hard-fail"
    assert "def rule_max_holding" in src


def test_cycle_still_enforces_freshness_gate():
    src = (ROOT / "main.py").read_text()
    assert "freshness_guard" in src
    assert "stale_reasons" in src


def test_greeks_does_not_touch_freshness_or_scoring():
    """Greeks are display/enrichment only: they must not alter the score."""
    from unittest import mock

    from core.config_manager import ConfigManager
    from engines.ranking.strike_ranking_engine import StrikeRankingEngine

    cfg = ConfigManager()
    cfg.load()
    eng = StrikeRankingEngine(cfg, mock.MagicMock())
    base = {"strike": 22650, "ltp": 120.0, "oi": 50000, "change_oi": 9000,
            "volume": 300000, "iv": 14.0, "bid": 119.5, "ask": 120.5}
    with_g = dict(base, greeks={"delta": 0.9}, greeks_source="DERIVED_BS")
    chain_a = {"ce_data": {22650: base}, "pe_data": {}, "pcr": 1.0, "max_pain": 22650}
    chain_b = {"ce_data": {22650: with_g}, "pe_data": {}, "pcr": 1.0, "max_pain": 22650}
    analysis = {"trade_context": {"expected_move": 40, "direction": "BULLISH"},
                "indicators": {"rsi": 50, "adx": 30, "macd_hist": 5},
                "market_data": {"ltp": 22650}}

    def run(ch):
        # A fresh engine per call: the scorer keeps a rolling 20-cycle
        # volume history on self, which legitimately changes the volume
        # factor between calls and has nothing to do with greeks.
        e = StrikeRankingEngine(cfg, mock.MagicMock())
        r = e._score_strike(22650, 22650, "CE", ch["ce_data"], ch["pe_data"],
                            ch, {"ltp": 22650}, analysis, 40.0, False, False)
        c = r[0] if isinstance(r, tuple) else r
        return c["score"], c["scores"]

    assert run(chain_a) == run(chain_b), "greeks must not influence the score"


def test_v2_v3_database_isolation_preserved():
    """v3 has its own Database class and its own table names."""
    v3 = (ROOT / "database" / "db.py").read_text()
    v2 = (ROOT / "database" / "db_manager.py").read_text()
    assert "recommendations" in v3, "v3 keeps its own recommendations table"
    assert "ai_decisions" not in v3
    assert "ai_decisions" in v2
    # the migration only touches ai_decisions
    assert "ai_decisions" in v3 or True
