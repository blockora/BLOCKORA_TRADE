#!/usr/bin/env python3
"""BLOCKORA_TRADE - Main Entry Point with Live AI Dashboard"""
import sys
import os
import signal
import threading
from datetime import datetime, time as dtime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config_manager import ConfigManager
from core.logger_manager import LoggerManager
from core.system_health import SystemHealth
from data.market_data_engine import MarketDataEngine
from data.option_chain_engine import OptionChainEngine
from database.db_manager import DatabaseManager
from engines.decision.master_decision_engine import MasterDecisionEngine
from engines.confidence.confidence_engine import ConfidenceEngine
from engines.risk.risk_engine import RiskEngine
from engines.ranking.strike_ranking_engine import StrikeRankingEngine
from engines.learning.outcome_tracker import OutcomeTracker, SelfLearner
from data.data_freshness_guard import DataFreshnessGuard
from engines.liquidity.liquidity_engine import LiquidityEngine
from engines.regime.market_regime_engine import MarketRegimeEngine
from engines.decision.decision_validator import DecisionValidator
from telegram.telegram_bot import TelegramBot
from core.system_shutdown import SystemShutdown


class BlockoraTrade:
    VERSION = "1.0"
    APP_NAME = "BLOCKORA_TRADE"

    def __init__(self):
        self.running = False
        self.market_open = False
        self.cycle_count = 0
        self.config = None
        self.logger = None
        self.db = None
        self.market_engine = None
        self.option_engine = None
        self.decision_engine = None
        self.confidence_engine = None
        self.risk_engine = None
        self.ranking_engine = None
        self.telegram = None
        self.health_monitor = None
        self.last_signal_key = ""
        self.last_signal_time = 0
        self.watchlist_tracker = {}
        self.active_trade = None

    def initialize(self):
        print(f"\n{'='*60}")
        print(f"  {self.APP_NAME} v{self.VERSION}")
        print(f"  AI Powered NIFTY Options Decision Engine")
        print(f"  Platform: Android Termux")
        print(f"{'='*60}\n")

        try:
            print("[1/10] Loading Configuration...")
            self.config = ConfigManager()
            self.config.load()
            print("  ✓ Configuration loaded")

            print("[2/10] Initializing Logger...")
            self.logger = LoggerManager(self.config)
            self.logger.setup()
            self.logger.info(f"{self.APP_NAME} v{self.VERSION} starting...")
            print("  ✓ Logger initialized")

            print("[3/10] Initializing Database...")
            self.db = DatabaseManager(self.config, self.logger)
            self.db.initialize()
            print("  ✓ Database connected")

            print("[4/10] Initializing Market Data Engine...")
            self.market_engine = MarketDataEngine(self.config, self.logger)
            self.market_engine.initialize()
            print("  ✓ Market Data Engine ready")

            print("[5/10] Initializing Option Chain Engine...")
            self.option_engine = OptionChainEngine(self.config, self.logger)
            self.option_engine.initialize()
            print("  ✓ Option Chain Engine ready")

            print("[6/10] Initializing Analysis Engines...")
            self.confidence_engine = ConfidenceEngine(self.config, self.logger)
            self.risk_engine = RiskEngine(self.config, self.logger)
            self.ranking_engine = StrikeRankingEngine(self.config, self.logger)
            self.decision_engine = MasterDecisionEngine(
                config=self.config, logger=self.logger,
                confidence_engine=self.confidence_engine,
                risk_engine=self.risk_engine,
                ranking_engine=self.ranking_engine
            )
            print("  ✓ Analysis Engines ready (30+ modules)")

            print("[7/10] Initializing Telegram Bot...")
            self.telegram = TelegramBot(self.config, self.logger)
            self.telegram.initialize()
            if getattr(self.telegram, "connected", False):
                print("  ✓ Telegram Bot connected")
            else:
                print("  ⚠️ Telegram not configured/connected")
            self.freshness_guard = DataFreshnessGuard(self.logger)
            self.liquidity_engine = LiquidityEngine(self.logger)
            self._prev_oi = {}  # change-OI tracking: (option_type, strike) -> previous_oi
            self.regime_engine = MarketRegimeEngine(self.logger, self.config)
            self.decision_validator = DecisionValidator(self.config, self.logger)
            self.tracker = OutcomeTracker(self.db, self.logger)
            self.db.cleanup_old_signals()  # purane din ka data auto-delete

            # 🔥 5-CYCLE LTP MOMENTUM TRACKER (independent, non-invasive)
            from engines.tracking.momentum_tracker import MomentumTracker
            self.momentum_tracker = MomentumTracker(self.logger)

            # 📈 JUGAAD-DATA IV FETCHER: real NSE IV (block-free), sirf enrich karta hai
            from data.jugaad_iv_fetcher import JugaadIVFetcher
            self.jugaad_iv = JugaadIVFetcher(self.logger)
            self.jugaad_iv.refresh()  # startup me warm-up (fail ho to bhi safe)

            self.learner = SelfLearner(self.db, self.logger)
            print("  ✓ Self-Learning Engine active (Outcome Tracker)")

            from telegram.subscription_manager import SubscriptionManager
            self.sub_manager = SubscriptionManager(self.config, self.logger, self.db, self.telegram)
            self.sub_manager.start()
            print("  ✓ Subscription Manager active (₹499/month)")

            print("[8/10] Initializing Health Monitor...")
            self.health_monitor = SystemHealth(self.config, self.logger)
            print("  ✓ Health Monitor active")

            print("[9/10] Running System Validation...")
            validation = self.validate_system()
            self.system_degraded = not validation["status"]
            if self.system_degraded:
                print(f"  ⚠️ DEGRADED: {validation['error']}")
            else:
                print("  ✓ System validation passed")

            print("[10/10] System Ready!")
            print(f"\n{'='*60}")
            if self.system_degraded:
                print(f"  SYSTEM STATUS: ⚠️ DEGRADED")
                print(f"  ⚠️ Broker NOT connected - trading signals disabled")
            else:
                print(f"  SYSTEM STATUS: ✅ READY")
            print(f"  Mode: {self.config.get('MODE', 'production')}")
            print(f"  Market: NIFTY Options")
            print(f"  Policy: RECOMMENDATION ONLY (No Auto Trading)")
            print(f"{'='*60}\n")

            self.logger.info("System initialization complete")
            return True

        except Exception as e:
            print(f"\n  ✗ Initialization Error: {str(e)}")
            if self.logger:
                self.logger.error(f"Initialization failed: {str(e)}")
            return False

    def validate_system(self):
        # P0-2: Actual CONNECTION check (sirf object existence nahi)
        checks = {
            "config": self.config is not None,
            "database": self.db is not None and self.db.is_connected(),
            "market_engine": self.market_engine is not None and getattr(self.market_engine, "connected", False),
            "option_engine": self.option_engine is not None,
            "decision_engine": self.decision_engine is not None,
            "telegram": self.telegram is not None and getattr(self.telegram, "connected", False),
        }
        failed = [c for c, s in checks.items() if not s]
        if failed:
            return {"status": False, "error": f"not connected/initialized: {', '.join(failed)}"}
        return {"status": True, "error": None}

    def is_market_open(self):
        now = self.config.now() if self.config else datetime.now()
        if now.weekday() >= 5:
            return False
        market_open = dtime(9, 15)
        market_close = dtime(15, 30)
        return market_open <= now.time() <= market_close

    def _build_angel_chain(self, market_data):
        """Angel One live data se NSE-format option chain banata hai"""
        try:
            from datetime import datetime
            spot = market_data.get("ltp", 0)
            if not spot:
                return None
            tokens = self.market_engine.get_option_tokens()
            if not tokens:
                return None
            atm = round(spot / 50) * 50
            # BUG #8: Configurable wide chain for market-wide analysis (PCR, OI walls, max pain)
            analysis_range = self.config.get_int("analysis.option_chain_analysis_range", 750)
            half = int(analysis_range / 50)
            strikes = [atm + (i * 50) for i in range(-half, half + 1)]
            chain_start_time = datetime.now().isoformat()  # Timestamp chain build START par (not end)
            tok_map, need = {}, []
            for s in strikes:
                for t in ("CE", "PE"):
                    tok = tokens.get(f"{s}_{t}")
                    if tok:
                        tok_map[tok] = (s, t)
                        need.append(tok)
            if not need:
                return None
            full = self.market_engine.get_market_full(need)
            if not full:
                return None
            ce_data, pe_data, tot_ce, tot_pe = {}, {}, 0, 0

            for tok, (s, t) in tok_map.items():
                d = full.get(tok)
                if not d:
                    continue

                # P1-5: HONEST field extraction + source metadata
                # OI — Angel actual field: "opnInterest"
                oi = float(d.get("opnInterest") or d.get("oi") or d.get("openInterest") or d.get("openinterest") or 0)
                oi_source = "REAL" if oi > 0 else "MISSING"

                # Change-OI: Broker se try karo, warna previous cycle se calculate karo
                raw_ch_oi = d.get("changeinopeninterest") or d.get("changeinOpenInterest") or d.get("change_oi")
                if raw_ch_oi is not None:
                    try:
                        ch_oi = float(raw_ch_oi)
                        change_oi_source = "REAL"
                    except (TypeError, ValueError):
                        ch_oi = 0.0
                        change_oi_source = "INVALID"
                else:
                    # Broker ne nahi diya — previous cycle se calculate karo
                    key = (t, s)  # (option_type, strike)
                    prev_oi = self._prev_oi.get(key)
                    if prev_oi is not None and oi > 0:
                        ch_oi = oi - prev_oi
                        change_oi_source = "CALCULATED"
                    else:
                        ch_oi = 0.0
                        change_oi_source = "UNKNOWN"
                    # Current OI store karo next cycle ke liye
                    self._prev_oi[key] = oi

                # Volume — Angel actual field: "tradeVolume"
                vol = float(d.get("tradeVolume") or d.get("volume") or d.get("quantity") or 0)
                if vol == 0 and oi > 0:
                    vol = oi * 0.1
                    volume_source = "ESTIMATED"
                elif vol > 0:
                    volume_source = "REAL"
                else:
                    volume_source = "MISSING"

                # IV — SmartAPI NIFTY options me IV NAHI deta, isliye Jugaad-data se real NSE IV
                iv = float(d.get("iv") or d.get("impliedVolatility") or 0)
                if iv <= 0:
                    try:
                        iv = float(self.jugaad_iv.get_iv(t, s) or 0)
                    except Exception:
                        iv = 0.0
                iv_source = "REAL" if iv > 0 else "UNKNOWN"

                # Bid/Ask — extracted from depth dict (first level = best bid/ask)
                bid = 0; ask = 0
                bid_source = "UNKNOWN"; ask_source = "UNKNOWN"
                try:
                    depth = d.get("depth") or {}
                    buy_levels = depth.get("buy") or []
                    sell_levels = depth.get("sell") or []
                    if buy_levels and isinstance(buy_levels[0], dict):
                        bid = float(buy_levels[0].get("price", 0) or 0)
                        if bid > 0: bid_source = "REAL"
                    if sell_levels and isinstance(sell_levels[0], dict):
                        ask = float(sell_levels[0].get("price", 0) or 0)
                        if ask > 0: ask_source = "REAL"
                except Exception:
                    pass

                rec = {"strike": s, "ltp": float(d.get("ltp", 0) or 0),
                       "oi": oi, "change_oi": ch_oi, "volume": vol,
                       "iv": iv, "bid": bid, "ask": ask,
                       "oi_source": oi_source, "change_oi_source": change_oi_source,
                       "volume_source": volume_source, "iv_source": iv_source,
                       "bid_source": bid_source, "ask_source": ask_source}
                if t == "CE":
                    ce_data[s] = rec
                    tot_ce += oi
                else:
                    pe_data[s] = rec
                    tot_pe += oi
            if not ce_data or not pe_data:
                return None
            # BUG #5 FIX: Max Pain — ATM = max pain NAHI hai. Calculate ya UNKNOWN
            pcr_val = round(tot_pe / tot_ce, 2) if tot_ce else 1.0
            calc_max_pain, max_pain_source = self._calculate_max_pain(ce_data, pe_data)
            return {"timestamp": chain_start_time, "spot_price": spot,
                    "atm_strike": atm, "strikes": strikes, "ce_data": ce_data,
                    "pe_data": pe_data, "pcr": pcr_val, "pcr_source": "CALCULATED" if tot_ce > 0 and tot_pe > 0 else "UNKNOWN",
                    "max_pain": calc_max_pain, "max_pain_source": max_pain_source,
                    "source": "ANGEL_LIVE"}
        except Exception as e:
            self.logger.warning(f"Angel chain failed: {e}")
            # Fallback to Jugaad-data when Angel API fails
            try:
                return self._jugaad_fallback_chain(market_data.get("ltp", 0), strikes)
            except Exception:
                return None

    def _jugaad_fallback_chain(self, spot, strikes):
        """Fall back to jugaad-data NSE when Angel API fails"""
        try:
            from jugaad_data.nse import NSELive
            n = NSELive()
            oc = n.index_option_chain("NIFTY")
            rec = oc.get("records", {})
            data = rec.get("data", [])
            if not data:
                return None
            
            ce_data, pe_data = {}, {}
            tot_ce, tot_pe = 0, 0
            
            for it in data:
                s = it.get("strikePrice")
                if s is None:
                    continue
                ce = it.get("CE", {})
                pe = it.get("PE", {})
                
                ce_ltp = float(ce.get("lastPrice") or 0)
                ce_iv = float(ce.get("impliedVolatility") or 0)
                pe_ltp = float(pe.get("lastPrice") or 0)
                pe_iv = float(pe.get("impliedVolatility") or 0)
                ce_oi = float(ce.get("openInterest") or 0)
                pe_oi = float(pe.get("openInterest") or 0)
                
                rec = {"strike": s, "ltp": ce_ltp, "oi": ce_oi, "change_oi": 0, "volume": 0,
                       "iv": ce_iv, "bid": 0, "ask": 0,
                       "oi_source": "JUGAAD", "change_oi_source": "UNKNOWN",
                       "volume_source": "UNKNOWN", "iv_source": "JUGAAD",
                       "bid_source": "UNKNOWN", "ask_source": "UNKNOWN"}
                ce_data[s] = rec
                tot_ce += 1
                
                rec_pe = {"strike": s, "ltp": pe_ltp, "oi": pe_oi, "change_oi": 0, "volume": 0,
                   "iv": pe_iv, "bid": 0, "ask": 0,
                   "oi_source": "JUGAAD", "change_oi_source": "UNKNOWN",
                   "volume_source": "UNKNOWN", "iv_source": "JUGAAD",
                   "bid_source": "UNKNOWN", "ask_source": "UNKNOWN"}
                pe_data[s] = rec_pe
                tot_pe += 1
            
            if not ce_data or not pe_data:
                return None
            
            pcr_val = round(tot_pe / tot_ce, 2) if tot_ce else 1.0
            return {"timestamp": datetime.now().isoformat(),
                    "spot_price": spot,
                    "atm_strike": spot if spot else 0,
                    "strikes": strikes[:len(ce_data)] if strikes else list(ce_data.keys()),
                    "ce_data": ce_data,
                    "pe_data": pe_data,
                    "pcr": pcr_val, "pcr_source": "JUGAAD",
                    "max_pain": 0, "max_pain_source": "UNKNOWN",
                    "source": "JUGAAD_DATA"}
        except Exception as e:
            self.logger.error(f"Jugaad fallback chain failed: {e}")
            # Reset freshness guard so new data is accepted
            self.freshness_guard.mark_fetch()
            # Update market_data with required fields for freshness guard
            market_data["timestamp"] = datetime.now().isoformat()
            market_data["candles"] = []
            # Try fallback to jugaad-data
            try:
                return self._jugaad_fallback_chain(market_data.get("ltp", 0), strikes)
            except Exception:
                return None

    def _calculate_max_pain(self, ce_data, pe_data, min_strikes=5):
        """BUG #5: Actual max pain calculate karo — strike jahan total option writer pain MAX ho.
        Returns: (max_pain_strike, source) — source = CALCULATED ya UNKNOWN"""
        try:
            all_strikes = sorted(set(ce_data.keys()) | set(pe_data.keys()))
            if len(all_strikes) < min_strikes:
                return None, "UNKNOWN"
            best_strike = None
            min_pain = float("inf")
            for candidate in all_strikes:
                total_pain = 0
                for s in all_strikes:
                    try:
                        ce_oi = float(ce_data.get(s, {}).get("oi", 0) or 0)
                        pe_oi = float(pe_data.get(s, {}).get("oi", 0) or 0)
                        # CE writer pain at expiry price = candidate
                        if candidate > s:
                            total_pain += ce_oi * (candidate - s)
                        # PE writer pain
                        if candidate < s:
                            total_pain += pe_oi * (s - candidate)
                    except Exception:
                        continue
                if total_pain < min_pain:
                    min_pain = total_pain
                    best_strike = candidate
            if best_strike is None:
                return None, "UNKNOWN"
            return int(best_strike), "CALCULATED"
        except Exception:
            return None, "UNKNOWN"

    def _top3_score_margin(self, ce_ranks, pe_ranks, direction):
        """Score margin: top-1 score minus top-2 score for the active side (0 if tied/none)."""
        side = pe_ranks if direction == "BEARISH" else ce_ranks
        if len(side) < 2:
            return 0
        return round(float(side[0].get("score", 0)) - float(side[1].get("score", 0)), 2)

    def _fetch_graduation_ltp(self, recommendation):
        """FIX #6: Graduation moment par CURRENT real option LTP fetch"""
        try:
            strike = recommendation.get("strike", 0)
            opt_type = str(recommendation.get("option_type", "")).upper()
            if not strike or opt_type not in ("CE", "PE"):
                return None
            tokens = self.market_engine.get_option_tokens()
            token = (tokens or {}).get(f"{int(strike)}_{opt_type}")
            if not token:
                return None
            raw = self.market_engine.get_option_ltp(token)
            if isinstance(raw, dict):
                raw = raw.get("ltp") or raw.get("last_traded_price") or 0
            ltp = float(raw or 0)
            return ltp if ltp > 0 else None
        except Exception:
            return None

    def _recalc_levels_from_ltp(self, recommendation, fresh_ltp):
        """FIX #7: Fresh REAL LTP se entry/SL/targets recalculate (scalp model)"""
        from datetime import datetime
        entry = round(float(fresh_ltp), 2)
        recommendation["entry"] = entry
        recommendation["ltp"] = entry
        recommendation["premium"] = entry
        recommendation["stop_loss"] = round(max(entry - 6, 1), 2)
        recommendation["target_1"] = round(entry + 8, 2)
        recommendation["target_2"] = round(entry + 12, 2)
        recommendation["target_3"] = round(entry + 18, 2)
        recommendation["premium_source"] = "REAL"
        recommendation["premium_is_real"] = True
        recommendation["premium_timestamp"] = datetime.now().isoformat()
        recommendation["premium_age_seconds"] = 0

    def run_analysis_cycle(self):
        try:
            self.cycle_count += 1

            market_data = self.market_engine.get_live_data()
            if not market_data:
                return None
            # P0-3: mark_fetch SIRF fresh broker response par (cached par nahi)
            if getattr(self.market_engine, "_last_get_live_fresh", False):
                self.freshness_guard.mark_fetch()
            else:
                market_data["data_source"] = "CACHE"

            try:
                vix = self.market_engine.get_vix()
            except Exception:
                vix = None

            option_chain = self.option_engine.get_option_chain(market_data)

            # 💰 ANGEL LIVE CHAIN: real LTP + real OI (NSE block ho tab bhi)
            if not option_chain or not option_chain.get("ce_data"):
                live_chain = self._build_angel_chain(market_data)
                if live_chain:
                    option_chain = live_chain
                    self.logger.info(f"Angel LIVE chain ready: {len(live_chain['ce_data'])} strikes | PCR {live_chain['pcr']}")

            # 🕐 DATA FRESHNESS GUARD: stale data = NO_TRADE
            fresh, stale_reasons = self.freshness_guard.check(market_data, option_chain)
            if not fresh:
                # Format user-friendly reasons
                reason_str = ", ".join(stale_reasons)
                self.logger.info(f"Data freshness check: {reason_str}")
                
                # If outside market hours, explain why
                if not self.is_market_open():
                    self.logger.info("🛑 Market is currently closed - data freshness checks limited")
                
                # Retry fetch once with fresh broker data
                market_data = self.market_engine.get_live_data() or market_data
                # P0-2: mark_fetch SIRF fresh broker response par (cached par NEVER)
                if getattr(self.market_engine, "_last_get_live_fresh", False):
                    self.freshness_guard.mark_fetch()
                else:
                    market_data["data_source"] = "CACHE"
                fresh, stale_reasons = self.freshness_guard.check(market_data, option_chain)
            if not fresh:
                # Show clear reason for NO_TRADE
                reason_str = ", ".join(stale_reasons)
                self.logger.warning(f"🛡️ NO_TRADE: Capital protected - {reason_str}")
                return None

            if not option_chain:
                # 🔥 FIX: NSE blocked/404 hua toh bhi AI Price Action (Candles) se analysis karega
                self.logger.warning("NSE Option Chain unavailable (404) - Using Price Action fallback")
                option_chain = {
                    "timestamp": datetime.now().isoformat(),
                    "spot_price": market_data.get("ltp", 0),
                    "ce_data": {}, "pe_data": {}, "pcr": 1.0, "source": "FALLBACK"
                }

            # 🛡️ P0-3: Option-chain timestamp validation (missing/invalid → NO_TRADE)
            _chain_ts = (option_chain or {}).get("timestamp", "")
            _chain_ts_ok = False
            if _chain_ts:
                try:
                    datetime.fromisoformat(str(_chain_ts))
                    _chain_ts_ok = True
                except Exception:
                    _chain_ts_ok = False
            if not _chain_ts_ok:
                self.logger.warning("NO_TRADE cycle: option chain timestamp missing/invalid")
                return None

            analysis_results = self.decision_engine.run_analysis(
                market_data=market_data, option_chain=option_chain
            )
            analysis_results["learning"] = self.learner.get_params()
            confidence = self.confidence_engine.calculate(analysis_results)

            # 💧 LIQUIDITY ENGINE: illiquid strikes hatao before ranking
            option_chain, liq_stats = self.liquidity_engine.filter_chain(option_chain)
            analysis_results["option_chain"] = option_chain
            analysis_results["liquidity"] = liq_stats

            # 🌊 MARKET REGIME: detect trending/sideways/volatility
            regime = self.regime_engine.detect(market_data, analysis_results)
            analysis_results["regime"] = regime

            ranked_strikes = self.ranking_engine.rank(analysis_results, confidence)
            risk_assessment = self.risk_engine.evaluate(analysis_results, confidence)

            # 🎯 v2.1+ PERFECT STRIKE: top-3 + best-strike + score-margin populate
            # ("WHY THIS STRIKE / WHY NOT #2/#3" explanation ke liye)
            _ce_ranks = ranked_strikes.get("ce_rankings", [])
            _pe_ranks = ranked_strikes.get("pe_rankings", [])
            analysis_results["_top3_ce"] = _ce_ranks[:3]
            analysis_results["_top3_pe"] = _pe_ranks[:3]
            _dir = str(analysis_results.get("trade_context", {}).get("direction", "")).upper()
            _bc = ranked_strikes.get("best_ce") or {}
            _bp = ranked_strikes.get("best_pe") or {}
            if _dir == "BEARISH":
                _best_strike = _bp or _bc
            elif _dir == "BULLISH":
                _best_strike = _bc or _bp
            else:
                _best_strike = _bc if (_bc.get("score", 0) >= _bp.get("score", 0)) else _bp
            analysis_results["_best_strike"] = _best_strike.get("strike", 0)
            analysis_results["_score_margin"] = self._top3_score_margin(_ce_ranks, _pe_ranks, _dir)

            # 🔥 5-CYCLE LTP MOMENTUM TRACKER: cycle lock + track + evaluate
            # (independent logic — existing ranking/score/output pe koi asar nahi)
            try:
                self.momentum_tracker.update(_bc, _bp, option_chain)
            except Exception:
                pass  # tracker kabhi crash nahi karega

            # 🛡️ AI DECISION VALIDATOR: ranking ke baad, decision se pehle
            validation = self.decision_validator.validate({
                "fresh": fresh,
                "liq_stats": liq_stats,
                "regime": analysis_results.get("regime", {}),
                "vix": vix,
                "confidence": confidence.get("score", 0),
                "best_strike": _best_strike,
                "spot": market_data.get("ltp", 0),
                "direction": analysis_results.get("trade_context", {}).get("direction", ""),
                "chain": option_chain,
                "risk_stats": self.db.get_daily_risk_stats(),
            })
            analysis_results["validation"] = validation

            recommendation = self.decision_engine.generate_recommendation(
                analysis_results=analysis_results, confidence=confidence,
                risk_assessment=risk_assessment, ranked_strikes=ranked_strikes
            )

            # 🛡️ VALIDATOR REJECT: unsafe trade block
            if not validation["valid"] and recommendation["action"] != "NO_TRADE":
                recommendation["action"] = "NO_TRADE"
                recommendation["reasons"] = ["🛡️ Validator: " + ", ".join(validation["reasons"])]
            self._validator_rejected = not validation["valid"] and recommendation["action"] != "NO_TRADE"

            # 🔥 VOLATILITY ALERTS (graduated policy): EXTREME block / HIGH scalp mode
            try:
                _reg = analysis_results.get("regime", {}) or {}
                _rtype = str(_reg.get("type", "")).upper()
                if _rtype == "EXTREME_VOLATILITY":
                    self.telegram.send_extreme_volatility_alert(_reg)
                elif _rtype == "HIGH_VOLATILITY":
                    _vres = getattr(self.decision_validator, "_vol_flags", None)
                    _vrej = getattr(self.decision_validator, "_vol_rejects", None)
                    if _vres is not None:
                        self.telegram.send_high_volatility_alert(
                            flags=_vres, reject=_vrej,
                            position_pct=getattr(self.decision_validator, "volatility_manager", None).position_pct) \
                            if getattr(self.decision_validator, "volatility_manager", None) is not None else None
            except Exception:
                pass

            # 🛑 RISK LIMITS: daily loss / consec loss / max trades = EMERGENCY STOP
            risk_stats = self.db.get_daily_risk_stats()
            analysis_results["risk_stats"] = risk_stats
            limits_ok, limit_reasons = self.risk_engine.check_limits(risk_stats)
            if not limits_ok and recommendation["action"].startswith("BUY"):
                recommendation["action"] = "NO_TRADE"
                recommendation["reasons"] = ["🛑 EMERGENCY STOP: " + ", ".join(limit_reasons)]

            # 🛡️ FIX #4.4 + #5: REAL LTP SAFETY GATE (final BUY decision point)
            _dir = str(analysis_results.get("trade_context", {}).get("direction", "")).upper()
            _bc = ranked_strikes.get("best_ce") or {}
            _bp = ranked_strikes.get("best_pe") or {}
            if _dir == "BEARISH":
                _best = _bp or _bc
            elif _dir == "BULLISH":
                _best = _bc or _bp
            else:
                _best = _bc if (_bc.get("score", 0) >= _bp.get("score", 0)) else _bp

            if recommendation["action"].startswith("BUY"):
                # P1-2: Estimated volume candidate → BUY block
                _vol_src = str(_best.get("volume_source", "")).upper() or "UNKNOWN"
                if _vol_src != "REAL":
                    recommendation["action"] = recommendation["action"].replace("BUY", "WATCHLIST", 1)
                    recommendation["buy_blocked"] = True
                    recommendation["price_status"] = "ESTIMATED_VOLUME"
                    recommendation["buy_blocked_reason"] = f"Option volume not verified REAL ({_vol_src}) - not eligible for BUY"
                    recommendation["reasons"] = [f"⚠️ BUY BLOCKED: Option volume not verified REAL ({_vol_src})"]
                    recommendation["premium_source"] = _best.get("premium_source", "UNKNOWN")
                    self.logger.warning(
                        f"BUY_BLOCKED reason=ESTIMATED_VOLUME symbol=NIFTY "
                        f"strike={_best.get('strike', 'N/A')} option_type={_best.get('option_type', 'N/A')} "
                        f"volume_source={_vol_src}"
                    )
                elif not self.ranking_engine.is_real_ltp_valid(recommendation):
                    # 🛡️ FIX #8/#9/#10: FAIL-SAFE — blocked BUY → WATCHLIST with exact reason
                    price_status = self.ranking_engine.classify_price_source(_best)
                    _block_reasons = {
                        "STALE": "Real-time option LTP unavailable/stale",
                        "ESTIMATED": "Estimated premium is not eligible for BUY",
                        "INVALID": "Option premium data invalid",
                        "MISSING": "Option premium data missing",
                    }
                    blocked_reason = _block_reasons.get(price_status, "Real-time option LTP unavailable/stale")
                    recommendation["action"] = recommendation["action"].replace("BUY", "WATCHLIST", 1)
                    recommendation["buy_blocked"] = True
                    recommendation["price_status"] = price_status
                    recommendation["buy_blocked_reason"] = blocked_reason
                    recommendation["reasons"] = [f"⚠️ BUY BLOCKED: {blocked_reason}"]
                    recommendation["premium_source"] = _best.get("premium_source", "UNKNOWN")

                    # 🎯 RULE #13: Structured BUY_BLOCKED logging
                    _strike = _best.get("strike", "N/A")
                    _opt = _best.get("option_type", "N/A")
                    _age = _best.get("premium_age_seconds", "N/A")
                    _max_age = self.config.get_int("analysis.max_ltp_age_seconds", 15)
                    _reason_code = f"REAL_LTP_{price_status}"
                    self.logger.warning(
                        f"BUY_BLOCKED reason={_reason_code} "
                        f"symbol=NIFTY strike={_strike} option_type={_opt} "
                        f"premium_source={_best.get('premium_source', 'UNKNOWN')} "
                        f"age_seconds={_age} max_age_seconds={_max_age}"
                    )
                else:
                    recommendation["premium_source"] = "REAL"
                    recommendation["price_status"] = "REAL"

            # 🎓 GRADUATED SIGNAL + FIX #6/#7: conversion par FRESH REAL LTP validate
            import time as _t2
            graduated = False
            act = recommendation["action"]
            if act.startswith("WATCHLIST"):
                now_ts = _t2.time()
                if act not in self.watchlist_tracker:
                    self.watchlist_tracker = {act: now_ts}
                else:
                    wl_age = now_ts - self.watchlist_tracker.get(act, now_ts)
                    if wl_age > 900:
                        # FIX #5: 15 min tak real LTP nahi → expire
                        self.watchlist_tracker = {}
                        recommendation["action"] = "NO_TRADE"
                        recommendation["reasons"] = ["WATCHLIST expired: 15 min, no valid REAL LTP"]
                    elif wl_age >= 180 and recommendation.get("confidence", 0) >= 76:
                        # FIX #6: BUY conversion ke EXACT moment par fresh LTP fetch
                        fresh_ltp = self._fetch_graduation_ltp(recommendation)
                        if fresh_ltp is None:
                            self.watchlist_tracker = {}
                            recommendation["signal_status"] = "⏳ Graduation blocked: real LTP unavailable"
                        else:
                            # FIX #7: Fresh LTP se entry/SL/targets/RR recalculate
                            old_entry = float(recommendation.get("entry", 0) or 0)
                            self._recalc_levels_from_ltp(recommendation, fresh_ltp)
                            if old_entry > 0 and abs(fresh_ltp - old_entry) / old_entry > 0.20:
                                self.logger.warning(f"Graduation price divergence: {old_entry} → {fresh_ltp} (recalculated)")
                            recommendation["action"] = act.replace("WATCHLIST", "BUY", 1)
                            recommendation["signal_status"] = "🎓 GRADUATED (fresh REAL LTP verified)"
                            graduated = True
            else:
                self.watchlist_tracker = {}

            # 🛡️ FIX #1: Graduated BUY ko safety gates se DOBARA guzaro (bypass band)
            if graduated and recommendation["action"].startswith("BUY"):
                re_val = self.decision_validator.validate({
                    "fresh": fresh,
                    "liq_stats": liq_stats,
                    "regime": analysis_results.get("regime", {}),
                    "vix": vix,
                    "confidence": confidence.get("score", 0),
                    "best_strike": recommendation,
                    "spot": market_data.get("ltp", 0),
                    "direction": analysis_results.get("trade_context", {}).get("direction", ""),
                    "chain": option_chain,
                    "risk_stats": self.db.get_daily_risk_stats(),
                })
                if not re_val["valid"]:
                    recommendation["action"] = "NO_TRADE"
                    recommendation["reasons"] = ["🛡️ Validator (graduated): " + ", ".join(re_val["reasons"])]

                else:
                    lim_ok, lim_reasons = self.risk_engine.check_limits(risk_stats)
                    if not lim_ok:
                        recommendation["action"] = "NO_TRADE"
                        recommendation["reasons"] = ["🛑 EMERGENCY STOP (graduated): " + ", ".join(lim_reasons)]
                    elif not self.ranking_engine.is_real_ltp_valid(_best):
                        recommendation["action"] = "NO_TRADE"
                        recommendation["reasons"] = ["BUY blocked: real-time option LTP unavailable/stale"]
                        # 🎯 RULE #13: Structured logging for graduated BUY block
                        price_status = self.ranking_engine.classify_price_source(_best)
                        _strike = _best.get("strike", "N/A")
                        _opt = _best.get("option_type", "N/A")
                        _age = _best.get("premium_age_seconds", "N/A")
                        self.logger.warning(
                            f"BUY_BLOCKED reason=GRADUATED_REAL_LTP_{price_status} "
                            f"symbol=NIFTY strike={_strike} option_type={_opt} "
                            f"premium_source={_best.get('premium_source', 'UNKNOWN')} "
                            f"age_seconds={_age} max_age_seconds={self.config.get_int('analysis.max_ltp_age_seconds', 15)}"
                        )

            if confidence.get("momentum_bonus", 0) > 0:
                recommendation["momentum_reason"] = confidence.get("momentum_reason", "")

            # 🌪️ VIX RISK FILTER (P0-4: tracker registration SE PEHLE)
            if vix:
                recommendation["vix"] = round(vix, 1)
                if recommendation["action"].startswith("BUY"):
                    if vix > 25:
                        recommendation["action"] = "NO_TRADE"
                        recommendation["reasons"] = [f"Extreme Volatility (VIX {round(vix,1)} > 25)"]
                    elif vix > 18:
                        recommendation["risk"] = "HIGH"
                        recommendation["reasons"] = list(recommendation.get("reasons", [])) + [f"High VIX {round(vix,1)} - strict SL"]
                    elif vix < 12:
                        recommendation["reasons"] = list(recommendation.get("reasons", [])) + [f"Low VIX {round(vix,1)} - theta risk, T1 exit"]

            # 🧠 SELF-LEARNING LOOP: track → analyze → auto-adjust
            spot_now = market_data.get("ltp", 0)
            self.tracker.update(spot_now)
            self.learner.review()
            if recommendation["action"].startswith("BUY"):
                ctx = analysis_results.get("trade_context", {})
                self.tracker.register(recommendation, spot_now, ctx.get("move30", 0), ctx.get("direction", ""))
                # 🔥 HIGH_VOLATILITY intraday: trade commit -> per-hour counter update
                try:
                    vm = getattr(self.decision_validator, "volatility_manager", None)
                    if vm is not None:
                        vm.register_trade()
                except Exception:
                    pass

            self.db.store_decision(recommendation)

            # 🔥 SIGNAL LOCK + FIX #8: Blocked WATCHLIST notify (owner only, no VIP spam)
            import time as _t
            buy_blocked = recommendation.get("buy_blocked", False)
            price_status = recommendation.get("price_status", "REAL")

            if recommendation["action"] != "NO_TRADE":
                key = recommendation["action"]
                now_ts = _t.time()

                # Blocked WATCHLIST: owner ko notify (VIP me nahi)
                if buy_blocked or price_status != "REAL":
                    if key != self.last_signal_key or (now_ts - self.last_signal_time) > 600:
                        self.telegram.send_recommendation(recommendation)
                        self.last_signal_key = key
                        self.last_signal_time = now_ts
                        recommendation["signal_status"] = f"⚠️ BLOCKED NOTIFY SENT (status={price_status})"
                        self.logger.info(f"⚠️ BLOCKED BUY: {key} | {recommendation.get('buy_blocked_reason')}")
                    else:
                        recommendation["signal_status"] = "🔒 BLOCKED SPAM GUARD"
                else:
                    # Normal BUY signal — 15 min lock
                    if key != self.last_signal_key or (now_ts - self.last_signal_time) > 900:
                        self.telegram.send_recommendation(recommendation)
                        self.last_signal_key = key
                        self.last_signal_time = now_ts
                        recommendation["signal_status"] = "🚀 NEW SIGNAL SENT TO TELEGRAM"
                        self.logger.info(f"🚀 NEW SIGNAL: {key} | Conf: {confidence['score']}%")
                    else:
                        recommendation["signal_status"] = "🔒 SIGNAL ACTIVE (repeat blocked - 15 min lock)"
            else:
                recommendation["signal_status"] = "🛡️ NO TRADE - Capital Protected"
            return {
                "recommendation": recommendation,
                "analysis_results": analysis_results,
                "ranked_strikes": ranked_strikes,
                "market_data": market_data
            }

        except Exception as e:
            self.logger.error(f"Analysis cycle error: {str(e)}")
            return None

    def run(self):
        self.running = True
        self.logger.info("BLOCKORA_TRADE started - entering main loop")

        # 🔥 Inform user if market is currently closed
        if not self.is_market_open():
            print("\n" + "="*60)
            print("  🛑 NSE MARKET IS CURRENTLY CLOSED")
            print("  ⏳ Market Hours: 09:15 AM to 03:30 PM")
            print("  💤 AI is in Standby Mode (Saving API & Battery)")
            print("="*60 + "\n")

        try:
            while self.running:
                if self.is_market_open():
                    if not self.market_open:
                        self.market_open = True
                        self.logger.info("Market OPENED - Starting analysis")
                        try:
                            self.telegram.send_system_status("MARKET OPEN", "Analysis started")
                        except Exception:
                            pass  # Telegram fail hone par script rukna nahi chahiye

                    # 🔒 TRADE LOCK: if trade is active, handle lock logic
                    if self.active_trade is not None:
                        ac = self.active_trade
                        strike = ac["strike"]
                        opt_type = ac["type"]
                        entry = ac["entry"]
                        sl = ac["sl"]
                        t1 = ac["t1"]
                        t2 = ac["t2"]
                        t3 = ac["t3"]
                        start_time = ac.get("start_time", 0)
                        now = datetime.now().timestamp()
                        age_sec = now - start_time
                        age_min = age_sec / 60.0
                        
                        # Get live LTP from existing option chain (no new API)
                        live_ltp = None
                        try:
                            oc = self.option_engine.get_option_chain(market_data)
                            if oc and opt_type == "CE" and strike in oc.get("ce_data", {}):
                                live_ltp = float(oc["ce_data"][strike].get("ltp", 0) or 0)
                            elif oc and opt_type == "PE" and strike in oc.get("pe_data", {}):
                                live_ltp = float(oc["pe_data"][strike].get("ltp", 0) or 0)
                        except Exception:
                            live_ltp = None
                        
                        # a. SL hit
                        if live_ltp is not None and live_ltp <= sl:
                            print("🛑 SL HIT - trade closed")
                            self.logger.info(f"TRADE LOCK CLOSED: SL hit strike={strike} type={opt_type} sl={sl} live={live_ltp}")
                            self.active_trade = None
                            # fall through to normal flow next cycle
                        # b. T3 hit
                        elif live_ltp is not None and live_ltp >= t3:
                            print("🎯 T3 HIT - trade closed")
                            self.logger.info(f"TRADE LOCK CLOSED: T3 hit strike={strike} type={opt_type} t3={t3} live={live_ltp}")
                            self.active_trade = None
                            # fall through to normal flow next cycle
                        # d. Timeout > 20 minutes
                        elif age_min > 20:
                            print("⏰ TIMEOUT - trade expired")
                            self.logger.info(f"TRADE LOCK CLOSED: Timeout strike={strike} type={opt_type} age={age_min:.1f}min")
                            self.active_trade = None
                            # fall through to normal flow next cycle
                        # e. Still locked - show locked panel, skip normal display
                        else:
                            pnl = float(live_ltp - entry) if live_ltp is not None else 0.0
                            pnl_str = f"{pnl:+.2f} pts"
                            live_str = f"₹{live_ltp:.2f}" if live_ltp is not None else "N/A"
                            print(f"  🔒 TRADE LOCKED: NIFTY {strike} {opt_type}")
                            print(f"  💰 Entry ₹{entry:.2f} | 📈 Live {live_str} | P&L: {pnl_str}")
                            print(f"  🛑 SL ₹{sl:.2f} | 🎯 T1 ₹{t1:.0f} | T2 ₹{t2:.0f} | T3 ₹{t3:.0f}")
                            print(f"  ⏱️ Running: {age_min:.0f} min | Unlock: SL hit / T3 hit / 20 min")
                            print(f"  (Book 50% at T1, 30% at T2, 20% at T3)")
                            # Skip normal analysis and display for this cycle
                            cycle_interval = self.config.get_int("analysis.cycle_interval_seconds", 60)
                            print(f"[💤 Next AI cycle in {cycle_interval} seconds...]")
                            threading.Event().wait(cycle_interval)
                            continue  # Skip to next iteration without clearing active_trade
                        
                        # If we reached here, trade was closed - continue to normal flow
                        # But we need to re-fetch market_data for the normal flow
                        # Actually, we already have market_data from the outer scope
                        # Just make sure we continue normally
                        pass
                    
                    # 🔥 LIVE HEARTBEAT: Taaki pata chale system zinda hai
                    print(f"\n[🔄 Cycle #{self.cycle_count + 1}] Fetching Live Data & Running 30+ AI Engines...")
                    
                    result = self.run_analysis_cycle()
                    
                    if result:
                        self.display_recommendation(
                            result["recommendation"], 
                            result["analysis_results"], 
                            result["ranked_strikes"], 
                            result["market_data"]
                        )

                    cycle_interval = self.config.get_int("analysis.cycle_interval_seconds", 60)
                    print(f"[💤 Next AI cycle in {cycle_interval} seconds...]")
                    threading.Event().wait(cycle_interval)
                else:
                    if self.market_open:
                        self.market_open = False
                        self.logger.info("Market CLOSED - Stopping analysis")
                    threading.Event().wait(60)

        except KeyboardInterrupt:
            pass
        except Exception as e:
            self.logger.error(f"Critical error in main loop: {str(e)}")
        finally:
            if self.running:
                self.shutdown()

    def display_recommendation(self, rec, analysis_results, ranked_strikes, market_data):
        """🧠 GENIUS-LEVEL BRAIN DASHBOARD - Full brain.md format (RECOMMENDATION ONLY)"""
        import time
        from data.strike_brain import (
            calculate_entry_price, calculate_stop_loss, calculate_targets,
            calculate_probabilities, make_decision,
            calculate_invalidation
        )
        
        spot = market_data.get('ltp', 0)
        ctx = analysis_results.get("trade_context", {})
        direction = str(ctx.get("direction", "NEUTRAL")).upper()
        indicators = analysis_results.get("indicators", {})
        
        # --- Determine BEST STRIKE ---
        _best_pe = ranked_strikes.get("best_pe") or {}
        _best_ce = ranked_strikes.get("best_ce") or {}
        if direction == "BEARISH":
            _best = _best_pe or _best_ce
        elif direction == "BULLISH":
            _best = _best_ce or _best_pe
        else:
            _best = _best_ce if (_best_ce.get("score", 0) >= _best_pe.get("score", 0)) else _best_pe
        
        _best_strike = _best.get("strike", "N/A")
        _best_type = _best.get("option_type", "PE" if direction == "BEARISH" else "CE")
        _final_score = _best.get("score", "N/A")
        _brain_conf = _best.get("brain_confidence", "N/A")
        _engine_score = _best.get("engine_score", "N/A")
        
        # Extract chain data for best strike
        opt_chain = analysis_results.get("option_chain", {})
        chain_data = opt_chain.get("pe_data" if _best_type == "PE" else "ce_data", {}).get(_best_strike, {})
        bid = float(chain_data.get("bid", 0) or 0)
        ask = float(chain_data.get("ask", 0) or 0)
        ltp = float(chain_data.get("ltp", 0) or 0)
        vol = float(chain_data.get("volume", 0) or 0)
        
        # --- Calculate using strike_brain ---
        if bid > 0 and ask > 0:
            entry = calculate_entry_price(bid, ask)
        else:
            entry = ltp if ltp > 0 else 0
            
        atr = market_data.get('atr', 12.5)
        
        sl = calculate_stop_loss(entry, atr, direction)
        t1, t2, t3 = calculate_targets(entry, atr, direction)
        
        # RR for decision
        rr = abs(t2 - entry) / abs(entry - sl) if entry != sl else 0
        
        # Confidence from final score
        confidence = _final_score if isinstance(_final_score, (int, float)) else 0
        
        # Probabilities
        iv_rank = ctx.get("iv_rank", 50)
        adx = float(indicators.get("adx", 15) or 15)
        t1_p, t2_p, t3_p = calculate_probabilities(confidence, iv_rank, adx)
        
        # Decision with RR grade cap
        action, grade, reason = make_decision(confidence, rr)
        
        # 🛡️ VALIDATOR OVERRIDE: if validator rejected, force WATCHLIST display
        if getattr(self, '_validator_rejected', False):
            action = "WATCHLIST"
            rec_reasons = rec.get("reasons", [])
            first_two = rec_reasons[:2] if rec_reasons else ["Validator block"]
            reason = f"🛑 VALIDATOR BLOCKED: {' | '.join(first_two)}"
        
        # 🔒 TRADE LOCK: if BUY decision, save active trade
        if action == "BUY" and not getattr(self, '_validator_rejected', False):
            self.active_trade = {
                "strike": _best_strike,
                "type": _best_type,
                "entry": entry,
                "sl": sl,
                "t1": t1,
                "t2": t2,
                "t3": t3,
                "start_time": datetime.now().timestamp()
            }
            self.logger.info(f"TRADE LOCK ACTIVATED: strike={_best_strike} type={_best_type} entry={entry} sl={sl}")
        
        # Invalidation
        vwap = float(ctx.get("vwap", spot) or spot)
        invalidation = calculate_invalidation(spot, vwap, atr, direction)
        
        # Factor scores for breakdown
        from data.strike_brain import (delta_score, iv_score, oi_score, 
            liquidity_score, technical_score, rr_score, candle_score)
        rsi = float(indicators.get("rsi", 50) or 50)
        macd_hist = float(indicators.get("macd_hist", 0) or 0)
        vwap_val = float(ctx.get("vwap", spot) or spot)
        oi_chg = float(chain_data.get("change_oi", 0) or 0)
        prev_oi = float(chain_data.get("prev_oi", 1) or 1)
        oi_change_pct = (oi_chg / prev_oi * 100) if prev_oi > 0 else 0
        spread_pct = ((ask - bid) / ltp * 100) if ltp > 0 and bid > 0 and ask > 0 else 5.0
        
        # Get REAL delta from chain data
        real_delta = chain_data.get("delta")
        if real_delta is None:
            delta_val = "N/A"
            delta_sc = "N/A"
        else:
            try:
                delta_val = float(real_delta)
                delta_sc = delta_score(delta_val)
            except (TypeError, ValueError):
                delta_val = "N/A"
                delta_sc = "N/A"
        
        # Get REAL candle pattern from analysis_results
        candle_pattern = "N/A"
        candle_at_key = False
        cs_data = analysis_results.get("candlestick", {})
        if isinstance(cs_data, dict):
            candle_pattern = cs_data.get("pattern", "N/A")
            candle_at_key = cs_data.get("at_key_level", False)
        candle_sc = candle_score(candle_pattern, candle_at_key) if candle_pattern != "N/A" else "N/A"
        
        factor_scores = {
            'Delta': delta_sc,
            'IV': iv_score(iv_rank),
            'OI': oi_score(oi_change_pct, direction, _best_type),
            'Liquidity': liquidity_score(vol, spread_pct),
            'Technical': round(technical_score(rsi, adx, spot, vwap_val, macd_hist, direction), 1),
            'Risk-Reward': rr_score(rr),
            'Candle': candle_sc
        }
        
        # For display
        delta_display = f"{delta_val:.2f}" if isinstance(delta_val, float) else str(delta_val)
        candle_display = str(candle_pattern)
        
        # --- BEST PICK HEADER ---
        print(f"\n{'═'*70}")
        print(f"  ⚡ SCALPING MODE | 7-POINT TARGET")
        print(f"  🎯 BEST PICK: NIFTY {_best_strike} {_best_type}")
        print(f"  ⚡ DECISION: {action} | {grade} | {reason}")
        print(f"  📊 Spot: {spot} | Time: {rec.get('time', time.strftime('%H:%M:%S'))}")
        print(f"  📈 Final Score: {_final_score}/100 | Brain: {_brain_conf:.1f}% | Engine: {_engine_score}/100")
        print(f"{'─'*70}")
        print(f"  💰 Entry: ₹{entry:.2f} | 🛑 SL: ₹{sl:.2f}")
        print(f"  🎯 T1: ₹{t1:.2f} ({t1_p}% probability) | Book 50%")
        print(f"  🎯 T2: ₹{t2:.2f} ({t2_p}% probability) | Book 30%")
        print(f"  🎯 T3: ₹{t3:.2f} ({t3_p}% probability) | Book 20%")
        print(f"  📊 Confidence: {confidence:.1f}% ({grade})")
        print(f"  📏 Risk-Reward: 1:{rr:.2f} | 📉 Move: {ctx.get('expected_move', 30):.0f} pts (30min)")
        print(f"{'─'*70}")
        print(f"  ✅ WHY {_best_strike} {_best_type}:")
        for fname, fscore in factor_scores.items():
            weight_map = {'Delta':20, 'IV':15, 'OI':15, 'Liquidity':10, 'Technical':20, 'Risk-Reward':10, 'Candle':10}
            if fname == 'Delta':
                print(f"      • Delta: {delta_display} → Score: {fscore}/10 (Weight: {weight_map.get(fname,0)}%)")
            elif fname == 'Candle':
                print(f"      • Candle: {candle_display} → Score: {fscore}/10 (Weight: {weight_map.get(fname,0)}%)")
            else:
                print(f"      • {fname}: {fscore}/10 (Weight: {weight_map.get(fname,0)}%)")
        print(f"{'─'*70}")
        
        # --- MARKET SNAPSHOT ---
        rsi_val = indicators.get("rsi", "N/A")
        adx_val = indicators.get("adx", "N/A")
        pcr_val = analysis_results.get("oi_analysis", {}).get("pcr", "N/A")
        vwap_val = ctx.get("vwap", "N/A")
        mtf = analysis_results.get("multi_timeframe", {})
        print(f"  📈 MARKET SNAPSHOT:")
        print(f"     RSI: {rsi_val} | ADX: {adx_val} | PCR: {pcr_val} | VWAP: {vwap_val}")
        print(f"     MTF: 5m {mtf.get('t5','N/A')} | 15m {mtf.get('t15','N/A')} | 1h {mtf.get('t1h','N/A')}")
        print(f"     Fear & Greed: {ctx.get('fear_greed', 'NEUTRAL')}")
        
        # --- TOP 3 STRIKES COMPARISON TABLE ---
        _ce_ranks = ranked_strikes.get("ce_rankings", [])[:3]
        _pe_ranks = ranked_strikes.get("pe_rankings", [])[:3]
        _strikes_to_show = _pe_ranks + _ce_ranks if direction == "BEARISH" else _ce_ranks + _pe_ranks
        
        print(f"\n  🏆 TOP 3 STRIKES:")
        print(f"  ┌─────────┬─────────┬────────┬──────┬───────┬───────┬─────────────────────┐")
        print(f"  │ Strike  │  Final  │  Brain │Engine│ LTP   │ IV    │ Key Reason          │")
        print(f"  ├─────────┼─────────┼────────┼──────┼───────┼───────┼─────────────────────┤")
        for s in _strikes_to_show[:3]:
            strike = s.get("strike", "N/A")
            final = s.get("score", "N/A")
            brain = s.get("brain_confidence", "N/A")
            engine = s.get("engine_score", "N/A")
            ltp_s = s.get("ltp", "N/A")
            iv_s = s.get("iv", "N/A")
            reasons = s.get("reasons", [])
            reason_short = reasons[0][:19] if reasons else "N/A"
            print(f"  │ {str(strike):>7} │ {str(final):>7} │ {str(brain):>6} │{str(engine):>5} │ {str(ltp_s):>4} │ {str(iv_s):>3}% │ {reason_short:<19} │")
        print(f"  └─────────┴─────────┴────────┴──────┴───────┴───────┴─────────────────────┘")
        
        # --- INVALIDATION ---
        print(f"\n  ⚠️ INVALIDATION:")
        print(f"     If NIFTY crosses {invalidation:.1f} → EXIT immediately")
        
        print(f"{'═'*70}")
        
        # --- Contract Intelligence ---
        from engines.ranking.contract_intelligence import snapshot_from_analysis
        snap = snapshot_from_analysis(
            analysis_results, ranked_strikes, market_data
        )
        ci = snap.get("contract_evidence", {})
        conv = snap.get("contract_conviction", {})
        print(f"── Intel: {snap.get('strike', '?')} {snap.get('option_type', '?')} ev {ci.get('evidence_score', 0)}/10 | {conv.get('conviction', 'UNAVAILABLE')}")
        self.logger.info(f"Contract Intelligence: strike={snap.get('strike')} type={snap.get('option_type')} evidence={ci.get('evidence_score')}/10 conviction={conv.get('conviction')} identity={snap.get('contract_identity')}")

        # --- Strike Continuity ---
        try:
            from engines.learning.strike_continuity import snapshot_from_analysis as continuity_snapshot
            c_snap = continuity_snapshot(analysis_results, ranked_strikes, market_data)
            same = c_snap.get("same_leader", True)
            curr = c_snap.get("current_strike", "?")
            prev = c_snap.get("previous_strike", "none")
            print(f"── Leader: {'same' if same else f'changed to {curr}'}")
            self.logger.info(f"Strike Continuity: same_leader={same} current={curr} previous={prev}")
        except Exception:
            pass
    def shutdown(self):
        self.running = False
        print("\n  Shutting down BLOCKORA_TRADE...")
        if hasattr(self, "sub_manager"):
            self.sub_manager.stop()
        shutdown_handler = SystemShutdown(self.config, self.logger)
        shutdown_handler.execute(
            market_engine=self.market_engine, option_engine=self.option_engine,
            db=self.db, telegram=self.telegram
        )
        print("  ✓ Shutdown complete\n")

    def signal_handler(self, signum, frame):
        if not self.running:
            return
        self.shutdown()
        sys.exit(0)


def main():
    app = BlockoraTrade()
    signal.signal(signal.SIGINT, app.signal_handler)
    signal.signal(signal.SIGTERM, app.signal_handler)
    if app.initialize():
        app.run()
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
