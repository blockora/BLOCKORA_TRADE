"""BLOCKORA_TRADE v3 — master decision engine (Phases 2–5 wiring).

Full cycle: data -> validation -> features -> regime -> side scoring ->
strike scoring -> risk plan -> hard filters -> ranking -> decision.
NO_TRADE is a first-class outcome; the engine can always return it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from core.models import (Decision, Direction, FeatureVector, OptionQuote,
                         Recommendation, TradePlan, UnderlyingTick)
from core.scoring_utils import rr_score, threshold_score
from core.signal_scorer import SignalScorer
from core.session import now_ist
from pipeline.data_sources import strikes_around_atm
from pipeline.features import build_features
from pipeline.hard_filters import FilterContext, HardFilterEngine
from pipeline.regime import Regime, classify
from pipeline.risk import build_plan
from pipeline.scoring import (build_directional_components,
                              build_strike_components, score_sides, side_of)

PROTOCOLS = ("BrokerSource", "ChainSource")


def _closed_bars_only(candles: list, decision_ts: datetime) -> list:
    """Defense-in-depth: drop bars whose close is after the decision instant.

    Live adapters must only return closed bars; this guard makes the no-
    look-ahead rule structural (docs/SCHEMA.md: ingestion refuses bars whose
    close is in the future) instead of an adapter promise.
    """
    from datetime import timedelta
    out = []
    for c in candles:
        try:
            bar_open = datetime.fromisoformat(c.bar_ts)
            tf = str(c.timeframe)
            unit = tf[-1]
            n = int(tf[:-1])
            dur = {"m": timedelta(minutes=n), "h": timedelta(hours=n),
                   "d": timedelta(days=n), "s": timedelta(seconds=n)}[unit]
        except (ValueError, KeyError, IndexError, TypeError):
            continue                       # unparsable metadata -> drop, never trust
        if bar_open.tzinfo is None:
            # schema contract: naive bar_ts means UTC (docs/SCHEMA.md)
            from datetime import timezone as _tz
            bar_open = bar_open.replace(tzinfo=_tz.utc)
        if decision_ts.tzinfo is None:
            decision_ts = decision_ts.replace(tzinfo=bar_open.tzinfo)
        if bar_open + dur <= decision_ts:
            out.append(c)
    return out


class MarketDataSource:
    """Minimal composed source: what the engine needs each cycle."""

    def __init__(self, broker, chain) -> None:
        self.broker = broker
        self.chain = chain

    def is_healthy(self) -> bool:
        return self.broker.is_healthy() and self.chain.is_healthy()


class DecisionEngine:
    def __init__(self, config, source: MarketDataSource,
                 calibrator=None, stats_provider=None) -> None:
        self.cfg = config
        self.source = source
        self.scorer = SignalScorer(config.weights)
        self.filters = HardFilterEngine(config.filters)
        self.calibrator = calibrator          # Phase 8; None -> UNAVAILABLE
        # stats_provider: callable -> {trades_today, consecutive_losses,
        # daily_loss_pct} for circuit breakers (wired from the DB in
        # run_cycle.py; None keeps stats at 0 = no history).
        self.stats_provider = stats_provider
        self._recent_keys: dict[str, datetime] = {}
        self._iv_history: list[float] = []

    def _prune_dedup_keys(self, ts: datetime) -> None:
        """Honor filters.yaml dedup.window_min — keys older than the window
        no longer block (pre-fix: keys lived forever = dead config)."""
        window_min = float(self.cfg.get("filters.dedup.window_min", 30))
        cutoff = ts.timestamp() - window_min * 60.0
        self._recent_keys = {
            k: t for k, t in self._recent_keys.items()
            if t.timestamp() >= cutoff
        }

    def _circuit_stats(self) -> dict[str, float]:
        base = {"trades_today": 0, "consecutive_losses": 0,
                "daily_loss_pct": 0.0}
        if self.stats_provider is None:
            return base
        try:
            got = self.stats_provider() or {}
            base.update({k: float(got.get(k, 0) or 0) for k in base})
        except Exception:
            # Stats must never crash a cycle; but an ERROR here must not
            # silently PASS circuit breakers either — fail closed on the
            # trades/day cap so a broken stats source cannot bypass limits.
            base["trades_today"] = self.cfg.get(
                "filters.circuit_breakers.max_trades_per_day", 2)
        return base

    # ------------------------------------------------------------------
    def run_cycle(self, now: datetime | None = None) -> Recommendation:
        ts = now_ist(now)
        source = self.source
        if not source.is_healthy():
            return self._no_trade(ts, "F2_source", "data source unhealthy")

        tick = source.broker.get_underlying_tick("NIFTY")
        if tick.ltp is None or tick.ltp <= 0:
            return self._no_trade(ts, "F4_missing", "underlying LTP missing")

        candles_5m = _closed_bars_only(source.broker.get_candles("NIFTY", "5m", 220), ts)
        candles_15m = _closed_bars_only(source.broker.get_candles("NIFTY", "15m", 220), ts)
        candles_1h = _closed_bars_only(source.broker.get_candles("NIFTY", "1h", 220), ts)

        regime = classify(candles_1h, candles_15m, candles_5m)

        strikes = strikes_around_atm(
            tick.ltp, self.cfg.get("settings.market.strike_step", 50),
            self.cfg.get("filters.contract.strike_window_atm", 3))
        expiry = self.cfg.get("settings.market.expiry_policy", "NEXT_WEEKLY")
        quotes: list[OptionQuote] = source.chain.get_chain(expiry, strikes)
        if not quotes:
            return self._no_trade(ts, "F4_missing", "empty option chain")

        atm = round(tick.ltp / 50) * 50
        features = build_features(tick, candles_5m, quotes, atm, dte_days=6.0,
                                  iv_history=self._iv_history or None)

        # PCR from chain OI (CALCULATED; None if impossible)
        tot_ce = sum(q.oi or 0 for q in quotes if q.option_type == "CE")
        tot_pe = sum(q.oi or 0 for q in quotes if q.option_type == "PE")
        pcr = round(tot_pe / tot_ce, 3) if tot_ce else None

        return self._decide(ts, tick, candles_5m, features, regime, pcr, expiry)

    # ------------------------------------------------------------------
    def _decide(self, ts, tick, candles_5m, features, regime: Regime,
                pcr, expiry) -> Recommendation:
        from pipeline import indicators as ind
        underlying_atr = ind.atr(candles_5m, 14)

        # ---- Stage 1: sides
        sg = self.cfg.get("weights.side_gate", {})
        call, put, diag = score_sides(
            features, regime, pcr, self.scorer,
            min_side_score=sg.get("min_side_score", 55.0),
            min_side_margin=sg.get("min_side_margin", 10.0))
        valid = call if (call and call.valid) else (put if (put and put.valid) else None)
        if valid is None:
            return self._no_trade(ts, "no_side",
                                  f"no valid side (CALL {call.score if call else '—'} / "
                                  f"PUT {put.score if put else '—'})",
                                  regime=regime, diag=diag)

        # ---- Stage 2: rank candidates on the valid side
        side_pool = [f for f in features if side_of(f.option_type) == valid.side]
        ranked: list[tuple[float, FeatureVector, TradePlan | None, dict, int]] = []
        for fv in side_pool:
            plan = build_plan(
                fv, underlying_atr,
                sl_mult=self.cfg.get("filters.risk.atr_multiplier_sl", 1.5),
                t1_mult=self.cfg.get("filters.risk.atr_multiplier_t1", 1.0),
                t2_mult=self.cfg.get("filters.risk.atr_multiplier_t2", 2.0),
                t3_mult=self.cfg.get("filters.risk.atr_multiplier_t3", 3.0),
                slippage_fraction=self.cfg.get("filters.entry.slippage_fraction_of_spread", 0.25),
                max_hold_bars=self.cfg.get("settings.timeframes.max_hold_bars", 24))
            strike_comps = build_strike_components(fv, plan.reward_risk if plan else None)
            s, audit = self.scorer.score(strike_comps + build_directional_components(fv, regime, pcr))
            ranked.append((s, fv, plan, audit, audit["unavailable_components"]))
        ranked.sort(key=lambda t: t[0], reverse=True)

        if not ranked:
            return self._no_trade(ts, "no_candidate", "no candidates on valid side",
                                  regime=regime, diag=diag)

        # ---- candidate filters (top first)
        rejected: list[str] = []
        chain_age = 1.0  # adapters are responsible for true freshness in live mode
        self._prune_dedup_keys(ts)
        stats = self._circuit_stats()
        ctx = FilterContext(
            now=ts, tick=tick, underlying_quality=tick.quality,
            chain_age_s=chain_age, source_healthy=True,
            feature_count=len(features), regime_classification=regime.classification,
            recent_signal_keys=set(self._recent_keys),
            trades_today=int(stats["trades_today"]),
            consecutive_losses=int(stats["consecutive_losses"]),
            daily_loss_pct=stats["daily_loss_pct"])
        for s, fv, plan, audit, n_unavail in ranked:
            ctx.unavailable_components = n_unavail
            ok, fails = self.filters.evaluate(fv, plan, ctx)
            if ok and plan is not None:
                return self._recommend(ts, regime, valid, fv, plan, s, audit,
                                       rejected, diag, expiry)
            rejected.extend(f"{int(fv.strike)} {fv.option_type}: {fid} {why}"
                            for fid, why in fails)

        return self._no_trade(ts, "filter_veto",
                              "all candidates rejected by hard filters: "
                              + "; ".join(rejected[:4]),
                              regime=regime, diag=diag)

    # ------------------------------------------------------------------
    def _recommend(self, ts, regime, side_score, fv: FeatureVector,
                   plan: TradePlan, score, audit, rejected, diag, expiry) -> Recommendation:
        calibrated, state = None, "UNAVAILABLE"
        if self.calibrator is not None:
            calibrated, state = self.calibrator.confidence(score, regime.classification)
        grade = self._grade(score)
        bias = regime.market_bias
        rec = Recommendation(
            decision=Decision.RECOMMENDATION, decision_ts=ts.isoformat(),
            market_bias=bias, side=side_score.side, strike=fv.strike, expiry=expiry,
            plan=plan, model_score=score, calibrated_confidence=calibrated,
            calibrated_state=state, trade_grade=grade,
            key_reasons=self._key_reasons(fv, regime, side_score),
            rejected_alternatives=rejected[:5],
            diagnostics={
                "regime": {"htf": regime.htf.value, "mtf": regime.mtf.value,
                           "ltf": regime.ltf.value, "class": regime.classification,
                           "notes": regime.notes},
                "score_audit": audit, "side_scores": diag["sides"],
                "iv": fv.iv, "spread_pct": fv.spread_pct, "delta": fv.delta,
            })
        self._recent_keys[f"{int(fv.strike)}_{fv.option_type}_{expiry}"] = ts
        if fv.iv:
            self._iv_history.append(fv.iv)
        return rec

    def _no_trade(self, ts, reason_code: str, detail: str,
                  regime: Regime | None = None,
                  diag: dict | None = None) -> Recommendation:
        return Recommendation(
            decision=Decision.NO_TRADE, decision_ts=ts.isoformat(),
            no_trade_reason=f"{reason_code}: {detail}",
            market_bias=regime.market_bias if regime else None,
            diagnostics={"side_scores": (diag or {}).get("sides", {}),
                         "regime": ({"class": regime.classification}
                                    if regime else {})})

    @staticmethod
    def _grade(score: float) -> str:
        # Grade labels describe SCORE BANDS only — never probability claims.
        if score >= 80:
            return "A"
        if score >= 70:
            return "B"
        if score >= 60:
            return "C"
        return "D"

    @staticmethod
    def _key_reasons(fv: FeatureVector, regime: Regime, side) -> list[str]:
        reasons = [f"{regime.classification} regime (HTF {regime.htf.value}/MTF {regime.mtf.value})"]
        if fv.trend_flag:
            reasons.append(f"EMA stack {fv.trend_flag}")
        if fv.vwap_rel:
            reasons.append(f"price {'above' if fv.vwap_rel == 'ABOVE' else 'below'} VWAP")
        if fv.change_oi:
            reasons.append(f"OI change {fv.change_oi:+d} on {int(fv.strike)} {fv.option_type}")
        if fv.delta is not None:
            reasons.append(f"delta {fv.delta:.2f}")
        return reasons
