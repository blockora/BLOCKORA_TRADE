"""Market Regime Engine - market type detect karta hai"""


class MarketRegimeEngine:
    # Thresholds
    ADX_TREND_THRESHOLD = 25
    ADX_LOW_THRESHOLD = 15
    RSI_EXTREME_HIGH = 75
    RSI_EXTREME_LOW = 25
    VOLATILITY_HIGH_ATR_PCT = 0.08    # 5-min ATR > ~20 pts = high vol
    VOLATILITY_LOW_ATR_PCT = 0.025    # 5-min ATR < ~6 pts = dead market

    # 🔥 EXTREME_VOLATILITY thresholds (config-driven, risk.json se override)
    # Defaults: RSI>90 OR ADX>85 OR ATR%>0.15 = market unstable -> NO_TRADE
    EXTREME_RSI_THRESHOLD = 90
    EXTREME_ADX_THRESHOLD = 85
    EXTREME_ATR_PCT_THRESHOLD = 0.15
    # HIGH_VOLATILITY intraday thresholds (config-driven)
    HIGH_RSI_THRESHOLD = 70
    HIGH_ADX_THRESHOLD = 50
    HIGH_ATR_PCT_THRESHOLD = 0.05

    def __init__(self, logger=None, config=None):
        self.logger = logger
        self.config = config
        self._load_thresholds()

    def _load_thresholds(self):
        """risk.json volatility_regimes se thresholds load karo (fallback = class defaults)"""
        if self.config is None:
            return
        try:
            self.EXTREME_RSI_THRESHOLD = self.config.get_float(
                "risk.volatility_regimes.extreme.rsi_threshold", self.EXTREME_RSI_THRESHOLD)
            self.EXTREME_ADX_THRESHOLD = self.config.get_float(
                "risk.volatility_regimes.extreme.adx_threshold", self.EXTREME_ADX_THRESHOLD)
            self.EXTREME_ATR_PCT_THRESHOLD = self.config.get_float(
                "risk.volatility_regimes.extreme.atr_pct_threshold", self.EXTREME_ATR_PCT_THRESHOLD)
            self.HIGH_RSI_THRESHOLD = self.config.get_float(
                "risk.volatility_regimes.high.rsi_threshold", self.HIGH_RSI_THRESHOLD)
            self.HIGH_ADX_THRESHOLD = self.config.get_float(
                "risk.volatility_regimes.high.adx_threshold", self.HIGH_ADX_THRESHOLD)
            self.HIGH_ATR_PCT_THRESHOLD = self.config.get_float(
                "risk.volatility_regimes.high.atr_pct_threshold", self.HIGH_ATR_PCT_THRESHOLD)
        except Exception:
            pass

    def detect(self, market_data, analysis_results):
        """Market regime detect karo based on existing analysis"""
        try:
            candles = market_data.get("candles", [])
            if len(candles) < 20:
                return self._default_regime("insufficient_data")

            # Existing analysis se metrics nikalo
            indicators = analysis_results.get("indicators", {})
            adx = float(indicators.get("adx", 0) or 0)
            rsi = float(indicators.get("rsi", 50) or 50)

            # ATR calculate (volatility measure)
            atr = self._calculate_atr(candles[-20:])
            spot = market_data.get("ltp", 0)
            atr_pct = (atr / spot * 100) if spot > 0 else 0

            # Regime detection logic
            regime = self._classify_regime(adx, rsi, atr_pct)

            if self.logger:
                self.logger.info(f"Market Regime: {regime['type']} | ADX:{adx:.1f} RSI:{rsi:.1f} ATR%:{atr_pct:.2f}")

            return regime

        except Exception as e:
            if self.logger:
                self.logger.warning(f"Regime detection failed: {e}")
            return self._default_regime("error")

    def _classify_regime(self, adx, rsi, atr_pct):
        """ADX + RSI + ATR se regime classify karo

        3 volatility states:
          - EXTREME_VOLATILITY: RSI>90 OR ADX>85 OR ATR%>0.15  -> NO_TRADE
          - HIGH_VOLATILITY:     RSI>70 OR ADX>50 OR ATR%>0.05  -> intraday rules
          - NORMAL:              baaki sab
        Existing states (TRENDING/SIDEWAYS/LOW_VOLATILITY) preserved for back-compat.
        """

        # 0) EXTREME_VOLATILITY: market unstable — highest priority (config-driven)
        if (rsi > self.EXTREME_RSI_THRESHOLD or adx > self.EXTREME_ADX_THRESHOLD
                or atr_pct > self.EXTREME_ATR_PCT_THRESHOLD):
            return {"type": "EXTREME_VOLATILITY", "adx": adx, "rsi": rsi, "atr_pct": atr_pct}

        # 1) HIGH_VOLATILITY: ATR bahut high (config-driven intraday thresholds)
        if (rsi > self.HIGH_RSI_THRESHOLD or adx > self.HIGH_ADX_THRESHOLD
                or atr_pct > self.HIGH_ATR_PCT_THRESHOLD):
            return {"type": "HIGH_VOLATILITY", "adx": adx, "rsi": rsi, "atr_pct": atr_pct}

        # 1b) NORMAL: pure volatility view ke liye — ATR/momentum balanaced
        if atr_pct <= self.VOLATILITY_LOW_ATR_PCT and adx < self.ADX_LOW_THRESHOLD:
            return {"type": "NORMAL", "adx": adx, "rsi": rsi, "atr_pct": atr_pct}

        # 2) LOW_VOLATILITY: ADX bahut low + ATR low
        if adx < self.ADX_LOW_THRESHOLD and atr_pct < self.VOLATILITY_LOW_ATR_PCT:
            return {"type": "LOW_VOLATILITY", "adx": adx, "rsi": rsi, "atr_pct": atr_pct}

        # 3) TRENDING: ADX strong + RSI extreme (confirmation)
        if adx >= self.ADX_TREND_THRESHOLD:
            if rsi > self.RSI_EXTREME_HIGH or rsi < self.RSI_EXTREME_LOW:
                return {"type": "TRENDING_STRONG", "adx": adx, "rsi": rsi, "atr_pct": atr_pct}
            else:
                return {"type": "TRENDING", "adx": adx, "rsi": rsi, "atr_pct": atr_pct}

        # 4) SIDEWAYS: ADX weak + RSI neutral
        return {"type": "SIDEWAYS", "adx": adx, "rsi": rsi, "atr_pct": atr_pct}

    def _calculate_atr(self, candles):
        """Average True Range calculate karo (last 20 candles)"""
        try:
            atr_sum = 0
            for i in range(len(candles)):
                high = float(candles[i][2])
                low = float(candles[i][3])
                close = float(candles[i][4])
                prev_close = float(candles[i-1][4]) if i > 0 else close
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                atr_sum += tr
            return atr_sum / len(candles)
        except Exception:
            return 0

    def _default_regime(self, reason):
        """Fallback regime"""
        return {"type": "UNKNOWN", "reason": reason, "adx": 0, "rsi": 50, "atr_pct": 0}
