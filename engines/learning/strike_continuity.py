"""Strike Continuity + Change Intelligence — Phase 22.

Deterministic comparison of successive analysis cycles.
Pure evidence layer — does NOT modify ranking, scores, strikes, or winner selection.

Current live ranking ALWAYS wins. Continuity is informational only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Snapshot of a completed ranking cycle
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RankingSnapshot:
    """Immutable snapshot of a completed analysis cycle's ranking."""

    timestamp: str = ""
    spot: float = 0.0
    direction: str = ""
    option_type: str = ""
    expiry: str = ""
    strike: float = 0.0
    baseline_score: float = 0.0
    enhanced_score: float = 0.0
    move_fit: float = 0.0
    score_margin: float = 0.0
    top_3_strikes: Tuple[float, ...] = field(default_factory=lambda: ())
    top_3_scores: Tuple[float, ...] = field(default_factory=lambda: ())
    # Relevant ranking components (named for display; values from engine)
    distance_score: float = 0.0
    move_fit_score: float = 0.0
    trend_score: float = 0.0
    indicators_score: float = 0.0
    structure_score: float = 0.0
    oi_score: float = 0.0
    liquidity_score: float = 0.0
    quality_score: float = 0.0
    enhanced_move_fit: float = 0.0
    ltp: float = 0.0
    ltp_timestamp: str = ""
    data_quality: str = "UNAVAILABLE"


# ---------------------------------------------------------------------------
# Strike continuity report
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrikeContinuityReport:
    """Read-only report from a continuity comparison."""

    strike_change: bool = False
    previous_leader: Optional[float] = None
    current_leader: float = 0.0
    score_changes: Dict[float, float] = field(default_factory=dict)
    new_leader_margin: float = 0.0
    status: str = "FIRST_CYCLE"
    top_3_changes: List[str] = field(default_factory=list)
    leadership_info: str = "FIRST LIVE CYCLE"
    reasons: List[str] = field(default_factory=list)
    material_change: bool = False
    score_delta: float = 0.0


# ---------------------------------------------------------------------------
# Strike continuity tracker state (in-memory, process lifetime only)
# ---------------------------------------------------------------------------

