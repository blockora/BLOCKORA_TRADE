"""Confidence Engine v4 - Adaptive + Momentum Trigger"""


class ConfidenceEngine:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def calculate(self, analysis_results):
        oi_real = bool(analysis_results.get("option_chain", {}).get("ce_data"))
        mtf_data = analysis_results.get("market_data", {}).get("candles_15m", [])
        mtf_align = analysis_results.get("multi_timeframe", {}).get("alignment", "NONE")

        # Base engines (Angel One candles = hamesha real)
        weights = {
            "market_structure": 35,
            "indicators": 35,
            "candlestick": 30,
        }
        if oi_real:
            weights["oi_analysis"] = 25
        if mtf_data and mtf_align != "NONE":
            weights["multi_timeframe"] = 25

        total_w = sum(weights.values())
        final = sum(
            analysis_results.get(k, {}).get("score", 0) * (w / total_w)
            for k, w in weights.items()
        )

        # 🔥 MOMENTUM TRIGGER: Real move + confirmation = +8 bonus
        bonus, reason = self._momentum_bonus(analysis_results)
        final += bonus

        # Safety caps (Institutional grade = full data chahiye)
        final = min(final, 92 if oi_real else 88)

        return {
            "score": round(final, 1),
            "grade": self._get_grade(final),
            "components": {k: analysis_results.get(k, {}).get("score", 0) for k in weights},
            "momentum_bonus": bonus,
            "momentum_reason": reason,
        }

    def _momentum_bonus(self, analysis_results):
        """15+ point move (3 candles) + RSI + MACD + ADX confirm = +8"""
        candles = analysis_results.get("market_data", {}).get("candles", [])
        ind = analysis_results.get("indicators", {})
        if len(candles) < 4:
            return 0, ""
        move = candles[-1][4] - candles[-4][4]
        rsi = ind.get("rsi", 50)
        adx = ind.get("adx", 0)
        macd_h = ind.get("macd_hist", 0)

        if abs(move) >= 15 and adx > 20:
            if move < 0 and rsi < 45 and macd_h < 0:
                return 8, "Momentum: Strong Bearish Move (15+ pts)"
            if move > 0 and rsi > 55 and macd_h > 0:
                return 8, "Momentum: Strong Bullish Move (15+ pts)"
        return 0, ""

    def _get_grade(self, s):
        if s >= 95: return "INSTITUTIONAL"
        if s >= 90: return "EXCELLENT"
        if s >= 80: return "GOOD"
        if s >= 70: return "WEAK"
        return "REJECT"
