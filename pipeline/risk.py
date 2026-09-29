"""BLOCKORA_TRADE v3 — risk engine (Phase 5 part 1).

Computes entry/SL/T1–T3 for long options per docs/ASSUMPTIONS.md C-1/C-2:
  entry = mid + slippage_fraction*spread (rounded to 0.05)
  SL    = entry - atr_mult_sl * atr_prem
  T1..3 = entry + atr_mult_tN * atr_prem
All levels are on the option PREMIUM (both directions up: long option).
"""
from __future__ import annotations

from core.models import FeatureVector, TradePlan
from core.scoring_utils import round_tick


def estimate_premium_atr(fv: FeatureVector, underlying_atr: float) -> float | None:
    """Premium ATR approximation from underlying ATR + delta (HEURISTIC).

    Option premium range ≈ underlying range × |delta|. Floor at 0.4 to avoid
    microscopic stops on far-OTM contracts.
    """
    if not underlying_atr or fv.delta is None or not fv.ltp:
        return None
    return max(abs(fv.delta) * underlying_atr, 0.4)


def build_plan(fv: FeatureVector, underlying_atr: float | None,
               sl_mult: float, t1_mult: float, t2_mult: float, t3_mult: float,
               slippage_fraction: float = 0.25,
               max_hold_bars: int = 24, bar_minutes: int = 5) -> TradePlan | None:
    if fv.bid is None or fv.ask is None or fv.ltp is None or fv.ltp <= 0:
        return None
    if fv.bid <= 0 or fv.ask < fv.bid:
        return None
    atr_prem = estimate_premium_atr(fv, underlying_atr) if underlying_atr else None
    if not atr_prem:
        return None
    mid = (fv.bid + fv.ask) / 2.0
    spread = fv.ask - fv.bid
    entry = round_tick(mid + slippage_fraction * spread)
    sl = round_tick(entry - sl_mult * atr_prem)
    t1 = round_tick(entry + t1_mult * atr_prem)
    t2 = round_tick(entry + t2_mult * atr_prem)
    t3 = round_tick(entry + t3_mult * atr_prem)
    if sl <= 0 or t1 <= entry:
        return None
    risk = entry - sl
    reward = t1 - entry
    rr = round(reward / risk, 2) if risk > 0 else None
    # Book-ladder expectancy R:R per the spec's output format (50% T1, 30% T2,
    # 20% T3): this is the reward the plan actually targets (docs/ASSUMPTIONS.md C-6).
    ladder_reward = 0.5 * (t1 - entry) + 0.3 * (t2 - entry) + 0.2 * (t3 - entry)
    ladder_rr = round(ladder_reward / risk, 2) if risk > 0 else None
    return TradePlan(
        entry=entry, stop_loss=sl, t1=t1, t2=t2, t3=t3,
        risk_pct=None, reward_risk=ladder_rr,
        expected_hold_min=max_hold_bars * bar_minutes,
    )
