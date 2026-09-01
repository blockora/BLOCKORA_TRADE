"""AI Decision Validator - Master Decision se pehle final safety gate"""
from datetime import datetime


class DecisionValidator:
    VIX_MAX = 25

    def __init__(self, config=None, logger=None):
        self.config = config
        self.logger = logger
        # 🎯 FIX #3: RR config se aaye (single source of truth)
        rr = 2.0
        if config:
            for path in ("risk.min_risk_reward_ratio", "min_risk_reward_ratio"):
                v = config.get(path, None)
                if v is not None:
                    try:
                        rr = float(v)
                    except Exception:
                        pass
                    break
        self.min_rr = rr
        # 🔥 VolatilityManager: HIGH_VOLATILITY intraday rules ke liye
        try:
            from engines.risk.volatility_manager import VolatilityManager
            self.volatility_manager = VolatilityManager(config, logger)
        except Exception:
            self.volatility_manager = None

    def validate(self, ctx, skip_market_hours=False):
        """Sab checks chalao -> (valid: bool, reasons: list)

        Volatility policy (graduated):
          - EXTREME_VOLATILITY -> REJECT (market unstable)
          - HIGH_VOLATILITY    -> intraday_rules() check -> PASS with flags ya REJECT
          - NORMAL / baaki     -> normal validation
        """
        hard_fail = []
        caution = []

        # 1) Fresh Data
        if not ctx.get("fresh", False):
            hard_fail.append("stale_data")

        # 2) Liquidity OK (kam se kam 1 liquid strike)
        liq = ctx.get("liq_stats", {})
        if liq.get("kept", 0) <= 0:
            hard_fail.append("no_liquid_strike")

        # 3) Regime OK — GRADUATED VOLATILITY POLICY
        regime = (ctx.get("regime", {}) or {}).get("type", "UNKNOWN")
        if regime == "EXTREME_VOLATILITY":
            # 🔥 NEW: Extreme = NO_TRADE (RSI>90 OR ADX>85 OR ATR%>0.15)
            hard_fail.append("regime_EXTREME_VOLATILITY")
        elif regime == "HIGH_VOLATILITY":
            # 🔥 NEW: HIGH_VOLATILITY -> intraday rules (PASS with flags ya REJECT)
            self._vol_flags = []
            self._vol_rejects = []
            try:
                if self.volatility_manager is not None:
                    vctx = dict(ctx)
                    vctx["direction"] = ctx.get("direction", "") or ""
                    vres = self.volatility_manager.check_intraday_rules(vctx)
                    self._vol_flags = vres.get("flags", [])
                    self._vol_rejects = vres.get("reject", [])
                    if vres.get("reject"):
                        hard_fail.extend([f"highvol_{r}" for r in vres["reject"]])
                    else:
                        caution.append("high_volatility_intraday_rules_ok")
                else:
                    # VolatilityManager unavailable -> conservative block
                    hard_fail.append("highvol_manager_unavailable")
            except Exception as e:
                hard_fail.append(f"highvol_check_err_{e}")
        elif regime in ("LOW_VOLATILITY",):
            hard_fail.append(f"regime_{regime}")
        elif regime == "SIDEWAYS":
            caution.append("sideways_market")

        # 4) Session OK
        hm = datetime.now().hour * 60 + datetime.now().minute
        if not skip_market_hours and not (555 <= hm <= 930):
            hard_fail.append("outside_market_hours")
        if 720 <= hm <= 795:
            caution.append("lunch_chop")

        # 5) VIX OK
        vix = ctx.get("vix")
        if vix:
            if vix > self.VIX_MAX:
                hard_fail.append(f"vix_{vix}")
            elif vix > 18:
                caution.append(f"high_vix_{vix}")

        # 6) Reward:Risk OK (FIX #3: config-driven, T2 par measure)
        #    HIGH_VOLATILITY me tighter 1:1.5 (config high_volatility_rules.min_risk_reward)
        #    FIX B: HIGH_VOLATILITY me T3 use karo (3×ATR / 1.5×ATR = 2.0) instead of T2 (1.33)
        bs = ctx.get("best_strike", {}) or {}
        try:
            entry = float(bs.get("entry", 0) or 0)
            sl = float(bs.get("stop_loss", 0) or 0)
            # FIX B: HIGH_VOLATILITY me T3 use karo, warna T2
            if regime == "HIGH_VOLATILITY":
                t3 = float(bs.get("target_3", 0) or 0) or float(bs.get("target_2", 0) or 0) or float(bs.get("target_1", 0) or 0)
                reward = t3 - entry
            else:
                t2 = float(bs.get("target_2", 0) or 0) or float(bs.get("target_1", 0) or 0)
                reward = t2 - entry
            risk = entry - sl
            if risk > 0 and reward > 0:
                rr = reward / risk
                min_rr = self.min_rr
                if regime == "HIGH_VOLATILITY" and self.config is not None:
                    try:
                        min_rr = float(self.config.get(
                            "risk.high_volatility_rules.min_risk_reward", self.min_rr))
                    except Exception:
                        pass
                if round(rr, 2) < min_rr:
                    hard_fail.append(f"rr_{rr:.1f}<{min_rr}")
            else:
                hard_fail.append("bad_rr_levels")
        except Exception:
            hard_fail.append("rr_parse_fail")

        valid = len(hard_fail) == 0
        reasons = hard_fail + caution
        if self.logger and not valid:
            self.logger.warning(f"Validator REJECT: {hard_fail}")
        return {"valid": valid, "reasons": reasons, "hard_fail": hard_fail}
