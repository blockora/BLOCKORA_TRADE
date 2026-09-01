"""Volatility Manager - HIGH_VOLATILITY intraday rule checker.

Har rule ek function: (ctx) -> (ok: bool, msg: str)
Sab rules try/except me wrapped (kabhi crash nahi hoga).

Data available in ctx (main.py se aata hai):
  regime       : {"type", "adx", "rsi", "atr_pct"}
  spot         : current underlying price
  chain        : {"spot_price", "strikes", "ce_data", "pe_data", "pcr", ...}
  best_strike  : {"strike", "option_type", "entry", "stop_loss", "target_2",
                  "oi", "change_oi", "volume", "iv"}
  risk_stats   : {"trades_today", "daily_pnl", ...} (optional)
  vix          : optional
"""
import time
from datetime import datetime


class VolatilityManager:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self._trade_times = []  # (timestamp) — max trades per hour ke liye

    def _log(self, msg):
        if self.logger is not None:
            self.logger.info(msg)

    def _cfg_float(self, path, default):
        try:
            return self.config.get_float(path, default)
        except Exception:
            return default

    def _cfg_int(self, path, default):
        try:
            return self.config.get_int(path, default)
        except Exception:
            return default

    # ══════════════ INDIVIDUAL RULES ══════════════

    def rule_atm_range(self, ctx):
        """Strike selection: ATM ± 2 strikes ONLY (no far OTM)"""
        try:
            spot = float(ctx.get("spot") or 0)
            strike = float(ctx.get("best_strike", {}).get("strike", 0) or 0)
            if spot <= 0 or strike <= 0:
                return False, "no_spot_or_strike"
            atm = round(spot / 50) * 50
            atm_range = self._cfg_int("risk.high_volatility_rules.atm_range", 2)
            dist = int(round(abs(strike - atm) / 50))
            if dist > atm_range:
                return False, f"strike_{int(strike)}_outside_atm_{atm_range}_range"
            return True, f"ATM±{dist} (ok)"
        except Exception as e:
            return False, f"atm_range_err_{e}"

    def rule_min_rr(self, ctx):
        """Min Risk-Reward: 1:1.3 (scalp mode, tighter than normal 1:2)"""
        try:
            bs = ctx.get("best_strike", {}) or {}
            entry = float(bs.get("entry", 0) or 0)
            sl = float(bs.get("stop_loss", 0) or 0)
            t2 = float(bs.get("target_2", 0) or 0) or float(bs.get("target_1", 0) or 0)
            risk = entry - sl
            reward = t2 - entry
            if risk <= 0 or reward <= 0:
                return False, "bad_rr_levels"
            rr = reward / risk
            min_rr = self._cfg_float("risk.high_volatility_rules.min_risk_reward", 1.3)
            if round(rr, 2) < min_rr:
                return False, f"rr_{rr:.1f}<{min_rr}"
            return True, f"RR {rr:.1f}"
        except Exception as e:
            return False, f"rr_err_{e}"

    def rule_oi_confirmation(self, ctx):
        """OI Confirmation Required: OI change > 5% on signal strike (scalp mode)"""
        try:
            bs = ctx.get("best_strike", {}) or {}
            oi = float(bs.get("oi", 0) or 0)
            chg = float(bs.get("change_oi", 0) or 0)
            if oi <= 0:
                return False, "oi_unavailable"
            pct = (abs(chg) / oi) * 100.0
            min_pct = self._cfg_float("risk.high_volatility_rules.min_oi_change_pct", 5)
            if pct <= min_pct:
                return False, f"oi_change_{pct:.0f}%<{min_pct}%"
            return True, f"OI +{pct:.0f}%"
        except Exception as e:
            return False, f"oi_err_{e}"

    def rule_volume_filter(self, ctx):
        """Volume > 1.2x average of last 5 cycles (scalp mode)"""
        try:
            bs = ctx.get("best_strike", {}) or {}
            vol = float(bs.get("volume", 0) or 0)
            if vol <= 0:
                return False, "volume_unavailable"
            mult = self._cfg_float("risk.high_volatility_rules.volume_multiplier", 1.2)
            hist = getattr(self, "_vol_history", [])
            if not hist:
                # Warm-up: history nahi hai -> block nahi, sirf flag (informational)
                self._vol_history = [vol]
                return True, "volume_history_warming"
            avg = sum(hist) / len(hist)
            self._vol_history.append(vol)
            self._vol_history = self._vol_history[-5:]
            if vol <= avg * mult:
                return False, f"vol_{vol:.0f}<=avg{avg:.0f}x{mult}"
            return True, f"Vol {vol:.0f} > {avg:.0f}x{mult}"
        except Exception as e:
            return False, f"vol_err_{e}"

    def rule_max_trades_per_hour(self, ctx):
        """Max Trades Per Hour: 1 (no overtrading)"""
        try:
            now = time.time()
            cutoff = now - 3600
            self._trade_times = [t for t in self._trade_times if t > cutoff]
            max_trades = self._cfg_int("risk.high_volatility_rules.max_trades_per_hour", 1)
            if len(self._trade_times) >= max_trades:
                return False, f"trades_this_hour_{len(self._trade_times)}"
            return True, f"{len(self._trade_times)}/{max_trades} this hour"
        except Exception as e:
            return False, f"max_trades_err_{e}"

    def rule_direction_with_trend(self, ctx):
        """Direction: ONLY with trend (ADX > 50 -> follow ADX direction)"""
        try:
            regime = ctx.get("regime", {}) or {}
            adx = float(regime.get("adx", 0) or 0)
            if adx <= 50:
                return True, "adx_le_50_no_trend_req"
            # ADX strong: signal direction = best_strike option_type + bias
            bs = ctx.get("best_strike", {}) or {}
            opt = str(bs.get("option_type", "")).upper()
            direction = str(ctx.get("direction", "") or "").upper()
            if direction == "BULLISH" and opt == "CE":
                return True, "with_trend_ce"
            if direction == "BEARISH" and opt == "PE":
                return True, "with_trend_pe"
            return False, "counter_trend_signal"
        except Exception as e:
            return False, f"direction_err_{e}"

    def rule_option_type_zone(self, ctx):
        """Option Type: CE if RSI 40-80, PE allowed RSI 30-60 (scalp mode relaxed)"""
        try:
            regime = ctx.get("regime", {}) or {}
            rsi = float(regime.get("rsi", 50) or 50)
            bs = ctx.get("best_strike", {}) or {}
            opt = str(bs.get("option_type", "")).upper()
            if opt == "CE" and 40 <= rsi <= 80:
                return True, "CE_relaxed_zone"
            if opt == "PE" and 30 <= rsi <= 60:
                return True, "PE_relaxed_zone"
            return False, f"option_type_{opt}_rsi_{rsi:.0f}_out_of_zone"
        except Exception as e:
            return False, f"opt_type_err_{e}"

    def rule_hard_stop(self, ctx):
        """Hard Stop: -20% in first 10 minutes -> auto exit signal (flag only)"""
        try:
            bs = ctx.get("best_strike", {}) or {}
            hard_stop_pct = self._cfg_float("risk.high_volatility_rules.hard_stop_pct", 20)
            early_min = self._cfg_int("risk.high_volatility_rules.early_exit_minutes", 10)
            entry = float(bs.get("entry", 0) or 0)
            if entry <= 0:
                return True, "no_entry_no_stop_check"
            stop = entry * (1 - hard_stop_pct / 100.0)
            return True, f"hard_stop_{stop:.1f}_within_{early_min}min"
        except Exception as e:
            return False, f"hard_stop_err_{e}"

    def rule_max_holding(self, ctx):
        """Max Holding Time: 30 minutes only (scalp mode)"""
        try:
            max_min = self._cfg_int("risk.high_volatility_rules.max_holding_minutes", 30)
            bs = ctx.get("best_strike", {}) or {}
            hold = float(bs.get("holding_time", 0) or 0)
            if hold <= 0:
                return True, "no_holding_time"
            if hold > max_min:
                return False, f"holding_{int(hold)}min>{max_min}min"
            return True, f"hold_{int(hold)}min"
        except Exception as e:
            return False, f"holding_err_{e}"

    def rule_position_size(self, ctx):
        """Position Size: 50% of normal (risk.json high_vol_position_pct)"""
        try:
            pct = self._cfg_float("risk.high_volatility_rules.position_size_pct", 0.5)
            return True, f"position_size_{int(pct*100)}%"
        except Exception as e:
            return False, f"pos_size_err_{e}"

    # ══════════════ MAIN ENTRY ══════════════

    def check_intraday_rules(self, ctx):
        """HIGH_VOLATILITY candidate ke liye saare intraday rules chalao.

        Returns: {"valid": bool, "flags": [str], "reject": [str], "position_pct": float}
          - reject  = hard fail (trade block)
          - flags   = passed rules / informational
        """
        try:
            reject = []
            flags = []
            position_pct = self._cfg_float(
                "risk.high_volatility_rules.position_size_pct", 0.5)

            rules = [
                ("atm_range", self.rule_atm_range),
                ("min_rr", self.rule_min_rr),
                ("oi_confirmation", self.rule_oi_confirmation),
                ("volume_filter", self.rule_volume_filter),
                ("max_trades_per_hour", self.rule_max_trades_per_hour),
                ("direction_with_trend", self.rule_direction_with_trend),
                ("option_type_zone", self.rule_option_type_zone),
                ("hard_stop", self.rule_hard_stop),
                ("max_holding", self.rule_max_holding),
                ("position_size", self.rule_position_size),
            ]

            for name, rule in rules:
                try:
                    ok, msg = rule(ctx)
                    if ok:
                        flags.append(f"{name}:{msg}")
                    else:
                        reject.append(f"{name}:{msg}")
                except Exception as e:
                    reject.append(f"{name}:err_{e}")

            return {
                "valid": len(reject) == 0,
                "flags": flags,
                "reject": reject,
                "position_pct": position_pct,
            }
        except Exception as e:
            return {"valid": False, "flags": [], "reject": [f"manager_err_{e}"],
                    "position_pct": 0.5}

    def register_trade(self):
        """Trade execute hui — max-trades-per-hour window update karo"""
        try:
            self._trade_times.append(time.time())
        except Exception:
            pass

    def position_size_pct(self, regime_type="NORMAL"):
        """Volatility-adjusted position size (0 = block, 0.5 = half, 1.0 = normal)"""
        try:
            if regime_type == "EXTREME_VOLATILITY":
                return 0.0
            if regime_type == "HIGH_VOLATILITY":
                return self._cfg_float("risk.high_volatility_rules.position_size_pct", 0.5)
            return 1.0
        except Exception:
            return 1.0