class StrikeContinuityTracker:
    """Tracks strike leadership across successive analysis cycles.

    Responsibilities:
    - remember the previous completed ranking snapshot
    - compare previous vs current ranking
    - identify leader persistence/change
    - calculate score deltas
    - identify meaningful component changes
    - generate transparent change reasons
    - track consecutive leadership

    CRITICAL: Current live ranking ALWAYS wins. This tracker only reports.
    """

    # Module-level persistent state (reset on process restart)
    _previous: Optional[RankingSnapshot] = None
    _consecutive_leader_cycles: int = 0
    _leadership_history: List[str] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------------
    # Snapshot management
    # ------------------------------------------------------------------

    @classmethod
    def save_previous(cls, snapshot: RankingSnapshot) -> None:
        """Call AFTER a successful analysis cycle to store the previous state."""
        cls._previous = snapshot
        # Reset consecutive counter when a new snapshot is saved
        # (it will be recalculated on next comparison)
        cls._consecutive_leader_cycles = 0
        cls._leadership_history = []

    @classmethod
    def clear_previous(cls) -> None:
        """Reset previous snapshot (e.g. new trading day)."""
        cls._previous = None
        cls._consecutive_leader_cycles = 0
        cls._leadership_history = []

    @classmethod
    def get_previous(cls) -> Optional[RankingSnapshot]:
        return cls._previous

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    @classmethod
    def compare(
        cls, current: RankingSnapshot, previous: Optional[RankingSnapshot] = None
    ) -> StrikeContinuityReport:
        """Compare current vs previous ranking and produce a report."""
        prev = previous or cls._previous
        # Always construct report with ALL required args
        if prev is None:
            return StrikeContinuityReport(
                strike_change=False,
                previous_leader=None,
                current_leader=current.strike,
                score_changes={},
                new_leader_margin=0.0,
                status="FIRST_CYCLE",
                top_3_changes=[],
                leadership_info="FIRST LIVE CYCLE",
                reasons=[],
                material_change=False,
                score_delta=0.0,
            )

        # Compute deltas
        prev_enhanced = prev.enhanced_score
        cur_enhanced = current.enhanced_score
        delta = round(cur_enhanced - prev_enhanced, 2)

        # Top-3 changes
        top_3_changes = cls._compute_top_3_changes(
            prev.top_3_strikes, prev.top_3_scores,
            current.top_3_strikes, current.top_3_scores,
        )

        # Leadership info
        leadership_info = cls._compute_leadership_info(current.strike, prev.strike)

        # Reasons (only real component changes)
        reasons = cls._compute_reasons(prev, current)

        # Material change threshold: delta >= 3 points
        material_change = abs(delta) >= 3

        # Status determination
        if not prev.strike or not prev.enhanced_score:
            status = "FIRST_CYCLE"
        elif not (
            prev.strike != current.strike
            or abs(delta) >= 3
        ):
            status = "SAME_LEADER"
        elif abs(delta) < 5:
            status = "FAIR_LEADER"
        elif abs(delta) < 10:
            status = "CLEAR_LEADER"
        else:
            status = "CLEAR_LEADER"

        # New leader margin: current cycle's score_margin when strike changes
        if prev.strike != current.strike:
            new_leader_margin = current.score_margin
        else:
            new_leader_margin = 0.0

        return StrikeContinuityReport(
            strike_change=prev.strike != current.strike,
            previous_leader=prev.strike,
            current_leader=current.strike,
            score_changes={prev.strike: delta},
            new_leader_margin=new_leader_margin,
            status=status,
            top_3_changes=top_3_changes,
            leadership_info=leadership_info,
            reasons=reasons,
            material_change=material_change,
            score_delta=delta,
        )

    # ------------------------------------------------------------------
    # Top-3 change computation
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_top_3_changes(
        prev_strikes: Tuple[float, ...],
        prev_scores: Tuple[float, ...],
        cur_strikes: Tuple[float, ...],
        cur_scores: Tuple[float, ...],
    ) -> List[str]:
        changes: List[str] = []
        prev_map = dict(zip(prev_strikes, prev_scores)) if prev_strikes else {}
        cur_map = dict(zip(cur_strikes, cur_scores)) if cur_strikes else {}
        all_strikes = sorted(set(list(prev_map.keys()) + list(cur_map.keys())))

        prev_ranked = sorted(prev_map.items(), key=lambda x: x[1], reverse=True) if prev_map else []
        cur_ranked = sorted(cur_map.items(), key=lambda x: x[1], reverse=True) if cur_map else []

        prev_pos = {strike: i + 1 for i, (strike, _) in enumerate(prev_ranked)}
        cur_pos = {strike: i + 1 for i, (strike, _) in enumerate(cur_ranked)}

        for strike in all_strikes:
            p = prev_pos.get(strike)
            c = cur_pos.get(strike)
            if p is None and c is None:
                continue
            if p is None:
                changes.append(f"{strike}: #N/A → #{c}")
            elif c is None:
                changes.append(f"{strike}: #{p} → #N/A")
            elif p == c:
                changes.append(f"{strike}: = #{c}")
            elif p < c:
                changes.append(f"{strike}: #{p} → #{c}")
            else:
                changes.append(f"{strike}: #{p} → #{c}")

        return changes[:3]

    # ------------------------------------------------------------------
    # Reasons (only real component changes)
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_reasons(prev: RankingSnapshot, current: RankingSnapshot) -> List[str]:
        reasons: List[str] = []

        def _diff(name: str, prev_val: float, cur_val: float) -> Optional[str]:
            if prev_val == cur_val:
                return None
            return f"{name} changed"

        # Distance/moneyness
        if prev.distance_score != current.distance_score:
            reasons.append("distance/moneyness score improved")

        # Expected-move fit
        if prev.move_fit_score != current.move_fit_score:
            reasons.append("expected-move fit improved")

        # Trend alignment
        if prev.trend_score != current.trend_score:
            reasons.append("trend alignment improved")

        # Indicators
        if prev.indicators_score != current.indicators_score:
            reasons.append("indicator score improved")

        # Structure
        if prev.structure_score != current.structure_score:
            reasons.append("structure score improved")

        # OI quality
        if prev.oi_score != current.oi_score:
            reasons.append("OI quality improved")

        # Liquidity
        if prev.liquidity_score != current.liquidity_score:
            reasons.append("liquidity score improved")

        # Quality
        if prev.quality_score != current.quality_score:
            reasons.append("quality score improved")

        # Enhanced move-fit
        if prev.enhanced_move_fit != current.enhanced_move_fit:
            reasons.append("enhanced move-fit improved")

        # LTP change
        if prev.ltp != current.ltp or prev.ltp_timestamp != current.ltp_timestamp:
            reasons.append("current LTP changed")

        # Spot moved relative to strike
        if prev.spot != current.spot:
            reasons.append("spot moved relative to strike")

        # Score margin changed
        if prev.score_margin != current.score_margin:
            reasons.append("score margin changed")

        return reasons

    # ------------------------------------------------------------------
    # Leadership info
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_leadership_info(new_strike: float, prev_strike: float) -> str:
        if prev_strike is None or prev_strike == new_strike:
            return f"{new_strike}: CONSECUTIVE LEADER"
        return f"{new_strike}: LEADER CHANGED from {prev_strike}"


