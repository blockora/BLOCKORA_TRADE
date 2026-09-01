"""Outcome Tracker + Self-Learner - System khud seekhta hai"""
from datetime import datetime


class OutcomeTracker:
    DELTA = 0.55
    MAX_AGE_MIN = 60

    def __init__(self, db, logger):
        self.db = db
        self.logger = logger

    def register(self, rec, spot, move30=0, direction=""):
        self.db.add_tracked_signal(rec, spot, move30, direction)
        self.logger.info(f"📌 Signal saved: {rec.get('action')} @ {spot}")

    def update(self, spot):
        for sig in self.db.get_active_signals():
            try:
                t0 = datetime.strptime(sig["signal_time"], "%H:%M:%S")
                age = (datetime.now() - t0).total_seconds() / 60.0
            except Exception:
                age = 999
            direction = 1 if sig["option_type"] == "CE" else -1
            est = sig["entry"] + (self.DELTA * (spot - sig["spot_at_signal"]) * direction)
            pnl = round(est - sig["entry"], 2)

            if est <= sig["sl"]:
                self.db.close_signal(sig["id"], "LOSS", pnl)
                self.logger.info(f"📊 Outcome: {sig['option_type']} {sig['strike']} → LOSS ({pnl})")
            elif est >= sig["t3"]:
                self.db.close_signal(sig["id"], "WIN_T3", pnl)
                self.logger.info(f"📊 Outcome: {sig['option_type']} {sig['strike']} → WIN T3 ({pnl})")
            elif est >= sig["t2"]:
                self.db.close_signal(sig["id"], "WIN_T2", pnl)
                self.logger.info(f"📊 Outcome: {sig['option_type']} {sig['strike']} → WIN T2 ({pnl})")
            elif est >= sig["t1"]:
                self.db.close_signal(sig["id"], "WIN_T1", pnl)
                self.logger.info(f"📊 Outcome: {sig['option_type']} {sig['strike']} → WIN T1 ({pnl})")
            elif age > self.MAX_AGE_MIN:
                st = "EXPIRED_WIN" if pnl > 0 else "EXPIRED"
                self.db.close_signal(sig["id"], st, pnl)
                self.logger.info(f"📊 Outcome: {sig['option_type']} {sig['strike']} → {st} ({pnl})")


class SelfLearner:
    """Closed signals ka analysis karke system ko auto-adjust karta hai"""

    def __init__(self, db, logger):
        self.db = db
        self.logger = logger
        self.params = db.get_learning() or {}

    def get_params(self):
        return self.params

    def review(self):
        closed = self.db.get_closed_outcomes(40)
        n = len(closed)
        if n < 8:
            return self.params

        wins = sum(1 for r in closed if r["status"].startswith("WIN"))
        wr = round(100 * wins / n, 1)

        # Overall win-rate se threshold adjust (safe: max +4)
        thr_adj = 4 if wr < 45 else (2 if wr < 50 else 0)

        # Direction-wise weakness detect karo
        ce = [r for r in closed if r["option_type"] == "CE"]
        pe = [r for r in closed if r["option_type"] == "PE"]
        ce_wr = 100 * sum(1 for r in ce if r["status"].startswith("WIN")) / len(ce) if ce else 50
        pe_wr = 100 * sum(1 for r in pe if r["status"].startswith("WIN")) / len(pe) if pe else 50
        ce_pen = 6 if (len(ce) >= 5 and ce_wr < 40) else 0
        pe_pen = 6 if (len(pe) >= 5 and pe_wr < 40) else 0

        new_params = {"sample": n, "win_rate": wr, "threshold_adj": thr_adj,
                      "ce_penalty": ce_pen, "pe_penalty": pe_pen,
                      "reviewed_at": datetime.now().strftime("%H:%M")}
        if new_params != self.params:
            self.params = new_params
            self.db.save_learning(new_params)
            self.logger.info(f"🧬 SELF-LEARNING: WR {wr}% ({n} trades) | Threshold +{thr_adj} | CE-{ce_pen} PE-{pe_pen}")
        return self.params
