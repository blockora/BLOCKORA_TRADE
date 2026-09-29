"""Tests: database schema, persistence, append-only semantics."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import Database


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.initialize()
    yield d
    d.close()


def _chain_quote(ts="2026-09-28T10:00:00Z", strike=24500.0, opt="CE", **over):
    row = {"snapshot_ts": ts, "received_ts": ts, "latency_ms": 120.0, "source": "TEST",
           "expiry": "2026-10-01", "strike": strike, "option_type": opt,
           "ltp": 105.5, "bid": 105.0, "ask": 106.0, "iv": 12.5,
           "volume": 5000, "oi": 20000, "change_oi": 1500, "quality_status": "OK"}
    row.update(over)
    row.pop("ltp", None) if over.get("_drop_ltp") else None
    return row


def test_schema_creates_all_tables(db):
    tables = {r["name"] for r in db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {"schema_version", "underlying_ticks", "chain_snapshots", "candles",
                "indicators", "features", "component_scores", "recommendations",
                "outcomes", "backtest_runs", "backtest_trades", "calibration_models"}
    assert expected <= tables


def test_chain_snapshot_roundtrip_with_nulls(db):
    q = _chain_quote(iv=None, volume=None)          # missing IV/volume stay NULL
    db.insert_chain_quotes([q])
    row = dict(db.conn.execute("SELECT * FROM chain_snapshots").fetchone())
    assert row["iv"] is None and row["volume"] is None
    assert row["ltp"] == 105.5 and row["quality_status"] == "OK"


def test_chain_snapshot_rejects_bad_option_type(db):
    q = _chain_quote(option_type="XX")
    with pytest.raises(Exception):
        db.insert_chain_quotes([q])


def test_candle_rejects_unclosed_bar(db):
    ok = db.insert_candle({"symbol": "NIFTY", "timeframe": "5m", "bar_ts": "2026-09-28T10:00:00Z",
                           "bar_close_ts": None, "open": 1, "high": 2, "low": 1, "close": 2,
                           "source": "TEST"})
    assert ok is False
    ok = db.insert_candle({"symbol": "NIFTY", "timeframe": "5m", "bar_ts": "2026-09-28T10:00:00Z",
                           "bar_close_ts": "2026-09-28T10:05:00Z", "open": 1, "high": 2,
                           "low": 1, "close": 2, "source": "TEST"})
    assert ok is True


def test_recommendation_roundtrip(db):
    rid = db.insert_recommendation({
        "decision_ts": "2026-09-28T10:00:00Z", "decision": "RECOMMENDATION",
        "market_bias": "BULLISH", "side": "CALL", "strike": 24500.0,
        "expiry": "2026-10-01", "entry": 105.5, "stop_loss": 95.0,
        "t1": 120.0, "t2": 135.0, "t3": 150.0, "expected_hold_min": 120,
        "model_score": 78.4, "calibrated_state": "UNAVAILABLE",
        "risk_pct": 1.2, "reward_risk": 1.8, "trade_grade": "A",
        "key_reasons": ["HTF+MTF aligned"], "rejected_alternatives": ["24550 CE score 74"],
        "pipeline_version": "3.0.0-phase1", "weights_hash": "abc123", "created_ts": "x",
        "diagnostics": {"spread_pct": 1.2},
    })
    rows = db.recent_recommendations()
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == rid and r["side"] == "CALL" and r["model_score"] == 78.4
    assert json.loads(r["key_reasons"]) == ["HTF+MTF aligned"]
    assert r["calibrated_confidence"] is None  # never fabricated


def test_no_trade_rows_persisted(db):
    db.insert_recommendation({
        "decision_ts": "2026-09-28T10:00:00Z", "decision": "NO_TRADE",
        "no_trade_reason": "filter:F5_spread", "pipeline_version": "3.0.0-phase1",
        "weights_hash": "abc123", "created_ts": "x",
    })
    rows = db.recent_recommendations()
    assert rows[0]["decision"] == "NO_TRADE" and rows[0]["no_trade_reason"] == "filter:F5_spread"


def test_outcome_persists_and_links(db):
    rid = db.insert_recommendation({
        "decision_ts": "2026-09-28T10:00:00Z", "decision": "RECOMMENDATION",
        "pipeline_version": "3.0.0-phase1", "weights_hash": "abc", "created_ts": "x",
    })
    oid = db.insert_outcome({"recommendation_id": rid, "outcome": "WIN_T1",
                             "mfe": 18.0, "mae": -6.0, "bars_to_outcome": 7,
                             "evaluated_ts": "2026-09-28T11:35:00Z",
                             "source": "LIVE_REPLAY", "data_quality": "OK"})
    open_recs = db.open_recommendations()
    assert open_recs == []                      # no longer open
    row = dict(db.conn.execute("SELECT * FROM outcomes").fetchone())
    assert row["id"] == oid and row["outcome"] == "WIN_T1"


def test_outcome_rejects_invalid_value(db):
    rid = db.insert_recommendation({
        "decision_ts": "2026-09-28T10:00:00Z", "decision": "RECOMMENDATION",
        "pipeline_version": "3.0.0-phase1", "weights_hash": "abc", "created_ts": "x"})
    with pytest.raises(Exception):
        db.insert_outcome({"recommendation_id": rid, "outcome": "MAYBE",
                           "evaluated_ts": "2026-09-28T11:00:00Z"})


def test_append_only_outcome_history(db):
    rid = db.insert_recommendation({
        "decision_ts": "2026-09-28T10:00:00Z", "decision": "RECOMMENDATION",
        "pipeline_version": "3.0.0-phase1", "weights_hash": "abc", "created_ts": "x"})
    db.insert_outcome({"recommendation_id": rid, "outcome": "LOSS",
                       "evaluated_ts": "2026-09-28T11:00:00Z"})
    db.insert_outcome({"recommendation_id": rid, "outcome": "WIN_T1",
                       "evaluated_ts": "2026-09-28T11:05:00Z"})  # correction = new row
    n = db.conn.execute("SELECT COUNT(*) c FROM outcomes").fetchone()["c"]
    assert n == 2