# ---------------------------------------------------------------------------
# Convenience integration helpers for main.py
# ---------------------------------------------------------------------------

def snapshot_from_analysis(
    analysis_results: Dict[str, object],
    ranked_strikes: Dict[str, object],
    market_data: Dict[str, object],
) -> RankingSnapshot:
    """Build a RankingSnapshot from the just-completed analysis cycle.

    This is called AFTER the ranking engine has decided and the cycle is
    complete. It does NOT influence the current ranking.
    """
    # Best strike (whichever the engine picked)
    best_ce = ranked_strikes.get("best_ce", {})
    best_pe = ranked_strikes.get("best_pe", {})

    direction = str(analysis_results.get("trade_context", {}).get("direction", "")).upper()

    if direction == "BEARISH" and best_pe:
        best_strike_data = best_pe
    elif direction == "BULLISH" and best_ce:
        best_strike_data = best_ce
    else:
        # NEUTRAL fallback: pick the side with the higher score
        _ce_score = float(best_ce.get("score", 0) or 0)
        _pe_score = float(best_pe.get("score", 0) or 0)
        if best_pe and _pe_score > _ce_score:
            best_strike_data = best_pe
        else:
            best_strike_data = best_ce or best_pe or {}

    # FIX B: option_type winner se derive karo (trade_context default "PE" NAHI)
    opt_type = str(best_strike_data.get("option_type", "") or "").upper()
    if opt_type not in ("CE", "PE"):
        opt_type = "PE" if best_strike_data is best_pe else "CE"

    strike = best_strike_data.get("strike", 0.0)
    baseline = best_strike_data.get("baseline_score", 0.0) or 0.0
    enhanced = best_strike_data.get("enhanced_score", 0.0) or 0.0
    move_fit = best_strike_data.get("move_fit", 0.0) or 0.0
    score_margin = analysis_results.get("_score_margin", 0.0) or 0.0

    # Top-3
    top3_strikes: Tuple[float, ...] = ()
    top3_scores: Tuple[float, ...] = ()
    if direction == "BEARISH":
        pe_ranks = ranked_strikes.get("pe_rankings", [])[:3]
        top3_strikes = tuple(r.get("strike", 0.0) for r in pe_ranks)
        top3_scores = tuple(r.get("score", 0.0) for r in pe_ranks)
    elif direction == "BULLISH":
        ce_ranks = ranked_strikes.get("ce_rankings", [])[:3]
        top3_strikes = tuple(r.get("strike", 0.0) for r in ce_ranks)
        top3_scores = tuple(r.get("score", 0.0) for r in ce_ranks)

    # Ranking components (from _advanced_score components)
    ctx = analysis_results.get("trade_context", {})
    ind = analysis_results.get("indicators", {})
    struct = analysis_results.get("market_structure", {})

    distance_score = 0.0
    move_fit_score = 0.0
    trend_score = 0.0
    indicators_score = ind.get("score", 0.0) if ind else 0.0
    structure_score = struct.get("trend", "NEUTRAL") != "NEUTRAL" and struct.get("score", 0.0) or 0.0
    oi_score = 0.0
    liquidity_score = 0.0
    quality_score = 0.0
    enhanced_move_fit = move_fit

    # LTP
    ltp = market_data.get("ltp", 0.0) if market_data else 0.0
    ltp_ts = market_data.get("timestamp", "") if market_data else ""
    dq = analysis_results.get("_enhancement_data_quality", "UNAVAILABLE") if analysis_results else "UNAVAILABLE"

    return RankingSnapshot(
        timestamp=analysis_results.get("timestamp", ""),
        spot=market_data.get("ltp", 0.0) if market_data else 0.0,
        direction=direction,
        option_type=opt_type,
        expiry=analysis_results.get("trade_context", {}).get("expiry", "") if analysis_results else "",
        strike=strike,
        baseline_score=baseline,
        enhanced_score=enhanced,
        move_fit=move_fit,
        score_margin=score_margin,
        top_3_strikes=top3_strikes,
        top_3_scores=top3_scores,
        distance_score=distance_score,
        move_fit_score=move_fit_score,
        trend_score=trend_score,
        indicators_score=indicators_score,
        structure_score=structure_score,
        oi_score=oi_score,
        liquidity_score=liquidity_score,
        quality_score=quality_score,
        enhanced_move_fit=enhanced_move_fit,
        ltp=ltp,
        ltp_timestamp=ltp_ts,
        data_quality=dq,
    )


