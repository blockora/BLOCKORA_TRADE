"""Master Decision Engine v2 - MTF + MACD + ADX + Supertrend + Engulfing + Real OI"""
from datetime import datetime


class MasterDecisionEngine:

    def __init__(self, config, logger, confidence_engine, risk_engine, ranking_engine):
        self.config = config
        self.logger = logger
        self.confidence_engine = confidence_engine
        self.risk_engine = risk_engine
        self.ranking_engine = ranking_engine

    def run_analysis(self, market_data, option_chain):
        structure = self._analyze_market_structure(market_data)
        indicators = self._analyze_indicators(market_data)
        mtf = self._analyze_multi_timeframe(market_data)
        sr = self._analyze_support_resistance(market_data)
        return {
            "market_data": market_data,
            "option_chain": option_chain,
            "market_structure": structure,
            "trend": {"score": structure["score"], "direction": structure["trend"]},
            "candlestick": self._analyze_candlestick(market_data),
            "indicators": indicators,
            "volume": self._analyze_volume(market_data),
            "oi_analysis": self._analyze_oi(option_chain, market_data),
            "multi_timeframe": mtf,
            "support_resistance": sr,
            "trade_context": self._analyze_trade_context(market_data, indicators, mtf, sr),
        }

    # ══════════ MARKET STRUCTURE ══════════
    def _analyze_market_structure(self, market_data):
        candles = market_data.get("candles", [])
        if len(candles) < 5:
            return {"score": 50, "trend": "NEUTRAL", "structure": "UNDEFINED"}
            
        highs = [c[2] for c in candles[-10:]]
        lows = [c[3] for c in candles[-10:]]
        
        total = len(highs) - 1
        hh = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i-1])
        hl = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i-1])
        bull = (hh + hl) / (2 * total) if total else 0
        bear = ((total - hh) + (total - hl)) / (2 * total) if total else 0

        if bull >= 0.6:
            return {"score": min(95, 60 + int(bull * 35)), "trend": "BULLISH", "structure": "UPTREND"}
        if bear >= 0.6:
            return {"score": min(95, 60 + int(bear * 35)), "trend": "BEARISH", "structure": "DOWNTREND"}
        return {"score": 40 + int(max(bull, bear) * 20), "trend": "NEUTRAL", "structure": "RANGE"}

    # ══════════ CANDLESTICK (Single + Double) ══════════
    def _analyze_candlestick(self, market_data):
        candles = market_data.get("candles", [])
        if len(candles) < 3:
            return {"score": 50, "pattern": "NONE", "bias": "NEUTRAL"}
        c1, c2 = candles[-2], candles[-1]
        o1, h1, l1, cl1 = c1[1], c1[2], c1[3], c1[4]
        o2, h2, l2, cl2 = c2[1], c2[2], c2[3], c2[4]
        b1, b2 = abs(cl1 - o1), abs(cl2 - o2)

        # 🔥 Double patterns (high reliability)
        if cl1 < o1 and cl2 > o2 and o2 <= cl1 and cl2 >= o1 and b2 > b1:
            return {"score": 92, "pattern": "BULLISH_ENGULFING", "bias": "BULLISH"}
        if cl1 > o1 and cl2 < o2 and o2 >= cl1 and cl2 <= o1 and b2 > b1:
            return {"score": 92, "pattern": "BEARISH_ENGULFING", "bias": "BEARISH"}
        if b1 > 0 and b2 < b1 * 0.5 and max(o2, cl2) <= max(o1, cl1) and min(o2, cl2) >= min(o1, cl1):
            bias = "BULLISH" if cl1 < o1 else "BEARISH"
            return {"score": 74, "pattern": "HARAMI", "bias": bias}

        # Single patterns
        body = b2
        uw = h2 - max(o2, cl2)
        lw = min(o2, cl2) - l2
        rng = h2 - l2
        if rng == 0:
            return {"score": 50, "pattern": "NONE", "bias": "NEUTRAL"}
        if body / rng < 0.1:
            return {"score": 40, "pattern": "DOJI", "bias": "NEUTRAL"}
        if lw > 2 * body and uw < body * 0.5:
            return {"score": 88, "pattern": "HAMMER", "bias": "BULLISH"}
        if uw > 2 * body and lw < body * 0.5:
            return {"score": 90, "pattern": "SHOOTING_STAR", "bias": "BEARISH"}
        if body / rng > 0.9:
            return {"score": 92, "pattern": "MARUBOZU", "bias": "BULLISH" if cl2 > o2 else "BEARISH"}
        return {"score": 50, "pattern": "NORMAL", "bias": "NEUTRAL"}

    # ══════════ INDICATORS (EMA+RSI+MACD+ADX+Supertrend) ══════════
    def _analyze_indicators(self, market_data):
        candles = market_data.get("candles", [])
        if len(candles) < 50:
            return {"score": 50, "bias": "NEUTRAL", "adx": 0}
        closes = [c[4] for c in candles]
        price = closes[-1]
        ema9 = self._calc_ema(closes, 9)
        ema20 = self._calc_ema(closes, 20)
        ema50 = self._calc_ema(closes, 50)
        rsi = self._calc_rsi(closes, 14)
        macd = self._calc_macd(closes)
        adx = self._calc_adx(candles)
        st = self._calc_supertrend(candles)
        atr = self._calc_atr(candles)

        bull = bear = 0
        if price > ema9 > ema20 > ema50: bull += 2
        elif price < ema9 < ema20 < ema50: bear += 2
        if rsi > 55: bull += 1
        elif rsi < 45: bear += 1
        if macd["bullish"] and macd["rising"]: bull += 2
        elif not macd["bullish"] and not macd["rising"]: bear += 2
        if st == "BULLISH": bull += 1
        elif st == "BEARISH": bear += 1

        # 🔥 ADX = trend strength filter (sideways killer)
        if bull > bear and adx >= 18:
            score = min(95, 60 + bull * 6 + (5 if adx > 25 else 0))
            bias = "BULLISH"
        elif bear > bull and adx >= 18:
            score = min(95, 60 + bear * 6 + (5 if adx > 25 else 0))
            bias = "BEARISH"
        else:
            score = 45 + min(bull, bear) * 3
            bias = "NEUTRAL"

        return {"score": score, "bias": bias, "adx": round(adx, 1),
                "rsi": round(rsi, 1), "macd_hist": round(macd["hist"], 2),
                "ema_gap": round(price - ema20, 1),
                "atr": atr}

    # ══════════ VOLUME ══════════
    def _analyze_volume(self, market_data):
        candles = market_data.get("candles", [])
        if len(candles) < 10:
            return {"score": 50}
        vols = [c[5] for c in candles[-10:]]
        avg = sum(vols[:-1]) / max(len(vols[:-1]), 1)
        if avg == 0:
            return {"score": 50}
        ratio = vols[-1] / avg
        if ratio > 1.5: return {"score": 90}
        if ratio > 1.0: return {"score": 70}
        if ratio > 0.5: return {"score": 50}
        return {"score": 30}

    def _oi_data_quality(self, option_chain):
        """BUG #7: Explicit OI/change-OI data quality (COMPLETE/PARTIAL/UNKNOWN)"""
        if not option_chain:
            return "UNKNOWN", 0, 0
        ce = option_chain.get("ce_data", {}) or {}
        pe = option_chain.get("pe_data", {}) or {}
        total = len(ce) + len(pe)
        if total == 0:
            return "UNKNOWN", 0, 0
        oi_ok = 0
        ch_ok = 0
        for rec in list(ce.values()) + list(pe.values()):
            if float(rec.get("oi", 0) or 0) > 0:
                oi_ok += 1
            if rec.get("change_oi_source", "UNKNOWN") in ("REAL", "ZERO", "CALCULATED"):
                ch_ok += 1
        if oi_ok / total >= 0.8 and ch_ok / total >= 0.6:
            return "COMPLETE", oi_ok, ch_ok
        if oi_ok > 0 or ch_ok > 0:
            return "PARTIAL", oi_ok, ch_ok
        return "UNKNOWN", oi_ok, ch_ok

    # ══════════ REAL OI (Put/Call Writing) ══════════
    def _analyze_oi(self, option_chain, market_data):
        if not option_chain:
            return {"score": 50, "bias": "NEUTRAL", "signal": "NO DATA"}

        # 🔥 DERIVED OI: Jab NSE block (404) ho, toh Price Action se OI estimate karo
        if option_chain.get("source") == "FALLBACK":
            candles = market_data.get("candles", [])
            if len(candles) < 5:
                return {"score": 50, "bias": "NEUTRAL", "signal": "Insufficient Data"}

            last_3 = candles[-3:]
            price_drop = last_3[0][4] - last_3[-1][4]
            price_rise = last_3[-1][4] - last_3[0][4]
            avg_range = sum(c[2] - c[3] for c in last_3) / 3

            score, bias, signals = 60, "NEUTRAL", []

            if price_drop > avg_range * 1.5:
                score += 20; bias = "BEARISH"; signals.append("Derived: Call Writing")
            elif price_rise > avg_range * 1.5:
                score += 20; bias = "BULLISH"; signals.append("Derived: Put Writing")

            last_c = candles[-1]
            lower_wick = min(last_c[1], last_c[4]) - last_c[3]
            upper_wick = last_c[2] - max(last_c[1], last_c[4])
            body = abs(last_c[4] - last_c[1])

            if lower_wick > body * 2:
                score += 15; bias = "BULLISH"; signals.append("Derived: Put Support")
            elif upper_wick > body * 2:
                score += 15; bias = "BEARISH"; signals.append("Derived: Call Resistance")

            quality, oi_n, ch_n = self._oi_data_quality(option_chain)
            return {"score": min(90, score), "bias": bias, "pcr": 1.0,
                    "signal": " | ".join(signals) if signals else "Derived: N/A",
                    "oi_data_quality": quality,
                    "oi_available_count": oi_n,
                    "change_oi_available_count": ch_n}

        # Real NSE OI Logic (Jo pehle se hai)
        pcr = option_chain.get("pcr", 1.0)
        ce = option_chain.get("ce_data", {})
        pe = option_chain.get("pe_data", {})
        ce_chg = sum(d.get("change_oi", 0) for d in ce.values())
        pe_chg = sum(d.get("change_oi", 0) for d in pe.values())

        score, bias, signals = 50, "NEUTRAL", []
        if pcr > 1.2: score += 10; bias = "BULLISH"; signals.append("PCR High")
        elif pcr < 0.8: score += 10; bias = "BEARISH"; signals.append("PCR Low")

        if pe_chg > 0 and pe_chg > abs(ce_chg):
            score += 25; bias = "BULLISH"; signals.append("Put Writing")
        elif ce_chg > 0 and ce_chg > abs(pe_chg):
            score += 25; bias = "BEARISH"; signals.append("Call Writing")
        if ce_chg < 0: score += 10; signals.append("Call Unwinding")
        if pe_chg < 0: score += 10; signals.append("Put Unwinding")

        quality, oi_n, ch_n = self._oi_data_quality(option_chain)
        return {"score": min(95, score), "bias": bias, "pcr": pcr,
                "signal": " | ".join(signals) if signals else "BALANCED",
                "oi_data_quality": quality,
                "oi_available_count": oi_n,
                "change_oi_available_count": ch_n}

    # ══════════ REAL MULTI-TIMEFRAME (5m vs 15m vs 1h) ══════════
    def _analyze_multi_timeframe(self, market_data):
        t5 = self._tf_trend(market_data.get("candles", []))
        t15 = self._tf_trend(market_data.get("candles_15m", []))
        t1h = self._tf_trend(market_data.get("candles_1h", []))

        trends = [t for t in (t5, t15, t1h) if t != "NEUTRAL"]
        base = {"t5": t5, "t15": t15, "t1h": t1h}

        if not trends:
            return {"score": 50, "alignment": "NONE", "conflict": False,
                    "direction": "NEUTRAL", **base}
        bull = sum(1 for t in trends if t == "BULLISH")
        bear = sum(1 for t in trends if t == "BEARISH")

        if bull > 0 and bear > 0:
            return {"score": 45, "alignment": "CONFLICT", "conflict": True,
                    "direction": "NEUTRAL", **base}

        direction = "BULLISH" if bull else "BEARISH"
        return {"score": min(96, 60 + len(trends) * 12), "alignment": "ALIGNED",
                "conflict": False, "direction": direction, **base}

    def _analyze_support_resistance(self, market_data):
        candles = market_data.get("candles", [])
        if len(candles) < 10:
            return {"score": 50, "support": 0, "resistance": 0}
        return {"score": 70, "support": min(c[3] for c in candles[-20:]),
                "resistance": max(c[2] for c in candles[-20:])}

    def _is_monthly_expiry(self):
        """Expiry day + agla week next month me = MONTHLY expiry"""
        from datetime import timedelta
        today = datetime.now()
        if self.config.get_int("analysis.expiry_weekday", 1) != today.weekday():
            return False
        return (today + timedelta(days=7)).month != today.month

    def _analyze_trade_context(self, market_data, indicators, mtf, sr):
        """VWAP + 30-min Move + Direction Score (Move Gate ka dimaag)"""
        candles = market_data.get("candles", [])
        spot = market_data.get("ltp", 0)
        if len(candles) < 10 or spot == 0:
            return {"vwap": spot, "move30": 0, "direction": "NEUTRAL", "direction_score": 50,
                    "expected_move": 20, "invalidation_ce": spot - 20, "invalidation_pe": spot + 20}

        today = datetime.now().strftime("%Y-%m-%d")
        sess = [c for c in candles if str(c[0]).startswith(today)] or candles[-40:]

        # VWAP (range-weighted - index candles me volume=0 hota hai)
        num = den = 0.0
        for c in sess:
            t = (c[2] + c[3] + c[4]) / 3
            w = (c[2] - c[3]) or 0.1
            num += t * w
            den += w
        vwap = num / den if den else spot

        move30 = spot - candles[-7][4]
        direction = "NEUTRAL"
        if move30 >= 20: direction = "BULLISH"
        elif move30 <= -20: direction = "BEARISH"

        ds = 50
        if abs(move30) >= 40: ds += 20
        elif abs(move30) >= 20: ds += 10
        if direction == "BULLISH":
            if spot > vwap: ds += 15
            if mtf.get("direction") == "BULLISH": ds += 10
            if indicators.get("bias") == "BULLISH": ds += 10
            if indicators.get("macd_hist", 0) > 0: ds += 5
        elif direction == "BEARISH":
            if spot < vwap: ds += 15
            if mtf.get("direction") == "BEARISH": ds += 10
            if indicators.get("bias") == "BEARISH": ds += 10
            if indicators.get("macd_hist", 0) < 0: ds += 5
        ds = min(100, ds)

        # FIX 1: Expected-move ATR-based — true volatility, move30 overlap safety
        _atr = float(indicators.get("atr", 0) or 0)
        exp_from_atr = int(_atr * 1.5) if _atr > 0 else int(abs(move30))
        exp_from_move = int(abs(move30))
        expected_move = max(20, min(120, max(exp_from_atr, exp_from_move)))

        return {
            "vwap": round(vwap, 1), "move30": round(move30, 1),
            "direction": direction, "direction_score": ds,
            "expected_move": expected_move,
            "invalidation_ce": round(sr.get("support", spot) - 5, 1),
            "invalidation_pe": round(sr.get("resistance", spot) + 5, 1),
            "is_expiry": self.config.get_int("analysis.expiry_weekday", 1) == datetime.now().weekday(),
            "is_monthly_expiry": self._is_monthly_expiry(),
        }

    # ══════════ MATH HELPERS ══════════
    def _ema_series(self, data, period):
        if not data:
            return []
        mult = 2 / (period + 1)
        out = []
        ema = data[0]
        for i, p in enumerate(data):
            ema = p if i == 0 else (p - ema) * mult + ema
            out.append(ema)
        return out

    def _calc_ema(self, data, period):
        s = self._ema_series(data, period)
        return s[-1] if s else 0

    def _calc_rsi(self, data, period=14):
        if len(data) < period + 1:
            return 50
        gains, losses = [], []
        for i in range(1, len(data)):
            ch = data[i] - data[i-1]
            gains.append(max(0, ch)); losses.append(max(0, -ch))
        ag = sum(gains[-period:]) / period
        al = sum(losses[-period:]) / period
        if al == 0:
            return 100
        return 100 - (100 / (1 + ag / al))

    def _calc_macd(self, closes):
        if len(closes) < 35:
            return {"bullish": False, "rising": False, "hist": 0}
        e12 = self._ema_series(closes, 12)
        e26 = self._ema_series(closes, 26)
        macd = [a - b for a, b in zip(e12, e26)]
        sig = self._ema_series(macd, 9)
        hist = macd[-1] - sig[-1]
        prev = macd[-2] - sig[-2]
        return {"bullish": hist > 0, "rising": hist > prev, "hist": hist}

    def _calc_adx(self, candles, period=14):
        """Robust Trend Strength (DX Proxy) - Fixes 100.0 bug"""
        if len(candles) < period + 2:
            return 0
        tr_list, plus_dm_list, minus_dm_list = [], [], []
        for i in range(1, len(candles)):
            h, l, pc = candles[i][2], candles[i][3], candles[i-1][4]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            tr_list.append(tr)
            up_move = h - candles[i-1][2]
            down_move = candles[i-1][3] - l
            plus_dm = up_move if (up_move > down_move and up_move > 0) else 0
            minus_dm = down_move if (down_move > up_move and down_move > 0) else 0
            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        atr = sum(tr_list[-period:]) / period
        if atr == 0: return 0
        plus_di = 100 * (sum(plus_dm_list[-period:]) / period) / atr
        minus_di = 100 * (sum(minus_dm_list[-period:]) / period) / atr
        
        di_sum = plus_di + minus_di
        dx = 100 * abs(plus_di - minus_di) / di_sum if di_sum > 0 else 0
        return dx

    def _calc_atr(self, candles, period=14):
        """Average True Range (14) — true market volatility"""
        if len(candles) < period + 1:
            return 0.0
        trs = []
        for i in range(1, len(candles)):
            h, l, pc = candles[i][2], candles[i][3], candles[i-1][4]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        return round(sum(trs[-period:]) / period, 1)

    def _calc_supertrend(self, candles, period=10, mult=3):
        if len(candles) < period + 2:
            return "NEUTRAL"
        trs = []
        for i in range(1, len(candles)):
            trs.append(max(candles[i][2]-candles[i][3],
                           abs(candles[i][2]-candles[i-1][4]),
                           abs(candles[i][3]-candles[i-1][4])))
        atr = sum(trs[-period:]) / period
        hl2 = (candles[-1][2] + candles[-1][3]) / 2
        if candles[-1][4] > hl2 + (atr * 0.5):
            return "BULLISH"
        if candles[-1][4] < hl2 - (atr * 0.5):
            return "BEARISH"
        return "NEUTRAL"

    def _tf_trend(self, candles):
        if len(candles) < 30:
            return "NEUTRAL"
        closes = [c[4] for c in candles]
        e20 = self._calc_ema(closes, 20)
        e50 = self._calc_ema(closes, 50) if len(closes) >= 50 else self._calc_ema(closes, 30)
        if closes[-1] > e20 > e50:
            return "BULLISH"
        if closes[-1] < e20 < e50:
            return "BEARISH"
        return "NEUTRAL"

    # ══════════ FINAL DECISION (with Session + MTF Filters) ══════════
    def generate_recommendation(self, analysis_results, confidence, risk_assessment, ranked_strikes):
        now = datetime.now()
        ctx = analysis_results.get("trade_context", {})
        learn = analysis_results.get("learning", {})
        move30 = ctx.get("move30", 0)
        direction = ctx.get("direction", "NEUTRAL")
        dscore = ctx.get("direction_score", 0)

        def no_trade(reason):
            return {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"),
                    "action": "NO_TRADE", "bias": "NEUTRAL", "confidence": confidence["score"],
                    "grade": "F", "reasons": [reason], "ai_score": confidence["score"]}

        hm = now.hour * 60 + now.minute
        if 555 <= hm <= 575:
            return no_trade("Opening session (9:15-9:35)")
        if hm >= 905:
            return no_trade("Closing session - no fresh entries")
        lunch_chop = 720 <= hm <= 795  # 12:00-13:15 lunch chop window

        # 🔒 MOVE GATE: 25 pts minimum + extra confirmation
        if abs(move30) < 25:
            return no_trade(f"Range-bound: 30-min move {round(move30)} pts (< 25)")

        # P0-3: Config-driven confidence threshold — single source of truth
        base_thr = self.config.get_int("analysis.min_confidence_threshold", 78)
        learn_adj = learn.get("threshold_adj", 0)
        # Bounded learning adjustment: effective KABHI configured base se neeche NAHI (safety floor)
        eff_thr = max(base_thr, base_thr + learn_adj)
        eff_thr = min(eff_thr, 92)  # sane upper cap
        if confidence["score"] < eff_thr:
            return no_trade(f"Confidence {confidence['score']}% < {eff_thr}% (base={base_thr}, learn_adj={learn_adj})")

        # BIAS FIX: direction NEUTRAL ho lekin strong dscore + trend ho, to trend use karo
        trend_dir = analysis_results.get("trend", {}).get("direction", "NEUTRAL")
        if dscore >= 70:
            bias = trend_dir if direction == "NEUTRAL" else direction
        else:
            bias = analysis_results.get("multi_timeframe", {}).get("direction", "NEUTRAL")

        best_ce = ranked_strikes.get("best_ce", {})
        best_pe = ranked_strikes.get("best_pe", {})
        if bias == "BULLISH" and best_ce:
            recommendation, option_type = best_ce, "CE"
        elif bias == "BEARISH" and best_pe:
            recommendation, option_type = best_pe, "PE"
        else:
            return no_trade("No directional alignment (move vs indicators)")

        # Self-Learning direction penalty
        pen = learn.get("ce_penalty", 0) if option_type == "CE" else learn.get("pe_penalty", 0)
        eff_conf = confidence["score"] - pen

        # BUY: 25+ pts + high dir score + high confidence
        move_gate = 30 if ctx.get("is_monthly_expiry") else 25
        # BUG #1 FIX: Explicit BUY threshold (config-driven margin)
        buy_margin = self.config.get_int("analysis.buy_confidence_margin", 2)
        buy_thr = eff_thr + buy_margin
        is_buy = abs(move30) >= move_gate and dscore >= 75 and eff_conf >= buy_thr and not lunch_chop
        action = "BUY" if is_buy else "WATCHLIST"

        reasons = self._build_reasons(analysis_results)
        reasons.extend(recommendation.get("reasons", []))
        reasons.append(f"30-min Move: {round(move30)} pts | Dir Score {dscore}")
        if lunch_chop and is_buy:
            reasons.append("Lunch chop (12:00-1:15) - watchlist only")
            action = "WATCHLIST"
        if ctx.get("is_monthly_expiry"):
            reasons.append("MONTHLY expiry: big fast moves - ITM only")
        elif ctx.get("is_expiry"):
            reasons.append("Expiry day: theta high - ATM/ITM only")
        reasons.append("📋 Plan: T1 par 50% exit + SL→entry | T2 par SL→T1")
        reasons.append("⚠️ Entry estimated - live premium match karke enter karein")
        reasons = list(dict.fromkeys(reasons))

        # 📊 TOP-3 STRIKE COMPARISON + WHY THIS STRIKE explanation
        _top3 = analysis_results.get("_top3_pe", []) if analysis_results.get("trade_context", {}).get("direction") == "BEARISH" else analysis_results.get("_top3_ce", [])
        _score_margin = analysis_results.get("_score_margin", 0)
        _best_strike = analysis_results.get("_best_strike", 0)
        
        # Build explanation
        _explanation_parts = []
        
        if _best_strike:
            # Get the best strike data (search works for ALL directions;
            # _top3 already selects CE/PE list based on direction above)
            _best_data = None
            for r in _top3:
                if r.get("strike") == _best_strike:
                    _best_data = r
                    break
            
            if _best_data:
                _explanation_parts.append(f"BEST STRIKE: {_best_strike} {option_type}")
                _explanation_parts.append(f"WHY #1:")
                _reasons = _best_data.get("reasons", [])
                # Map ranking reasons to user-friendly explanations
                reason_map = {
                    "ATM / Near ATM": "- ATM / near-ATM selection",
                    "Heuristic-Move Fit (Ideal Strike)": "- Strongest directional alignment",
                    "BEARISH Trend": "- Strongest directional alignment",
                    "Indicators BEARISH": "- Confirming indicators",
                    "Structure BEARISH": "- Market structure supports bias",
                    "Put Unwinding": "- Strong OI support",
                    "Near ATM": "- Near-ATM but secondary to ATM",
                }
                for r in _reasons:
                    if r in reason_map:
                        _explanation_parts.append(reason_map[r])
                
                # Explain why #2 and #3 lost
                if len(_top3) >= 2:
                    _explanation_parts.append(f"WHY NOT #2:")
                    _r2 = _top3[1] if len(_top3) > 1 else None
                    if _r2:
                        _r2_reasons = _r2.get("reasons", [])
                        # Find the strongest reason _2 has that _1 doesn't
                        _1_reasons_set = set(_best_data.get("reasons", []) if _best_data else [])
                        _2_reasons_set = set(_r2.get("reasons", []))
                        _unique_to_2 = _2_reasons_set - _1_reasons_set
                        if _unique_to_2:
                            for u in _unique_to_2:
                                _explanation_parts.append(f"  - {u} (but {_best_strike} has stronger overall score)")
                        else:
                            _explanation_parts.append("  - Lower combined score components")
                
                if len(_top3) >= 3:
                    _explanation_parts.append(f"WHY NOT #3:")
                    _r3 = _top3[2] if len(_top3) > 2 else None
                    if _r3:
                        _r3_reasons = _r3.get("reasons", [])
                        _1_reasons_set = set(_best_data.get("reasons", []) if _best_data else [])
                        _2_reasons_set = set(_top3[1].get("reasons", []) if len(_top3) > 1 else [])
                        _unique_to_3 = set(_r3_reasons) - _1_reasons_set - _2_reasons_set
                        if _unique_to_3:
                            for u in _unique_to_3:
                                _explanation_parts.append(f"  - {u}")
                        else:
                            _explanation_parts.append("  - Lower combined score components")
        
        # Score margin display
        if _score_margin > 0:
            _explanation_parts.append(f"SCORE MARGIN: +{_score_margin}")
        elif _score_margin == 0:
            _explanation_parts.append(f"SCORE MARGIN: Tied (no clear best)")
        
        # Only add explanation if we have data
        if _explanation_parts:
            _final_reasons = []
            # Preserve existing reasons first, then add explanation
            existing_reasons = reasons[:8]  # top 8 existing reasons
            _final_reasons.extend(existing_reasons)
            _final_reasons.append("")
            _final_reasons.append(" ".join(_explanation_parts))
            reasons = _final_reasons
        

        return {
            "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"),
            "action": f"{action} NIFTY {recommendation.get('strike', 'ATM')} {option_type}",
            "bias": bias, "strike": recommendation.get("strike", 0), "option_type": option_type,
            "confidence": confidence["score"], "grade": self._determine_grade(confidence["score"]),
            "entry": recommendation.get("entry", 0), "stop_loss": recommendation.get("stop_loss", 0),
            "target_1": recommendation.get("target_1", 0), "target_2": recommendation.get("target_2", 0),
            "target_3": recommendation.get("target_3", 0),
            "invalidation": ctx.get("invalidation_ce") if option_type == "CE" else ctx.get("invalidation_pe"),
            "vwap": ctx.get("vwap"), "move30": move30, "expected_move": ctx.get("expected_move"),
            "risk": risk_assessment.get("level", "MEDIUM"),
            "holding_time": "10-20 Minutes" if ctx.get("is_monthly_expiry") else ("10-25 Minutes" if ctx.get("is_expiry") else "15-45 Minutes"),
            "trade_plan": "T1: 50% exit + SL→entry | T2: SL→T1 | T3: full exit",
            "reasons": reasons[:10], "ai_score": confidence["score"],
        }

    def _build_reasons(self, a):
        reasons = []
        ms = a.get("market_structure", {})
        if ms.get("score", 0) > 70:
            reasons.append(f"Structure {ms.get('structure')}")
        ind = a.get("indicators", {})
        if ind.get("score", 0) > 70:
            reasons.append(f"Indicators Aligned (ADX {ind.get('adx')})")
        mtf = a.get("multi_timeframe", {})
        if mtf.get("alignment") == "ALIGNED":
            reasons.append(f"MTF Aligned (15m+1h {mtf.get('direction')})")
        oi = a.get("oi_analysis", {})
        if oi.get("score", 0) > 70:
            reasons.append(f"OI: {oi.get('signal')}")
        cs = a.get("candlestick", {})
        if cs.get("score", 0) > 70:
            reasons.append(f"Pattern: {cs.get('pattern')}")
        if not reasons:
            reasons.append("Multi-factor Confirmation")
        return reasons

    def _determine_grade(self, c):
        if c >= 95: return "A+"
        if c >= 90: return "A"
        if c >= 85: return "B+"
        if c >= 80: return "B"
        if c >= 70: return "C"
        return "F"
