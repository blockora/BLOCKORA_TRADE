"""Market Memory - Persistent storage for market observations.

Uses SQLite storage via the project's existing database connection pattern.
All values are stored as-is; missing values are stored as None (null in SQLite).
"""

import json
import sqlite3
from datetime import datetime


class MarketMemory:
    """Persistent storage for market-intelligence observations.

    Stores observations from strike-ranking decisions for later similarity
    analysis and outcome learning. Uses SQLite via the project's database
    connection pattern. Missing values are stored as None (null in SQLite).

    Does NOT influence ranking, scores, strikes, risk limits, recommendations,
    or trading behavior. Pure observation storage only.
    """

    DB_NAME = "blockora_trade.db"

    def __init__(self, db_path=None):
        if db_path is None:
            from core.config_manager import ConfigManager
            config = ConfigManager()
            db_path = config.get("database.path", "./database/blockora_trade.db")
        self.db_path = db_path
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._create_table()

    def _create_table(self):
        cursor = self.connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                spot REAL,
                market_regime TEXT,
                direction TEXT,
                adx REAL,
                rsi REAL,
                macd REAL,
                atr REAL,
                vwap_relationship TEXT,
                mtf_state TEXT,
                expected_move REAL,
                oi_context TEXT,
                volume_context TEXT,
                candidate_strikes TEXT,
                option_type TEXT,
                expiry TEXT,
                strike REAL,
                baseline_score REAL,
                enhanced_score REAL,
                score_margin REAL,
                stability TEXT,
                for_reasons TEXT,
                against_reasons TEXT,
                ltp REAL,
                ltp_timestamp TEXT,
                data_quality TEXT
            )
        """)
        self.connection.commit()

    def store_observation(self, observation: dict):
        import json
        cursor = self.connection.cursor()

        fields = {
            "timestamp": observation.get("timestamp"),
            "symbol": observation.get("symbol"),
            "spot": observation.get("spot"),
            "market_regime": observation.get("market_regime"),
            "direction": observation.get("direction"),
            "adx": observation.get("adx"),
            "rsi": observation.get("rsi"),
            "macd": observation.get("macd"),
            "atr": observation.get("atr"),
            "vwap_relationship": observation.get("vwap_relationship"),
            "mtf_state": observation.get("mtf_state"),
            "expected_move": observation.get("expected_move"),
            "oi_context": observation.get("oi_context"),
            "volume_context": observation.get("volume_context"),
            "candidate_strikes": json.dumps(observation.get("candidate_strikes"))
            if observation.get("candidate_strikes")
            else None,
            "option_type": observation.get("option_type"),
            "expiry": observation.get("expiry"),
            "strike": observation.get("strike"),
            "baseline_score": observation.get("baseline_score"),
            "enhanced_score": observation.get("enhanced_score"),
            "score_margin": observation.get("score_margin"),
            "stability": observation.get("stability"),
            "for_reasons": json.dumps(observation.get("for_reasons"))
            if observation.get("for_reasons")
            else None,
            "against_reasons": json.dumps(observation.get("against_reasons"))
            if observation.get("against_reasons")
            else None,
            "ltp": observation.get("ltp"),
            "ltp_timestamp": observation.get("ltp_timestamp"),
            "data_quality": observation.get("data_quality"),
        }

        present_fields = {k: v for k, v in fields.items() if v is not None}

        if not present_fields:
            return

        field_names = ", ".join(present_fields.keys())
        field_placeholders = ", ".join(["?"] * len(present_fields))
        values = [fields[k] for k in present_fields]

        cursor = self.connection.cursor()
        cursor.execute(
            f"INSERT INTO market_observations ({field_names})"
            f" VALUES ({field_placeholders})",
            values,
        )
        self.connection.commit()

    def get_recent(self, limit: int = 100):
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT * FROM market_observations ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()

        columns = [desc[0] for desc in cursor.description]
        results = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                value = row[i]
                if col in ("candidate_strikes", "for_reasons", "against_reasons"):
                    try:
                        value = json.loads(value) if value is not None else None
                    except (json.JSONDecodeError, TypeError):
                        value = None
                row_dict[col] = value
            results.append(row_dict)

        return results

    def count(self):
        cursor = self.connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM market_observations")
        return cursor.fetchone()[0]

    def clear_for_test(self):
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM market_observations")
        self.connection.commit()
