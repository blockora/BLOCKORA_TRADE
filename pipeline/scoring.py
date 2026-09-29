"""BLOCKORA_TRADE v3 — component score builders (Phase 4 glue).

Converts FeatureVectors + Regime into ComponentScore lists per family, then
uses core.signal_scorer.SignalScorer for group-aware aggregation (the
double-counting control lives THERE, not here).
"""
from __future__ import annotations

from typing import Any

from core.models import ComponentScore, Direction, FeatureVector, SideScore
from core.scoring_utils import (binary_score, delta_fit_score, rr_score,
                                threshold_score)
from core.signal_scorer import SignalScorer
from pipeline.regime import Regime

DIRECTIONAL_FAMILIES = ("trend", "market_structure", "option_chain",
                        "oi", "volume", "momentum")


def side_of(opt: str) -> str:
    return "CALL" if opt == "CE" else "PUT"


def build_directional_components(fv: FeatureVector, regime: Regime,
                                 pcr: float | None) -> list[ComponentScore]:
    """Directional evidence for the side this contract belongs to."""
    bull = fv.option_type == "CE"
    want = Direction.BULLISH if bull else Direction.BEARISH

    trend_align = (regime.mtf == want)
    mtf_score = 10.0 if trend_align else (5.0 if regime.mtf == Direction.RANGE else 0.0)

    return [
        ComponentScore("trend", "ema_stack",
                       binary_score(fv.trend_flag == ("BULLISH" if bull else "BEARISH"))),
        ComponentScore("trend", "adx",
                       threshold_score(regime.adx_15m or 0.0, good=25.0, bad=15.0)),
        ComponentScore("trend", "mtf_alignment", mtf_score),
        ComponentScore("market_structure", "htf_structure",
                       10.0 if regime.htf == want else (4.0 if regime.htf == Direction.RANGE else 0.0)),
        ComponentScore("market_structure", "swing_quality",
                       threshold_score(regime.adx_15m or 0.0, good=25.0, bad=10.0)),
        ComponentScore("option_chain", "pcr_skew",
                       threshold_score((pcr - 1.0) if bull else (1.0 - pcr),
                                       good=0.15, bad=-0.15) if pcr else None),
        ComponentScore("option_chain", "oi_wall_proximity",
                       binary_score(abs(fv.change_oi or 0) > 0 and
                                    ((fv.change_oi or 0) > 0) == bull, 7.0, 4.0)),
        ComponentScore("oi", "oi_change_direction",
                       binary_score((fv.change_oi or 0) > 0)),
        ComponentScore("oi", "buildup_class",
                       binary_score((fv.change_oi or 0) > 0 and fv.oi and fv.oi > 0, 8.0, 4.0)),
        ComponentScore("volume", "volume_expansion",
                       threshold_score(float(fv.volume or 0), good=20000.0, bad=1000.0)
                       if fv.volume is not None else None),
        ComponentScore("volume", "delta_proxy",
                       binary_score((fv.change_oi or 0) > 0 and bull or
                                    (fv.change_oi or 0) < 0 and not bull, 7.0, 4.0)),
        ComponentScore("momentum", "roc",
                       threshold_score((fv.momentum_5m or 0.0) if bull else -(fv.momentum_5m or 0.0),
                                       good=0.15, bad=-0.15) if fv.momentum_5m is not None else None),
        ComponentScore("momentum", "vwap_side",
                       binary_score(fv.vwap_rel == ("ABOVE" if bull else "BELOW"))),
        ComponentScore("momentum", "candle_body", 5.0),   # pattern witness slot, neutral w/o Phase 9
    ]


def build_strike_components(fv: FeatureVector, plan_rr: float | None) -> list[ComponentScore]:
    """Strike-fit + microstructure evidence for a specific contract."""
    comps = [
        ComponentScore("liquidity", "spread_score",
                       threshold_score(10.0 - (fv.spread_pct or 10.0), good=8.0, bad=0.0)
                       if fv.spread_pct is not None else None),
        ComponentScore("liquidity", "depth_score",
                       threshold_score(float(fv.volume or 0), good=20000.0, bad=1000.0)
                       if fv.volume is not None else None),
        ComponentScore("volatility", "iv_rank_fit",
                       threshold_score(10.0 - (fv.iv_rank or 5.0) / 10.0, good=8.0, bad=2.0)
                       if fv.iv_rank is not None else 6.0),
        ComponentScore("volatility", "atr_state",
                       8.0 if fv.volatility_state == "NORMAL" else
                       (3.0 if fv.volatility_state == "HIGH" else None)),
        ComponentScore("strike_quality", "delta_fit",
                       delta_fit_score(abs(fv.delta)) if fv.delta is not None else None),
        ComponentScore("strike_quality", "distance_atm_fit",
                       threshold_score(150.0 - abs(fv.distance_atm or 999.0),
                                       good=100.0, bad=-50.0)),
        ComponentScore("risk_reward", "rr_score",
                       rr_score(plan_rr) if plan_rr else None),
    ]
    return comps


def score_sides(features: list[FeatureVector], regime: Regime,
                pcr: float | None, scorer: SignalScorer,
                min_side_score: float, min_side_margin: float,
                min_coverage: float = 0.35) -> tuple[SideScore | None, SideScore | None,
                                                     dict[str, Any]]:
    """Stage 1: aggregate per-side evidence across candidate strikes.

    Returns (best_call, best_put, diagnostics). A side is valid only if
    score >= min_side_score and margin over the other side >= min_side_margin.
    """
    diag: dict[str, Any] = {"sides": {}}
    best: dict[str, SideScore] = {}
    for side in ("CALL", "PUT"):
        pool = [f for f in features if side_of(f.option_type) == side]
        if not pool:
            continue
        # side evidence = best candidate of the side (its directional evidence)
        scored: list[tuple[float, FeatureVector, dict]] = []
        for fv in pool:
            comps = build_directional_components(fv, regime, pcr)
            s, audit = scorer.score(comps)
            scored.append((s, fv, audit))
        scored.sort(key=lambda t: t[0], reverse=True)
        s, fv, audit = scored[0]
        best[side] = SideScore(side=side, score=s, valid=False,
                               reasons=[f"best candidate {int(fv.strike)} {fv.option_type}"],
                               contributing=audit)
        diag["sides"][side] = {
            "score": s, "candidates": len(pool),
            "top": f"{int(fv.strike)} {fv.option_type}",
            "coverage": audit.get("coverage"),
        }

    call, put = best.get("CALL"), best.get("PUT")
    if call and put:
        call.valid = (call.score >= min_side_score and
                      call.score - put.score >= min_side_margin)
        put.valid = (put.score >= min_side_score and
                     put.score - call.score >= min_side_margin)
        # coverage gate on the winning side
        for ss in (call, put):
            if ss.valid and ss.contributing.get("coverage", 0) < min_coverage:
                ss.valid = False
                ss.reasons.append("coverage below minimum")
    elif call:
        call.valid = call.score >= min_side_score
    elif put:
        put.valid = put.score >= min_side_score
    return call, put, diag
