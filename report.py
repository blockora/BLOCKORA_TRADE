"""Signal Report - sirf aaj ke signals, kabhi bhi dekho"""
import sys
sys.path.insert(0, '.')
from datetime import datetime
from core.config_manager import ConfigManager
from core.logger_manager import LoggerManager
from database.db_manager import DatabaseManager

config = ConfigManager(); config.load()
logger = LoggerManager(config); logger.setup()
db = DatabaseManager(config, logger); db.initialize()
db.cleanup_old_signals()  # sirf aaj ka data

today = datetime.now().strftime("%Y-%m-%d")
cur = db.connection.cursor()
cur.execute("SELECT * FROM signal_tracker WHERE date=? ORDER BY id", (today,))
rows = [dict(r) for r in cur.fetchall()]

HIT = {"WIN_T1": "T1 hit", "WIN_T2": "T2 hit", "WIN_T3": "T3 hit",
       "LOSS": "SL hit", "EXPIRED": "Time-out", "EXPIRED_WIN": "Time-out(+)", "ACTIVE": "LIVE"}

print("=" * 72)
print(f"  📊 SIGNAL PERFORMANCE REPORT — {today}")
print("=" * 72)
if not rows:
    print("  Aaj koi signal nahi aaya.")
else:
    print(f"  {'Time':<7}{'Option':<12}{'Entry':<8}{'Hit':<11}{'PnL':<8}{'Result'}")
    print("  " + "-" * 68)
    for r in rows:
        t = (r["signal_time"] or "")[:5]
        opt = f"{int(r['strike'])} {r['option_type']}"
        res = "✅ PASS" if r["status"].startswith("WIN") else "❌ FAIL" if r["status"] in ("LOSS", "EXPIRED") else "⏳ LIVE"
        print(f"  {t:<7}{opt:<12}{r['entry']:<8}{HIT.get(r['status'], r['status']):<11}{r['est_pnl']:<8}{res}")
    print("  " + "-" * 68)
    wins = sum(1 for r in rows if r["status"].startswith("WIN"))
    loss = sum(1 for r in rows if r["status"] in ("LOSS", "EXPIRED"))
    live = sum(1 for r in rows if r["status"] == "ACTIVE")
    pnl = round(sum(r["est_pnl"] or 0 for r in rows), 1)
    closed = wins + loss
    print(f"  Total: {len(rows)} | ✅ Pass: {wins} | ❌ Fail: {loss} | ⏳ Live: {live}")
    print(f"  Net PnL (est): {pnl} pts" + (f" | Win Rate: {round(100*wins/closed,1)}%" if closed else ""))
print("=" * 72)
