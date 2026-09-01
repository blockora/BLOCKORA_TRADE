"""Risk Engine - Risk assessment and management"""


class RiskEngine:
    """Evaluates risk for each recommendation"""

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def evaluate(self, analysis_results, confidence):
        """Evaluate risk level"""
        risk_score = 0
        factors = []

        volume_score = analysis_results.get("volume", {}).get("score", 50)
        if volume_score < 40:
            risk_score += 20
            factors.append("LOW_VOLUME")

        trend_score = analysis_results.get("trend", {}).get("score", 50)
        if trend_score < 50:
            risk_score += 15
            factors.append("WEAK_TREND")

        if confidence["score"] < 80:
            risk_score += 25
            factors.append("LOW_CONFIDENCE")

        if risk_score <= 10:
            level = "LOW"
        elif risk_score <= 25:
            level = "MEDIUM"
        elif risk_score <= 40:
            level = "HIGH"
        else:
            level = "CRITICAL"

        return {
            "level": level,
            "score": risk_score,
            "factors": factors,
            "approved": risk_score <= 40
        }

    # 🛑 TRADING LIMITS (per day)
    MAX_DAILY_LOSS = -20.0
    MAX_CONSEC_LOSS = 3
    MAX_TRADES_PER_DAY = 6

    def check_limits(self, stats):
        """Daily limits check -> (allowed: bool, reasons: list)"""
        reasons = []
        if stats.get("daily_pnl", 0) <= self.MAX_DAILY_LOSS:
            reasons.append(f"daily_loss_{stats['daily_pnl']}")
        if stats.get("consec_losses", 0) >= self.MAX_CONSEC_LOSS:
            reasons.append(f"consec_loss_{stats['consec_losses']}")
        if stats.get("trades_today", 0) >= self.MAX_TRADES_PER_DAY:
            reasons.append(f"max_trades_{stats['trades_today']}")
        return (len(reasons) == 0), reasons

    # ══════════ VOLATILITY-ADJUSTED POSITION SIZING ══════════
    def calculate_volatility_adjusted_position(self, signal, regime):
        """Volatility regime ke hisaab se position size calculate karo.

        Returns: {
            "regime": str,
            "position_pct": float,   # 1.0 normal, 0.5 high, 0.0 extreme
            "base_lot_size": int,    # signal/contract base lot
            "adjusted_lot_size": float,
            "blocked": bool
        }
        """
        try:
            regime_type = str((regime or {}).get("type", "NORMAL")).upper()
            from engines.risk.volatility_manager import VolatilityManager
            vm = VolatilityManager(self.config, self.logger)
            pct = vm.position_size_pct(regime_type)

            base_lot = 1
            try:
                base_lot = int(signal.get("lot_size") or self.config.get_int(
                    "application.lot_size", 1) or 1)
            except Exception:
                base_lot = 1

            return {
                "regime": regime_type,
                "position_pct": float(pct),
                "base_lot_size": base_lot,
                "adjusted_lot_size": round(float(base_lot * pct), 2),
                "blocked": pct <= 0,
            }
        except Exception as e:
            return {"regime": "NORMAL", "position_pct": 1.0, "base_lot_size": 1,
                    "adjusted_lot_size": 1, "blocked": False, "error": str(e)}
