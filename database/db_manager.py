"""Database Manager - SQLite database operations"""
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path


class DatabaseManager:
    """Manages SQLite database operations"""

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self.db_path = config.get("database.path", "./database/blockora_trade.db")
        self.connection = None

    def initialize(self):
        """Initialize database and create tables"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._create_tables()
        self._create_sub_tables()
        self._create_learning_tables()

    def _create_tables(self):
        """Create all database tables"""
        cursor = self.connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                ltp REAL, open REAL, high REAL, low REAL,
                close REAL, volume INTEGER, vix REAL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS option_chain (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                strike REAL NOT NULL,
                ce_ltp REAL, ce_oi INTEGER, ce_volume INTEGER, ce_iv REAL,
                pe_ltp REAL, pe_oi INTEGER, pe_volume INTEGER, pe_iv REAL,
                pcr REAL, max_pain REAL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                strike REAL, option_type TEXT,
                confidence REAL, grade TEXT,
                entry_price REAL, stop_loss REAL,
                target_1 REAL, target_2 REAL, target_3 REAL,
                risk_level TEXT, holding_time TEXT,
                reasons TEXT, market_bias TEXT, ai_score REAL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT UNIQUE,
                date TEXT NOT NULL,
                strike REAL, option_type TEXT,
                entry_price REAL, exit_price REAL,
                entry_time TEXT, exit_time TEXT,
                pnl REAL, result TEXT,
                confidence REAL, user_action TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                module TEXT, level TEXT, message TEXT
            )
        """)

        self.connection.commit()

    def store_decision(self, recommendation):
        """Store AI decision in database"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                INSERT INTO ai_decisions
                (timestamp, action, strike, option_type, confidence, grade,
                 entry_price, stop_loss, target_1, target_2, target_3,
                 risk_level, holding_time, reasons, market_bias, ai_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                recommendation.get("date", "") + " " + recommendation.get("time", ""),
                recommendation.get("action", "NO_TRADE"),
                recommendation.get("strike", 0),
                recommendation.get("option_type", ""),
                recommendation.get("confidence", 0),
                recommendation.get("grade", ""),
                recommendation.get("entry", 0),
                recommendation.get("stop_loss", 0),
                recommendation.get("target_1", 0),
                recommendation.get("target_2", 0),
                recommendation.get("target_3", 0),
                recommendation.get("risk", ""),
                recommendation.get("holding_time", ""),
                json.dumps(recommendation.get("reasons", [])),
                recommendation.get("bias", ""),
                recommendation.get("ai_score", 0)
            ))
            self.connection.commit()
        except Exception as e:
            pass

    def get_session_summary(self):
        """Get today's session summary"""
        cursor = self.connection.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN action != 'NO_TRADE' THEN 1 ELSE 0 END) as signals,
                   AVG(confidence) as avg_confidence
            FROM ai_decisions WHERE timestamp LIKE ?
        """, (f"{today}%",))
        row = cursor.fetchone()
        return {
            "date": today,
            "total_cycles": row["total"] if row else 0,
            "signals_generated": row["signals"] if row else 0,
            "avg_confidence": row["avg_confidence"] if row else 0
        }

    def is_connected(self):
        return self.connection is not None

    def backup(self):
        """Create database backup with auto-rotation (keep last 3)"""
        try:
            backup_path = self.db_path.replace(".db", f"_backup_{datetime.now().strftime('%Y%m%d')}.db")
            backup_conn = sqlite3.connect(backup_path)
            self.connection.backup(backup_conn)
            backup_conn.close()
            
            # Auto-rotation: keep only last 3 backups
            import glob
            backup_dir = Path(self.db_path).parent
            backup_pattern = Path(self.db_path).stem + "_backup_*.db"
            backups = sorted(backup_dir.glob(backup_pattern), key=lambda p: p.stat().st_mtime, reverse=True)
            if len(backups) > 3:
                deleted = 0
                for old_backup in backups[3:]:
                    try:
                        old_backup.unlink()
                        deleted += 1
                    except Exception:
                        pass
                if deleted and self.logger:
                    self.logger.info(f"Backup rotation: deleted {deleted} old backups, kept 3")
        except Exception as e:
            if self.logger:
                self.logger.error(f"DB error in {self._caller_name()}: {e}")

    def _create_sub_tables(self):
        cursor = self.connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                user_id TEXT PRIMARY KEY,
                username TEXT, first_name TEXT,
                status TEXT DEFAULT 'KNOWN',
                start_date TEXT, expiry_date TEXT,
                last_reminder TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT, username TEXT, first_name TEXT,
                utr TEXT, amount TEXT, time TEXT, status TEXT DEFAULT 'PENDING'
            )
        """)
        self.connection.commit()

    def upsert_user(self, user_id, username, first_name):
        try:
            cur = self.connection.cursor()
            cur.execute("INSERT OR IGNORE INTO subscribers (user_id, username, first_name) VALUES (?,?,?)",
                        (user_id, username, first_name))
            cur.execute("UPDATE subscribers SET username=?, first_name=? WHERE user_id=?",
                        (username, first_name, user_id))
            self.connection.commit()
        except Exception as e:
            self.logger.error(f"DB error in {self._caller_name()}: {e}")

    def get_user(self, user_id):
        try:
            cur = self.connection.cursor()
            cur.execute("SELECT * FROM subscribers WHERE user_id=?", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    def activate(self, user_id, days=30):
        try:
            start = datetime.now()
            expiry = (start + timedelta(days=days)).strftime("%Y-%m-%d")
            cur = self.connection.cursor()
            cur.execute("UPDATE subscribers SET status='ACTIVE', start_date=?, expiry_date=? WHERE user_id=?",
                        (start.strftime("%Y-%m-%d"), expiry, user_id))
            self.connection.commit()
            return expiry
        except Exception:
            return None

    def expire(self, user_id):
        try:
            cur = self.connection.cursor()
            cur.execute("UPDATE subscribers SET status='EXPIRED' WHERE user_id=?", (user_id,))
            self.connection.commit()
        except Exception as e:
            self.logger.error(f"DB error in {self._caller_name()}: {e}")

    def list_active(self):
        try:
            cur = self.connection.cursor()
            cur.execute("SELECT * FROM subscribers WHERE status='ACTIVE'")
            return [dict(r) for r in cur.fetchall()]
        except Exception:
            return []

    def add_pending(self, user_id, username, first_name, utr, amount):
        try:
            cur = self.connection.cursor()
            cur.execute("INSERT INTO pending_payments (user_id, username, first_name, utr, amount, time) VALUES (?,?,?,?,?,?)",
                        (user_id, username, first_name, utr, amount, datetime.now().strftime("%Y-%m-%d %H:%M")))
            self.connection.commit()
        except Exception as e:
            self.logger.error(f"DB error in {self._caller_name()}: {e}")

    def set_reminder(self, user_id, date_str):
        try:
            cur = self.connection.cursor()
            cur.execute("UPDATE subscribers SET last_reminder=? WHERE user_id=?", (date_str, user_id))
            self.connection.commit()
        except Exception as e:
            self.logger.error(f"DB error in {self._caller_name()}: {e}")

    def _create_learning_tables(self):
        cursor = self.connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_tracker (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_time TEXT, date TEXT,
                strike REAL, option_type TEXT,
                entry REAL, sl REAL, t1 REAL, t2 REAL, t3 REAL,
                spot_at_signal REAL, confidence REAL,
                move30 REAL, direction TEXT,
                status TEXT DEFAULT 'ACTIVE',
                outcome_time TEXT, est_pnl REAL DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS learning_weights (
                key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
            )
        """)
        self.connection.commit()

    def add_tracked_signal(self, rec, spot, move30=0, direction=""):
        try:
            cur = self.connection.cursor()
            cur.execute("""INSERT INTO signal_tracker
                (signal_time, date, strike, option_type, entry, sl, t1, t2, t3,
                 spot_at_signal, confidence, move30, direction)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rec.get("time"), rec.get("date"), rec.get("strike"), rec.get("option_type"),
                 rec.get("entry"), rec.get("stop_loss"), rec.get("target_1"),
                 rec.get("target_2"), rec.get("target_3"), spot,
                 rec.get("confidence"), move30, direction))
            self.connection.commit()
        except Exception:
            pass

    def get_active_signals(self):
        try:
            cur = self.connection.cursor()
            cur.execute("SELECT * FROM signal_tracker WHERE status='ACTIVE'")
            return [dict(r) for r in cur.fetchall()]
        except Exception:
            return []

    def close_signal(self, sig_id, status, est_pnl):
        try:
            cur = self.connection.cursor()
            cur.execute("UPDATE signal_tracker SET status=?, est_pnl=?, outcome_time=? WHERE id=?",
                        (status, est_pnl, datetime.now().strftime("%H:%M:%S"), sig_id))
            self.connection.commit()
            return True
        except Exception as e:
            self.logger.error(f"DB error closing signal {sig_id}: {e}")
            return False

    def get_closed_outcomes(self, limit=40):
        try:
            cur = self.connection.cursor()
            cur.execute("SELECT * FROM signal_tracker WHERE status!='ACTIVE' ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]
        except Exception:
            return []

    def get_tracker_stats(self):
        try:
            cur = self.connection.cursor()
            cur.execute("SELECT status, COUNT(*) as c FROM signal_tracker GROUP BY status")
            rows = {r["status"]: r["c"] for r in cur.fetchall()}
            wins = sum(v for k, v in rows.items() if k.startswith("WIN"))
            losses = rows.get("LOSS", 0) + rows.get("EXPIRED", 0)
            total = wins + losses
            return {"wins": wins, "losses": losses, "active": rows.get("ACTIVE", 0),
                    "win_rate": round(100 * wins / total, 1) if total else 0, "total": total}
        except Exception:
            return {"wins": 0, "losses": 0, "active": 0, "win_rate": 0, "total": 0}

    def save_learning(self, params):
        try:
            cur = self.connection.cursor()
            cur.execute("INSERT OR REPLACE INTO learning_weights (key, value, updated_at) VALUES ('params', ?, ?)",
                        (json.dumps(params), datetime.now().isoformat()))
            self.connection.commit()
        except Exception:
            pass

    def get_learning(self):
        try:
            cur = self.connection.cursor()
            cur.execute("SELECT value FROM learning_weights WHERE key='params'")
            row = cur.fetchone()
            return json.loads(row["value"]) if row else {}
        except Exception:
            return {}

    def cleanup_old_signals(self):
        """Sirf aaj ka data rakho - purane din auto-delete"""
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            cur = self.connection.cursor()
            cur.execute("DELETE FROM signal_tracker WHERE date != ?", (today,))
            self.connection.commit()
        except Exception:
            pass

    def get_daily_risk_stats(self):
        """Aaj ke trades ka risk summary (limits check ke liye)"""
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            cur = self.connection.cursor()
            cur.execute("SELECT status, est_pnl FROM signal_tracker WHERE date=? ORDER BY id", (today,))
            rows = [dict(r) for r in cur.fetchall()]
        except Exception:
            return {"trades_today": 0, "closed_today": 0, "daily_pnl": 0.0, "consec_losses": 0}
        closed = [r for r in rows if (r["status"] or "").startswith(("WIN", "LOSS", "EXPIRED"))]
        pnl = sum(float(r["est_pnl"] or 0) for r in closed)
        consec = 0
        for r in reversed(closed):
            if r["status"] in ("LOSS", "EXPIRED"):
                consec += 1
            else:
                break
        return {"trades_today": len(rows), "closed_today": len(closed),
                "daily_pnl": round(pnl, 1), "consec_losses": consec}

    def _caller_name(self):
        import inspect
        return inspect.stack()[1].function if len(inspect.stack()) > 1 else "unknown"

    def close(self):
        if self.connection:
            self.connection.close()
