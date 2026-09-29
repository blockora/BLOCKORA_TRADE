"""BLOCKORA_TRADE v3 — SQLite access layer.

Schema init from database/schema.sql; append-only helpers for snapshots,
recommendations and outcomes. See docs/SCHEMA.md for design intent.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "database" / "schema.sql"


class Database:
    def __init__(self, path: str | Path, journal_mode: str = "WAL",
                 busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(f"PRAGMA journal_mode={journal_mode};")
        self.conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms};")
        self.conn.execute("PRAGMA foreign_keys=ON;")

    def initialize(self) -> None:
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.conn.commit()

    # -- writes -------------------------------------------------------------
    def insert_chain_quotes(self, quotes: Iterable[dict[str, Any]]) -> None:
        rows = [(
            q["snapshot_ts"], q["received_ts"], q.get("latency_ms"), q["source"],
            q["expiry"], q["strike"], q["option_type"],
            q.get("ltp"), q.get("bid"), q.get("ask"), q.get("iv"),
            q.get("volume"), q.get("oi"), q.get("change_oi"),
            q.get("quality_status", "UNKNOWN"),
        ) for q in quotes]
        self.conn.executemany(
            """INSERT INTO chain_snapshots
               (snapshot_ts, received_ts, latency_ms, source, expiry, strike, option_type,
                ltp, bid, ask, iv, volume, oi, change_oi, quality_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        self.conn.commit()

    def insert_tick(self, tick: dict[str, Any]) -> None:
        self.conn.execute(
            """INSERT INTO underlying_ticks
               (snapshot_ts, received_ts, latency_ms, source, symbol, ltp, change_pct, quality_status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (tick["snapshot_ts"], tick["received_ts"], tick.get("latency_ms"), tick["source"],
             tick["symbol"], tick.get("ltp"), tick.get("change_pct"),
             tick.get("quality_status", "UNKNOWN")))
        self.conn.commit()

    def insert_candle(self, c: dict[str, Any]) -> bool:
        """Insert a CLOSED candle only; returns False if the bar is not closed yet."""
        if not c.get("bar_close_ts"):
            return False
        try:
            self.conn.execute(
                """INSERT OR REPLACE INTO candles
                   (symbol, timeframe, bar_ts, bar_close_ts, open, high, low, close, volume, source, quality_status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (c["symbol"], c["timeframe"], c["bar_ts"], c["bar_close_ts"],
                 c["open"], c["high"], c["low"], c["close"], c.get("volume"),
                 c["source"], c.get("quality_status", "OK")))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def insert_recommendation(self, rec: dict[str, Any]) -> int:
        cur = self.conn.execute(
            """INSERT INTO recommendations
               (decision_ts, decision, market_bias, side, strike, expiry,
                entry, stop_loss, t1, t2, t3, expected_hold_min,
                model_score, calibrated_confidence, calibrated_state,
                risk_pct, reward_risk, trade_grade,
                key_reasons, rejected_alternatives, no_trade_reason, diagnostics,
                pipeline_version, weights_hash, calibrator_hash, created_ts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rec["decision_ts"], rec["decision"], rec.get("market_bias"), rec.get("side"),
             rec.get("strike"), rec.get("expiry"),
             rec.get("entry"), rec.get("stop_loss"), rec.get("t1"), rec.get("t2"), rec.get("t3"),
             rec.get("expected_hold_min"),
             rec.get("model_score"), rec.get("calibrated_confidence"),
             rec.get("calibrated_state", "UNAVAILABLE"),
             rec.get("risk_pct"), rec.get("reward_risk"), rec.get("trade_grade"),
             json.dumps(rec.get("key_reasons", [])), json.dumps(rec.get("rejected_alternatives", [])),
             rec.get("no_trade_reason"), json.dumps(rec.get("diagnostics", {})),
             rec["pipeline_version"], rec.get("weights_hash"), rec.get("calibrator_hash"),
             rec["created_ts"]))
        self.conn.commit()
        return int(cur.lastrowid)

    def insert_outcome(self, outcome: dict[str, Any]) -> int:
        cur = self.conn.execute(
            """INSERT INTO outcomes
               (recommendation_id, outcome, mfe, mae, bars_to_outcome, seconds_to_outcome,
                exit_reason, evaluated_ts, source, data_quality)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (outcome["recommendation_id"], outcome["outcome"], outcome.get("mfe"),
             outcome.get("mae"), outcome.get("bars_to_outcome"), outcome.get("seconds_to_outcome"),
             outcome.get("exit_reason"), outcome["evaluated_ts"],
             outcome.get("source", "LIVE_REPLAY"), outcome.get("data_quality", "OK")))
        self.conn.commit()
        return int(cur.lastrowid)

    # -- reads --------------------------------------------------------------
    def recent_recommendations(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM recommendations ORDER BY decision_ts DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def open_recommendations(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT * FROM recommendations
               WHERE decision='RECOMMENDATION'
                 AND id NOT IN (SELECT recommendation_id FROM outcomes)""").fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self.conn.close()
