"""BLOCKORA_TRADE v3 — hard filter engine (Phase 5 part 2).

Binary vetoes; any FAIL means NO_TRADE regardless of score. Filter ids and
rules follow docs/FILTERS.md section 3; thresholds come from config/filters.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.models import DataQuality, FeatureVector, Quality, TradePlan, UnderlyingTick


@dataclass
class FilterContext:
    now: datetime
    tick: UnderlyingTick
    underlying_quality: DataQuality
    chain_age_s: float
    source_healthy: bool
    feature_count: int
    regime_classification: str
    unavailable_components: int = 0
    recent_signal_keys: set[str] = field(default_factory=set)
    trades_today: int = 0
    consecutive_losses: int = 0
    daily_loss_pct: float = 0.0
    vix: float | None = None


class HardFilterEngine:
    def __init__(self, filters_cfg: dict[str, Any]) -> None:
        self.cfg = filters_cfg

    # ------------------------------------------------------------------
    def evaluate(self, fv: FeatureVector, plan: TradePlan | None,
                 ctx: FilterContext) -> tuple[bool, list[tuple[str, str]]]:
        """Return (all_pass, [(filter_id, reason), ...]) for one candidate."""
        results: list[tuple[str, str]] = []
        ok = True

        def fail(fid: str, reason: str) -> None:
            nonlocal ok
            ok = False
            results.append((fid, reason))

        # F1 session
        from core.session import is_market_open
        s = self.cfg["session"]
        if not is_market_open(ctx.now, s["market_open"], s["market_close"],
                              tuple(s["days"])):
            fail("F1_session", "market closed")

        # F2 source health
        if not ctx.source_healthy:
            fail("F2_source", "source unhealthy")

        # F3/F15 freshness
        dq = self.cfg["data_quality"]
        uq = ctx.underlying_quality
        if uq.latency_ms is not None and uq.latency_ms > dq["max_latency_ms"]:
            fail("F3_latency", f"latency {uq.latency_ms}ms")
        if ctx.chain_age_s > dq["max_chain_age_s"]:
            fail("F15_chain_age", f"chain age {ctx.chain_age_s:.1f}s")
        if uq.status == Quality.STALE:
            fail("F3_stale", "underlying data stale")

        # F4 critical completeness (underlying + this quote)
        for name, val in (("spot", ctx.tick.ltp), ("ltp", fv.ltp),
                          ("bid", fv.bid), ("ask", fv.ask)):
            if val is None or val <= 0:
                fail("F4_missing", f"critical field {name} missing")

        # F5 spread
        liq = self.cfg["liquidity"]
        if fv.spread_pct is None:
            fail("F5_spread", "spread unknown (missing bid/ask)")
        elif fv.spread_pct > liq["max_spread_pct"]:
            fail("F5_spread", f"spread {fv.spread_pct:.2f}% > {liq['max_spread_pct']}%")

        # F6 liquidity
        if fv.volume is None or fv.volume < liq["min_volume"]:
            fail("F6_liquidity", f"volume {fv.volume} < {liq['min_volume']}")
        if fv.oi is None or fv.oi < liq["min_oi"]:
            fail("F6_liquidity", f"OI {fv.oi} < {liq['min_oi']}")

        # F7 entry sanity
        if plan is None:
            fail("F7_plan", "no valid trade plan (bad data or ATR unavailable)")
        else:
            dev = abs(plan.entry - fv.ltp) / fv.ltp * 100.0
            if dev > self.cfg["entry"]["max_entry_deviation_pct"]:
                fail("F7_entry", f"entry deviation {dev:.1f}%")
            if not (fv.bid <= plan.entry <= fv.ask + 0.5):
                fail("F7_entry", "entry outside bid/ask band")

        # F8 score completeness (set by caller)
        if ctx.unavailable_components > dq["max_unavailable_components"]:
            fail("F8_score", f"{ctx.unavailable_components} unavailable components")

        # F9 volatility sanity
        vol = self.cfg["volatility"]
        if fv.iv is not None and not (vol["min_iv"] <= fv.iv <= vol["max_iv"]):
            fail("F9_iv", f"IV {fv.iv} outside [{vol['min_iv']}, {vol['max_iv']}]")
        if fv.iv_rank is not None and fv.iv_rank > vol["max_iv_rank"]:
            fail("F9_iv_rank", f"IV rank {fv.iv_rank:.0f} > {vol['max_iv_rank']}")
        if ctx.vix is not None and ctx.vix > 25.0:
            fail("F9_vix", f"VIX {ctx.vix} > 25")

        # F10 risk/reward
        risk_cfg = self.cfg["risk"]
        if plan is not None:
            if plan.reward_risk is None or plan.reward_risk < risk_cfg["min_rr"]:
                fail("F10_rr", f"R:R {plan.reward_risk} < {risk_cfg['min_rr']}")

        # F12 regime
        if ctx.regime_classification not in self.cfg["regime"]["allowed_classifications"]:
            fail("F12_regime", f"regime {ctx.regime_classification}")

        # F14 duplicates / daily caps
        key = f"{int(fv.strike)}_{fv.option_type}_{fv.expiry}"
        dd = self.cfg["dedup"]
        if key in ctx.recent_signal_keys:
            fail("F14_duplicate", f"{key} signalled within dedup window")
        if ctx.trades_today >= dd["max_signals_per_day"]:
            fail("F14_daily_cap", "max signals per day reached")

        # circuit breakers
        cb = self.cfg["circuit_breakers"]
        if ctx.trades_today >= cb["max_trades_per_day"]:
            fail("CB_trades", "max trades/day")
        if ctx.consecutive_losses >= cb["max_consecutive_losses"]:
            fail("CB_losses", "consecutive loss limit")
        if ctx.daily_loss_pct >= cb["max_daily_loss_pct"]:
            fail("CB_daily_loss", "daily loss limit")

        return ok, results
