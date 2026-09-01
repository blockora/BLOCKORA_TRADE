"""
Enhanced Strike Selector for BLOCKORA_TRADE
engines/ranking/strike_ranking_engine.py

Adaptive Strike Matrix - Dynamic strike selection
Replaces old 10-strike rigid system
"""

from datetime import datetime


class StrikeRankingEngine:
    """
    Adaptive Strike Matrix - Dynamic strike selection
    Replaces old 10-strike rigid system
    """

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.historical_volumes = {}  # (strike, type) -> [last 20 volumes]

    def rank_strikes(self, analysis_results):
        """
        Main method - returns best CE and PE strikes
        """
        self.logger.info("=== Adaptive Strike Ranking Started ===")

        market_data = analysis_results.get("market_data", {})
        option_chain = analysis_results.get("option_chain", {})
        spot = market_data.get("ltp", 0)

        if spot == 0:
            self.logger.warning("Spot price 0, cannot rank strikes")
            return {"best_ce": {}, "best_pe": {}, "ce_rankings": [], "pe_rankings": []}

        atr = market_data.get("atr", 12.5)
        vix = market_data.get("vix", 15)

        ctx = analysis_results.get("trade_context", {})
        time_to_expiry = self._get_time_to_expiry(ctx)
        is_expiry = ctx.get("is_expiry", False)
        is_monthly = ctx.get("is_monthly_expiry", False)

        self.logger.info(f"Spot: {spot} | ATR: {atr} | VIX: {vix} | Hours to expiry: {time_to_expiry:.1f}")

        strikes = self._get_adaptive_range(spot, atr, vix, time_to_expiry)
        self.logger.info(f"Analyzing {len(strikes)} strikes: {strikes[:5]}...{strikes[-3:]}")

        ce_scores = []
        pe_scores = []

        for strike in strikes:
            strike_key = str(strike)

            if strike_key in option_chain.get("ce_data", {}):
                ce_result = self._score_strike(
                    strike, spot, "CE", option_chain, market_data,
                    analysis_results, time_to_expiry, is_expiry, is_monthly
                )
                ce_scores.append(ce_result)

            if strike_key in option_chain.get("pe_data", {}):
                pe_result = self._score_strike(
                    strike, spot, "PE", option_chain, market_data,
                    analysis_results, time_to_expiry, is_expiry, is_monthly
                )
                pe_scores.append(pe_result)

        ce_scores.sort(key=lambda x: x["total_score"], reverse=True)
        pe_scores.sort(key=lambda x: x["total_score"], reverse=True)

        best_ce = ce_scores[0] if ce_scores else {}
        best_pe = pe_scores[0] if pe_scores else {}

        self.logger.info(f"Best CE: {best_ce.get('strike')} Score: {best_ce.get('total_score')}")
        self.logger.info(f"Best PE: {best_pe.get('strike')} Score: {best_pe.get('total_score')}")

        return {
            "best_ce": best_ce,
            "best_pe": best_pe,
            "ce_rankings": ce_scores,
            "pe_rankings": pe_scores
        }

    def _get_adaptive_range(self, spot, atr, vix, time_to_expiry_hours):
        """Dynamic strike range based on market conditions"""
        base_range = int(atr * 2.5)

        if vix > 20:
            base_range = int(base_range * 1.3)
            self.logger.info(f"VIX high ({vix}), expanding range")
        elif vix > 25:
            base_range = int(base_range * 1.6)

        if time_to_expiry_hours < 2:
            base_range = int(base_range * 0.4)
            self.logger.info("Expiry day scalp mode - tight range")
        elif time_to_expiry_hours < 6:
            base_range = int(base_range * 0.6)
        elif time_to_expiry_hours < 24:
            base_range = int(base_range * 0.8)

        half_range = max(100, (base_range // 50) * 50)
        atm = round(spot / 50) * 50

        return list(range(atm - half_range, atm + half_range + 1, 50))

    def _score_strike(self, strike, spot, opt_type, chain, market_data,
                      analysis_results, time_to_expiry, is_expiry, is_monthly):
        """10-factor scoring system - Total: 100 points"""

        strike_key = str(strike)
        my_data = chain.get("ce_data" if opt_type == "CE" else "pe_data", {}).get(strike_key, {})

        scores = {}
        reasons = []

        # === FACTOR 1: Moneyness/Delta (15 pts) ===
        distance = abs(strike - spot)
        if distance <= 25:
            scores["moneyness"] = 15
            reasons.append("ATM (Max Delta)")
        elif distance <= 75:
            scores["moneyness"] = 12
            reasons.append("Near ATM")
        elif distance <= 125:
            scores["moneyness"] = 8
        elif distance <= 200:
            scores["moneyness"] = 5
        else:
            scores["moneyness"] = 2

        # === FACTOR 2: Gamma Impact (10 pts) ===
        scores["gamma"] = self._gamma_score(strike, spot, time_to_expiry, opt_type)
        if scores["gamma"] >= 12:
            reasons.append("Gamma Blast Zone")

        # === FACTOR 3: Expected Move Fit (15 pts) ===
        exp_move = analysis_results.get("trade_context", {}).get("expected_move", 30)
        scores["move_fit"] = self._move_fit_score(strike, spot, exp_move, opt_type, my_data)
        if scores["move_fit"] >= 10:
            reasons.append("Sweet Move Zone")

        # === FACTOR 4: OI Quality (12 pts) ===
        pcr = chain.get("pcr", 1.0)
        scores["oi"] = self._enhanced_oi_score(strike, opt_type, spot,
            chain.get("ce_data", {}), chain.get("pe_data", {}), pcr)

        # === FACTOR 5: Volume Velocity (10 pts) ===
        hist_key = (strike, opt_type)
        hist_vols = self.historical_volumes.get(hist_key, [])
        hist_avg = sum(hist_vols) / max(1, len(hist_vols))
        scores["volume"] = self._volume_velocity_score(my_data, hist_avg)
        if scores["volume"] >= 8:
            reasons.append("Volume Spike")

        if hist_key not in self.historical_volumes:
            self.historical_volumes[hist_key] = []
        self.historical_volumes[hist_key].append(my_data.get("volume", 0))
        self.historical_volumes[hist_key] = self.historical_volumes[hist_key][-20:]

        # === FACTOR 6: Spread Efficiency (8 pts) ===
        scores["spread"] = self._spread_score(my_data)

        # === FACTOR 7: Trend Confluence (12 pts) ===
        scores["trend"] = self._trend_confluence_score(strike, opt_type, analysis_results)

        # === FACTOR 8: VWAP Distance (8 pts) ===
        vwap = market_data.get("vwap", spot)
        scores["vwap"] = self._vwap_score(spot, vwap, strike, opt_type, analysis_results)

        # === FACTOR 9: Max Pain (5 pts) ===
        max_pain = chain.get("max_pain", 0)
        scores["max_pain"] = self._max_pain_score(strike, max_pain)

        # === FACTOR 10: Historical Win Rate (5 pts) ===
        scores["historical"] = self._historical_score(strike, opt_type, analysis_results)

        # === PENALTIES ===
        total = sum(scores.values())

        if is_expiry:
            otm = (opt_type == "CE" and strike > spot) or (opt_type == "PE" and strike < spot)
            if otm:
                penalty = 12 if is_monthly else 8
                total -= penalty
                reasons.append(f"Expiry OTM Penalty (-{penalty})")

        if time_to_expiry < 6 and distance > 100:
            total -= 5
            reasons.append("Far OTM Theta Risk")

        return {
            "strike": strike,
            "option_type": opt_type,
            "total_score": max(0, min(100, total)),
            "scores": scores,
            "reasons": reasons,
            "ltp": my_data.get("ltp", 0),
            "oi": my_data.get("oi", 0),
            "change_oi": my_data.get("change_oi", 0),
            "volume": my_data.get("volume", 0),
            "iv": my_data.get("iv", 0)
        }

    def _gamma_score(self, strike, spot, time_to_expiry, opt_type):
        """Gamma scoring - critical for expiry day"""
        if time_to_expiry > 48:
            return 5

        distance = abs(strike - spot)

        if time_to_expiry < 6:
            if distance <= 25:
                return 10
            elif distance <= 75:
                return 7
            elif distance <= 125:
                return 3
            return 0

        elif time_to_expiry < 48:
            if distance <= 50:
                return 8
            elif distance <= 100:
                return 5
            return 3

        return 5

    def _move_fit_score(self, strike, spot, exp_move, opt_type, my_data):
        """Premium-aware move fit scoring"""
        premium = my_data.get("ltp", 0)

        if opt_type == "CE":
            if strike <= spot:
                return 0
            dist = strike - spot
            sweet_zone = exp_move / 2
            coverage = max(0, 1 - abs(dist - sweet_zone) / max(exp_move, 1))
            score = int(15 * coverage)
            if premium > exp_move * 0.3:
                score -= 3
        else:
            if strike >= spot:
                return 0
            dist = spot - strike
            sweet_zone = exp_move / 2
            coverage = max(0, 1 - abs(dist - sweet_zone) / max(exp_move, 1))
            score = int(15 * coverage)
            if premium > exp_move * 0.3:
                score -= 3

        return max(0, score)

    def _enhanced_oi_score(self, strike, opt_type, spot, ce_data, pe_data, pcr):
        """Enhanced OI scoring with context"""
        my_data = ce_data.get(str(strike), {}) if opt_type == "CE" else pe_data.get(str(strike), {})
        if not my_data:
            return 0

        oi = my_data.get("oi", 0)
        ch_oi = my_data.get("change_oi", 0)
        score = 0

        if ch_oi > 0:
            score += min(4, int(ch_oi / 2000))

        neighbor_oi = []
        for s in [strike-50, strike+50]:
            n = ce_data.get(str(s), {}) if opt_type == "CE" else pe_data.get(str(s), {})
            neighbor_oi.append(n.get("oi", 0))

        if neighbor_oi and oi > max(neighbor_oi) * 1.5:
            score += 3

        if pcr > 1.5 and opt_type == "CE":
            score += 2
        elif pcr < 0.5 and opt_type == "PE":
            score += 2

        opposite = pe_data if opt_type == "CE" else ce_data
        wall_strike = None
        wall_oi = 0
        for k, v in opposite.items():
            try:
                oi_val = float(v.get("oi", 0))
                if oi_val > wall_oi:
                    wall_oi = oi_val
                    wall_strike = int(k)
            except Exception:
                pass

        if wall_strike and abs(strike - wall_strike) <= 50:
            score -= 3

        return max(0, score)

    def _volume_velocity_score(self, my_data, hist_avg):
        """Volume velocity scoring"""
        current = my_data.get("volume", 0)
        if hist_avg <= 0:
            return 5
        ratio = current / hist_avg
        if ratio >= 3:
            return 10
        elif ratio >= 2:
            return 8
        elif ratio >= 1.5:
            return 6
        elif ratio >= 1:
            return 4
        return 2

    def _spread_score(self, my_data):
        """Bid-ask spread efficiency"""
        bid = my_data.get("bid", 0)
        ask = my_data.get("ask", 0)
        ltp = my_data.get("ltp", 0)

        if bid > 0 and ask > 0 and ltp > 0:
            spread_pct = (ask - bid) / ltp * 100
            if spread_pct <= 1:
                return 8
            elif spread_pct <= 3:
                return 5
            elif spread_pct <= 5:
                return 2
            return 0
        return 3

    def _trend_confluence_score(self, strike, opt_type, analysis_results):
        """Multi-timeframe trend alignment"""
        trend = analysis_results.get("trend", {})
        t_dir = trend.get("direction", "NEUTRAL")

        ind = analysis_results.get("indicators", {})
        rsi = ind.get("rsi", 50)
        macd_hist = ind.get("macd_hist", 0)

        mtf = analysis_results.get("multi_timeframe", {})
        t5 = mtf.get("t5", "NEUTRAL")
        t15 = mtf.get("t15", "NEUTRAL")
        t1h = mtf.get("t1h", "NEUTRAL")

        score = 0

        if (opt_type == "CE" and t_dir == "BULLISH") or (opt_type == "PE" and t_dir == "BEARISH"):
            score += 4

        align_count = sum(1 for t in [t5, t15, t1h] if t == t_dir)
        score += align_count * 2

        if opt_type == "CE" and 40 <= rsi <= 60:
            score += 2
        elif opt_type == "PE" and 40 <= rsi <= 60:
            score += 2

        if opt_type == "CE" and macd_hist > 0:
            score += 2
        elif opt_type == "PE" and macd_hist < 0:
            score += 2

        return min(12, score)

    def _vwap_score(self, spot, vwap, strike, opt_type, analysis_results):
        """VWAP-based institutional bias"""
        direction = analysis_results.get("trade_context", {}).get("direction", "NEUTRAL")

        if direction == "BULLISH":
            if spot > vwap:
                return 8 if opt_type == "CE" else 3
            else:
                return 3 if opt_type == "CE" else 6
        elif direction == "BEARISH":
            if spot < vwap:
                return 8 if opt_type == "PE" else 3
            else:
                return 3 if opt_type == "PE" else 6

        return 5

    def _max_pain_score(self, strike, max_pain):
        """Near max pain = higher probability"""
        if max_pain == 0:
            return 3
        dist = abs(strike - max_pain)
        if dist <= 50:
            return 5
        elif dist <= 100:
            return 3
        return 1

    def _historical_score(self, strike, opt_type, analysis_results):
        """Self-learning from past trades"""
        learning = analysis_results.get("learning", {})
        strike_key = f"{strike}_{opt_type}"
        win_rate = learning.get("strike_win_rates", {}).get(strike_key, 0.5)
        return int(win_rate * 5)

    def _get_time_to_expiry(self, ctx):
        """Hours to expiry calculation"""
        try:
            expiry = ctx.get("expiry_date")
            if expiry:
                exp_dt = datetime.strptime(expiry, "%d%b%Y")
                now = datetime.now()
                if now.date() == exp_dt.date():
                    market_close = datetime.combine(now.date(), datetime.strptime("15:30", "%H:%M").time())
                    hours = (market_close - now).total_seconds() / 3600
                    return max(0, hours)
                else:
                    days = (exp_dt - now).days
                    return days * 24
        except Exception:
            pass
        return 168