# ---------------------------------------------------------------------------
# Convenience function for main.py integration
# ---------------------------------------------------------------------------

def maybe_report_continuity(
    current_snapshot: RankingSnapshot,
    display_func=None,
) -> None:
    """Generate and display continuity information after a cycle.

    Call this at the end of display_recommendation().

    If there is no previous snapshot, it reports "FIRST LIVE CYCLE".
    Otherwise it compares current vs previous and prints a compact
    continuity section.

    The current ranking remains authoritative. This only adds a display
    strip; it does NOT modify any scores, strikes, or validator decisions.

    Order: COMPARE first against the stored previous snapshot, THEN save
    current as previous for the next cycle. Saving before comparing would
    compare the snapshot against itself.

    Display uses the real winner option_type and enhanced_score (never the
    strike number or a hardcoded side).
    """
    from engines.learning.strike_continuity import StrikeContinuityTracker

    # Compare current against the stored previous snapshot FIRST,
    # then save current as previous for the NEXT cycle.
    report = StrikeContinuityTracker.compare(current_snapshot)

    StrikeContinuityTracker.save_previous(current_snapshot)

    if display_func is None:
        if report.status == "FIRST_CYCLE":
            print(f"── Leader: first cycle {current_snapshot.option_type} {current_snapshot.enhanced_score}/100")
        else:
            same = not report.strike_change
            prev = report.previous_leader or "none"
            curr = current_snapshot.strike
            print(f"── Leader: {'same' if same else f'changed to {curr}'} (was {prev}) {current_snapshot.option_type} {current_snapshot.enhanced_score}/100")
        return

    display_func(report)
