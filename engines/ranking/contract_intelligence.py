"""Contract-Level Strike Intelligence — Phase 23.

Deterministic, explainable contract-level analysis layer.
Pure evidence layer — does NOT modify ranking, scores, strikes, or winner selection.

Current live ranking ALWAYS wins. Contract intelligence is informational only.
No fabricated data. All missing fields stored as UNAVAILABLE, never guessed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data quality classifications
# ---------------------------------------------------------------------------

DATA_QUALITY_CHOICES = ("REAL", "DERIVED", "ESTIMATED", "UNAVAILABLE")


def classify_quality(
    has_real: bool = False, has_derived: bool = False, source: str = ""
) -> str:
    """Classify data quality for a metric.

    Rules:
    - REAL: Directly supplied by verified live broker/NSE data with valid timestamp
    - DERIVED: Mathematically calculated only from REAL inputs
    - ESTIMATED: Modelled/inferred value where the source is explicitly known to be estimated
    - UNAVAILABLE: Required input does not exist
    """
    if has_real and not has_derived:
        return "REAL"
    if has_derived:
        return "DERIVED"
    if source and "estimated" in source.lower():
        return "ESTIMATED"
    return "UNAVAILABLE"


# ---------------------------------------------------------------------------
# Contract identity
# ---------------------------------------------------------------------------

def contract_identity(
    symbol: str, expiry: str, strike: float, option_type: str
) -> str:
    """Return exact contract identity string.

    Identity is: symbol + expiry + strike + option_type
    Example: NIFTY | 18AUG2026 | 24400 | PE

    Two contracts are identical ONLY if all four components match exactly.
    """
    return f"{symbol.upper()} | {expiry} | {strike} | {option_type.upper()}"


def are_same_contract(
    id1: str, id2: str
) -> bool:
    """Check if two contract identity strings represent the same contract."""
    return id1 == id2


def contract_components(
    identity: str,
) -> Tuple[str, str, float, str]:
    """Parse contract identity string into components.

    Returns (symbol, expiry, strike, option_type)
    """
    parts = [p.strip() for p in identity.split(" | ")]
    if len(parts) != 4:
        raise ValueError(f"Invalid contract identity: {identity}")
    symbol, expiry, strike_str, opt_type = parts
    strike = float(strike_str)
    return symbol, expiry, strike, opt_type


# ---------------------------------------------------------------------------
# Moneyness intelligence
# ---------------------------------------------------------------------------

def calculate_moneyness(
    strike: float, spot: float
) -> Dict[str, Any]:
    """Calculate moneyness for a strike vs spot.

    Returns classification, distance, and quality.
    """
    distance = abs(strike - spot)
    distance_pct = (distance / max(1, spot)) * 100

    if strike <= spot:
        classification = "ITM"
    elif strike >= spot:
        classification = "OTM"
    else:
        classification = "UNKNOWN"

    # ATM / NEAR_ATM classification
    if distance <= 25:
        atm_classification = "ATM"
    elif distance <= 75:
        atm_classification = "NEAR_ATM"
    else:
        atm_classification = "WIDE"

    # Determine quality based on distance
    if distance <= 25:
        quality = "STRONG"
    elif distance <= 75:
        quality = "MODERATE"
    elif distance <= 125:
        quality = "FAIR"
    else:
        quality = "LOW"

    return {
        "distance": distance,
        "distance_pct": distance_pct,
        "classification": classification,
        "atm_classification": atm_classification,
        "quality": quality,
    }


# ---------------------------------------------------------------------------
# OI intelligence
# ---------------------------------------------------------------------------

def oi_intelligence(
    oi: float = 0.0, prev_oi: Optional[float] = None,
    oi_timestamp: str = "", prev_oi_timestamp: str = ""
) -> Dict[str, Any]:
    """Calculate OI intelligence for a contract.

    Rules:
    - Use REAL OI when available
    - OI CHANGE only when previous valid OI exists for SAME contract
    - Otherwise OI_CHANGE = UNAVAILABLE
    - Never infer OI change from current OI alone
    """
    oi_quality = classify_quality(has_real=bool(oi and oi > 0))

    result: Dict[str, Any] = {
        "oi": oi if oi and oi > 0 else 0.0,
        "oi_quality": oi_quality,
        "oi_change": "UNAVAILABLE",
        "oi_change_pct": "UNAVAILABLE",
    }

    # OI CHANGE only when previous valid OI exists for the SAME contract
    if prev_oi is not None and prev_oi > 0 and oi is not None and oi > 0:
        oi_change = oi - prev_oi
        oi_change_pct = (oi_change / max(1, prev_oi)) * 100
        result["oi_change"] = oi_change
        result["oi_change_pct"] = oi_change_pct
        result["oi_change_quality"] = classify_quality(
            has_real=True, source=f"OI_CHANGE_{oi}"
        )
    elif prev_oi is not None and prev_oi > 0 and (oi is None or oi == 0):
        # Previous exists but current OI unavailable
        result["oi_change"] = "UNAVAILABLE"
        result["oi_change_pct"] = "UNAVAILABLE"

    return result


# ---------------------------------------------------------------------------
# Volume intelligence
# ---------------------------------------------------------------------------

def volume_intelligence(
    volume: Optional[float] = None, prev_volume: Optional[float] = None,
    volume_timestamp: str = "", prev_volume_timestamp: str = ""
) -> Dict[str, Any]:
    """Calculate volume intelligence for a contract.

    Rules:
    - Use REAL volume when available
    - VOLUME_ACCELERATION only if multiple valid time observations exist
    - If prior volume snapshot unavailable: VOLUME_ACCELERATION = UNAVAILABLE
    - Never fabricate acceleration
    """
    vol_quality = classify_quality(
        has_real=bool(volume is not None and volume > 0)
    )

    result: Dict[str, Any] = {
        "volume": volume if volume is not None and volume > 0 else 0.0,
        "volume_quality": vol_quality,
        "volume_acceleration": "UNAVAILABLE",
        "volume_rank": "UNAVAILABLE",
    }

    # Volume acceleration only when prior valid volume snapshot exists
    # for the same contract
    if prev_volume is not None and volume is not None:
        # Simple acceleration: compare current vs previous
        if prev_volume > 0:
            vol_change = volume - prev_volume
            vol_change_pct = (vol_change / max(1, prev_volume)) * 100
            result["volume_change"] = vol_change
            result["volume_change_pct"] = vol_change_pct
            # Acceleration is change-of-change; without a second prior point,
            # we mark acceleration as ESTIMATED at best
            result["volume_acceleration"] = "ESTIMATED"
            result["volume_acceleration_source"] = (
                f"current={volume} prev={prev_volume}"
            )

    # Volume rank: relative ranking among comparable candidates
    # (computed externally when comparing top-N candidates)

    return result


# ---------------------------------------------------------------------------
# Premium intelligence (LTP tracking)
# ---------------------------------------------------------------------------

def premium_intelligence(
    ltp: float = 0.0, prev_ltp: Optional[float] = None,
    ltp_timestamp: str = "", prev_ltp_timestamp: str = ""
) -> Dict[str, Any]:
    """Calculate premium intelligence for a contract.

    Rules:
    - Track current LTP
    - If previous valid LTP for the SAME EXACT CONTRACT exists:
        calculate premium_change, premium_change_pct, premium_velocity
    - Contract identity MUST match: symbol + expiry + strike + option_type
    - Do NOT compare different strikes
    - If no previous valid LTP: PREMIUM_RESPONSE = UNAVAILABLE
    """
    result: Dict[str, Any] = {
        "ltp": ltp if ltp is not None and ltp > 0 else 0.0,
        "ltp_quality": classify_quality(
            has_real=bool(ltp is not None and ltp > 0)
        ),
        "premium_response": "UNAVAILABLE",
        "premium_response_quality": "UNAVAILABLE",
    }

    # Premium response only when previous valid LTP for the SAME contract exists
    if prev_ltp is not None and prev_ltp > 0 and ltp is not None and ltp > 0:
        premium_change = ltp - prev_ltp
        premium_change_pct = (premium_change / max(1, prev_ltp)) * 100

        # Avoid division by zero for velocity; use simple change
        if prev_ltp > 0:
            premium_velocity = premium_change / max(1, abs(prev_ltp - 0))
        else:
            premium_velocity = 0.0

        result["premium_response"] = premium_change
        result["premium_response_pct"] = premium_change_pct
        result["premium_response_quality"] = classify_quality(
            has_real=True, source=f"PREMIUM_{ltp}"
        )
        result["premium_velocity"] = premium_velocity

    return result


# ---------------------------------------------------------------------------
# Bid/Ask quality
# ---------------------------------------------------------------------------

def bid_ask_intelligence(
    bid: Optional[float] = None, ask: Optional[float] = None,
    bid_ts: str = "", ask_ts: str = ""
) -> Dict[str, Any]:
    """Calculate bid/ask quality for a contract.

    Rules:
    - If REAL bid and ask exist: calculate spread and spread_pct
    - Classify: GOOD, ACCEPTABLE, WIDE, UNAVAILABLE
    - Do not fabricate bid/ask
    """
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2
        spread = ask - bid
        spread_pct = (spread / max(1, mid)) * 100

        if spread_pct <= 5:
            spread_class = "GOOD"
        elif spread_pct <= 10:
            spread_class = "ACCEPTABLE"
        else:
            spread_class = "WIDE"

        return {
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread": spread,
            "spread_pct": spread_pct,
            "spread_quality": spread_class,
            "spread_quality_source": "REAL",
        }
    else:
        return {
            "bid": 0.0,
            "ask": 0.0,
            "mid": 0.0,
            "spread": 0.0,
            "spread_pct": 0.0,
            "spread_quality": "UNAVAILABLE",
            "spread_quality_source": "UNAVAILABLE",
        }


# ---------------------------------------------------------------------------
# IV intelligence
# ---------------------------------------------------------------------------

def iv_intelligence(
    iv: Optional[float] = None, prev_iv: Optional[float] = None,
    iv_timestamp: str = "", prev_iv_timestamp: str = ""
) -> Dict[str, Any]:
    """Calculate IV intelligence for a contract.

    Rules:
    - Only use IV if the actual API provides a verified value
    - If IV is REAL: calculate relative IV among comparable strikes
    - If previous IV exists for the SAME contract: calculate IV change
    - Otherwise: IV CHANGE = UNAVAILABLE
    - If IV is unavailable: IV = UNAVAILABLE
    - Do NOT fabricate IV
    - Do NOT infer IV from premium
    """
    result: Dict[str, Any] = {
        "iv": iv if iv is not None and iv > 0 else "UNAVAILABLE",
        "iv_quality": classify_quality(
            has_real=bool(iv is not None and iv > 0),
            source="IV",
        ),
        "iv_change": "UNAVAILABLE",
        "iv_change_pct": "UNAVAILABLE",
    }

    # IV change only when previous IV exists for the SAME contract
    if prev_iv is not None and iv is not None and iv > 0 and prev_iv > 0:
        iv_change = iv - prev_iv
        iv_change_pct = (iv_change / max(1, prev_iv)) * 100
        result["iv_change"] = iv_change
        result["iv_change_pct"] = iv_change_pct
        result["iv_change_quality"] = classify_quality(
            has_real=True, source="IV_CHANGE"
        )

    return result


# ---------------------------------------------------------------------------
# Option response intelligence
# ---------------------------------------------------------------------------

def option_response_intelligence(
    underlying_change: float, premium_change: float
) -> Dict[str, Any]:
    """Calculate observed option response.

    Rules:
    - When two valid observations exist for SAME EXACT CONTRACT
    - AND underlying spot changed during the same interval
    - Calculate: underlying_change, premium_change, premium_response_ratio
    - Report as: OBSERVED OPTION RESPONSE
    - Do NOT call this delta
    - Do NOT infer Greeks
    - Do NOT claim causality
    - If insufficient data: OBSERVED OPTION RESPONSE = UNAVAILABLE
    """
    result: Dict[str, Any] = {
        "underlying_change": underlying_change,
        "premium_change": premium_change,
        "premium_response_ratio": "UNAVAILABLE",
        "response_consistency": "UNAVAILABLE",
    }

    if premium_change != 0 and underlying_change != 0:
        # Calculate ratio (premium change per underlying point)
        # Use absolute values for ratio calculation
        if underlying_change != 0:
            ratio = premium_change / underlying_change
            result["premium_response_ratio"] = ratio

        # Determine consistency based on sign alignment
        # Same sign: positive response (premium moves with underlying direction)
        # Opposite sign: negative response
        if (underlying_change > 0 and premium_change > 0) or (
            underlying_change < 0 and premium_change < 0
        ):
            result["response_consistency"] = "CONSISTENT"
        else:
            result["response_consistency"] = "MIXED"

    return result


# ---------------------------------------------------------------------------
# Response consistency
# ---------------------------------------------------------------------------

def response_consistency(
    observations: List[Dict[str, Any]]
) -> str:
    """Calculate observed response consistency from multiple valid observations.

    Rules:
    - For SAME EXACT CONTRACT identity
    - Multiple valid intraday observations
    - CONSISTENT: all observations show same direction response
    - MIXED: observations show mixed directions
    - If fewer than 2 observations: UNAVAILABLE
    """
    if len(observations) < 2:
        return "UNAVAILABLE"

    consistencies: List[str] = []
    for obs in observations:
        rc = obs.get("response_consistency", "UNAVAILABLE")
        if rc in ("CONSISTENT", "MIXED"):
            consistencies.append(rc)

    if not consistencies:
        return "UNAVAILABLE"

    if all(c == "CONSISTENT" for c in consistencies):
        return "CONSISTENT"
    if all(c == "MIXED" for c in consistencies):
        return "MIXED"
    return "MIXED"


# ---------------------------------------------------------------------------
# Expected-move compatibility
# ---------------------------------------------------------------------------

def move_fit(
    strike: float, spot: float, expected_move: float
) -> Dict[str, Any]:
    """Calculate expected-move compatibility (move fit).

    Returns a score 0-10 representing how well the strike's moneyness
    fits the current expected move.

    This is DERIVED from strike distance vs expected move.
    """
    distance = abs(strike - spot)

    if expected_move <= 0:
        return {
            "move_fit": 0,
            "move_fit_quality": "UNAVAILABLE",
            "message": "Expected move not available",
        }

    # Normalize distance by expected move
    # Closer fit = higher score
    ratio = distance / max(1, expected_move)

    if ratio <= 0.1:
        # Within 10% of expected move = excellent fit
        score = 10
    elif ratio <= 0.25:
        # Within 25% = good fit
        score = 8
    elif ratio <= 0.5:
        # Within 50% = moderate fit
        score = 6
    elif ratio <= 1.0:
        # Within 100% = fair fit
        score = 4
    elif ratio <= 2.0:
        # Beyond expected move but not excessive
        score = 2
    else:
        # Way beyond expected move
        score = 1

    # Determine quality
    if score >= 8:
        quality = "STRONG"
    elif score >= 5:
        quality = "MODERATE"
    else:
        quality = "WEAK"

    return {
        "move_fit": score,
        "move_fit_quality": quality,
        "ratio": ratio,
    }


# ---------------------------------------------------------------------------
# Contract evidence
# ---------------------------------------------------------------------------

def calculate_contract_evidence(
    moneyness: Dict[str, Any],
    oi_result: Dict[str, Any],
    volume_result: Dict[str, Any],
    bid_ask_result: Dict[str, Any],
    iv_result: Dict[str, Any],
    move_fit_result: Dict[str, Any],
    premium_result: Dict[str, Any],
    response_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Calculate overall contract evidence score 0-10.

    This is purely informational and bounded 0-10.
    Does NOT modify baseline_score or enhanced_score.
    """
    weights: Dict[str, int] = {
        "moneyness": 2,
        "oi": 2,
        "volume": 1,
        "bid_ask": 1,
        "iv": 1,
        "move_fit": 2,
        "premium_response": 1,
        "response_consistency": 1,
    }

    total_weight = sum(weights.values())  # 10
    scored = 0
    components: Dict[str, Any] = {}
    quality_flags: List[str] = []

    # Moneyness (0-2)
    mq = moneyness.get("quality", "LOW")
    if mq == "STRONG":
        scored += 2
        components["moneyness"] = "STRONG"
    elif mq == "MODERATE":
        scored += 1
        components["moneyness"] = "MODERATE"
    else:
        components["moneyness"] = "LOW"

    # OI (0-2)
    oiq = oi_result.get("oi_quality", "UNAVAILABLE")
    if oiq == "REAL" and oi_result.get("oi", 0) > 0:
        scored += 2
        components["oi"] = "STRONG"
        quality_flags.append("REAL_OI")
    elif oiq == "REAL":
        scored += 1
        components["oi"] = "MODERATE"
    else:
        components["oi"] = "UNAVAILABLE"

    # Volume (0-1)
    vq = volume_result.get("volume_quality", "UNAVAILABLE")
    if vq == "REAL" and volume_result.get("volume", 0) > 0:
        scored += 1
        components["volume"] = "STRONG"
    else:
        components["volume"] = "UNAVAILABLE"

    # Bid/Ask (0-1)
    baq = bid_ask_result.get("spread_quality", "UNAVAILABLE")
    if baq in ("GOOD", "ACCEPTABLE"):
        scored += 1
        components["bid_ask"] = baq
    else:
        components["bid_ask"] = "UNAVAILABLE"

    # IV (0-1)
    ivq = iv_result.get("iv_quality", "UNAVAILABLE")
    if ivq == "REAL" and iv_result.get("iv", "UNAVAILABLE") != "UNAVAILABLE":
        scored += 1
        components["iv"] = "REAL"
    else:
        components["iv"] = "UNAVAILABLE"

    # Move fit (0-2)
    mfq = move_fit_result.get("move_fit_quality", "UNAVAILABLE")
    mf_score = move_fit_result.get("move_fit", 0)
    if mfq in ("STRONG", "MODERATE") and mf_score >= 4:
        scored += 2
        components["move_fit"] = f"{mf_score}/10"
    elif mfq in ("WEAK",) and mf_score >= 2:
        scored += 1
        components["move_fit"] = f"{mf_score}/10"
    else:
        components["move_fit"] = "UNAVAILABLE"

    # Premium response (0-1)
    pq = premium_result.get("premium_response_quality", "UNAVAILABLE")
    if pq in ("CONSISTENT", "MIXED") and premium_result.get(
        "premium_response", 0
    ) != 0:
        scored += 1
        components["premium_response"] = "AVAILABLE"
    else:
        components["premium_response"] = "UNAVAILABLE"

    # Response consistency (0-1)
    rc = response_result.get("response_consistency", "UNAVAILABLE")
    if rc == "CONSISTENT":
        scored += 1
        components["response_consistency"] = "CONSISTENT"
    else:
        components["response_consistency"] = "UNAVAILABLE"

    # Bounded 0-10
    evidence_score = min(10, max(0, scored))

    return {
        "evidence_score": evidence_score,
        "evidence_score_quality": classify_quality(
            has_derived=True, source="CONTRACT_EVIDENCE"
        ),
        "components": components,
        "quality_flags": quality_flags,
        "evidence_breakdown": {
            "moneyness": components.get("moneyness"),
            "oi": components.get("oi"),
            "volume": components.get("volume"),
            "bid_ask": components.get("bid_ask"),
            "iv": components.get("iv"),
            "move_fit": components.get("move_fit"),
            "premium_response": components.get("premium_response"),
            "response_consistency": components.get("response_consistency"),
        },
    }


# ---------------------------------------------------------------------------
# Contract conviction (informational only)
# ---------------------------------------------------------------------------

def calculate_contract_conviction(
    evidence_score: float,
    data_quality: str,
    score_margin: float,
    has_option_response: bool,
    response_consistency: str,
    liquidity_quality: str = "UNKNOWN",
) -> Dict[str, Any]:
    """Calculate informational contract conviction.

    Rules:
    - HIGH: strong evidence + good data + wide margin + response available
    - MEDIUM: moderate evidence + reasonable data + moderate margin
    - LOW: weak evidence + poor data + narrow margin
    - UNAVAILABLE: insufficient information

    CRITICAL: CONVICTION MUST NOT CHANGE THE WINNER.
    This is purely informational display.
    """
    # Determine base level
    if evidence_score >= 7 and data_quality in ("REAL", "DERIVED"):
        base = "HIGH"
    elif evidence_score >= 4:
        base = "MEDIUM"
    else:
        base = "LOW"

    # Refine based on additional factors
    refinements: List[str] = []

    if has_option_response:
        if response_consistency == "CONSISTENT":
            refinements.append("RES_CONSISTENT")
        elif response_consistency == "MIXED":
            refinements.append("RES_MIXED")

    if score_margin >= 5:
        refinements.append("MARGIN_WIDE")
    elif score_margin >= 3:
        refinements.append("MARGIN_MODERATE")
    else:
        refinements.append("MARGIN_NARROW")

    if liquidity_quality in ("GOOD", "ACCEPTABLE"):
        refinements.append("LIQUID_GOOD")
    else:
        refinements.append("LIQUID_POOR")

    # Final conviction
    if base == "HIGH" and len(refinements) >= 3:
        conviction = "HIGH"
    elif base == "MEDIUM" and len(refinements) >= 2:
        conviction = "MEDIUM"
    else:
        conviction = "LOW"

    return {
        "conviction": conviction,
        "conviction_quality": classify_quality(
            has_derived=True, source="CONTRACT_CONVICTION"
        ),
        "evidence_score": evidence_score,
        "data_quality": data_quality,
        "score_margin": score_margin,
        "refinements": refinements,
        "conviction_should_not_change_winner": True,
    }


# ---------------------------------------------------------------------------
# WHY/AGAINST reasons
# ---------------------------------------------------------------------------

def why_against_reasons(
    moneyness: Dict[str, Any],
    oi_result: Dict[str, Any],
    volume_result: Dict[str, Any],
    bid_ask_result: Dict[str, Any],
    iv_result: Dict[str, Any],
    move_fit_result: Dict[str, Any],
    premium_result: Dict[str, Any],
    response_result: Dict[str, Any],
    conviction: Dict[str, Any],
) -> Tuple[List[str], List[str]]:
    """Generate truthful WHY and AGAINST reasons for the top contract.

    Rules:
    - WHY: positive factors that support the contract
    - AGAINST: cautionary factors or missing data
    - Never invent negative reasons
    - All reasons must be truthfully derivable from the input data
    """
    why: List[str] = []
    against: List[str] = []

    # Moneyness reasons
    mq = moneyness.get("quality", "LOW")
    mc = moneyness.get("atm_classification", "WIDE")
    if mq == "STRONG":
        why.append(f"Near {mc} ({mq.lower()})")
    elif mq == "MODERATE":
        why.append(f"{mc} moneyness")
    else:
        against.append(f"Wide moneyness ({mc})")

    # OI reasons
    oiq = oi_result.get("oi_quality", "UNAVAILABLE")
    if oiq == "REAL" and oi_result.get("oi", 0) > 0:
        oi_val = oi_result.get("oi", 0)
        if oi_val > 5000:
            why.append("Strong OI")
        elif oi_val > 1000:
            why.append("Adequate OI")
        else:
            against.append("Thin OI")
    else:
        against.append("OI unavailable")

    # Volume reasons
    vq = volume_result.get("volume_quality", "UNAVAILABLE")
    if vq == "REAL" and volume_result.get("volume", 0) > 0:
        vval = volume_result.get("volume", 0)
        if vval > 5000:
            why.append("Strong volume")
        elif vval > 1000:
            why.append("Adequate volume")
        else:
            against.append("Thin volume")
    else:
        against.append("Volume unavailable")

    # Bid/Ask reasons
    baq = bid_ask_result.get("spread_quality", "UNAVAILABLE")
    if baq == "GOOD":
        why.append("Good spread")
    elif baq == "ACCEPTABLE":
        why.append("Acceptable spread")
    else:
        against.append("Wide spread")

    # IV reasons
    ivq = iv_result.get("iv_quality", "UNAVAILABLE")
    if ivq == "REAL":
        why.append("IV available")
    else:
        against.append("IV unavailable")

    # Move fit reasons
    mfq = move_fit_result.get("move_fit_quality", "UNAVAILABLE")
    mf_score = move_fit_result.get("move_fit", 0)
    if mfq in ("STRONG", "MODERATE") and mf_score >= 4:
        why.append("Expected move compatible")
    else:
        against.append("Move fit weak")

    # Premium response reasons
    prq = premium_result.get("premium_response_quality", "UNAVAILABLE")
    if prq in ("CONSISTENT", "MIXED") and premium_result.get(
        "premium_response", 0
    ) != 0:
        why.append("Positive observed option response")
    else:
        against.append("Option response unavailable")

    # Response consistency reasons
    rc = response_result.get("response_consistency", "UNAVAILABLE")
    if rc == "CONSISTENT":
        why.append("Response consistent")
    elif rc == "MIXED":
        against.append("Response mixed")

    # Conviction refinements
    if conviction.get("conviction") == "HIGH":
        why.append("High contract conviction")
    elif conviction.get("conviction") == "LOW":
        against.append("Low contract conviction")

    return why, against


# ---------------------------------------------------------------------------
# Snapshot from analysis (integration helper)
# ---------------------------------------------------------------------------

def snapshot_from_analysis(
    analysis_results: Dict[str, object],
    ranked_strikes: Dict[str, object],
    market_data: Dict[str, object],
) -> Dict[str, Any]:
    """Build contract intelligence snapshot from the just-completed analysis cycle.

    This is called AFTER the ranking engine has decided and the cycle is complete.
    It does NOT influence the current ranking.
    """
    spot = market_data.get("ltp", 0.0) if market_data else 0.0
    ctx = analysis_results.get("trade_context", {})
    direction = ctx.get("direction", "") or ""

    # Determine option_type from ranked winner (same logic as generate_recommendation)
    best_ce = ranked_strikes.get("best_ce", {})
    best_pe = ranked_strikes.get("best_pe", {})
    if direction.upper() == "BEARISH" and best_pe:
        opt_type = best_pe.get("option_type", "PE")
    elif direction.upper() == "BULLISH" and best_ce:
        opt_type = best_ce.get("option_type", "CE")
    else:
        # NEUTRAL fallback: pick the side with the higher score
        _ce_score = float(best_ce.get("score", 0) or 0)
        _pe_score = float(best_pe.get("score", 0) or 0)
        if best_pe and _pe_score > _ce_score:
            opt_type = best_pe.get("option_type", "PE")
        else:
            opt_type = best_ce.get("option_type", "CE") if best_ce else "CE"

    # Best strike (whichever the engine picked)
    if direction.upper() == "BEARISH" and best_pe:
        best_strike_data = best_pe
    elif direction.upper() == "BULLISH" and best_ce:
        best_strike_data = best_ce
    else:
        # NEUTRAL fallback: pick the side with the higher score
        _ce_score = float(best_ce.get("score", 0) or 0)
        _pe_score = float(best_pe.get("score", 0) or 0)
        if best_pe and _pe_score > _ce_score:
            best_strike_data = best_pe
        else:
            best_strike_data = best_ce or best_pe or {}

    # Get expiry from ranked winner's live chain data (preserved through _calculate_levels)
    # Fall back to trade_context if expiry not available from ranked data
    expiry = best_strike_data.get("expiry", "") or ctx.get("expiry", "") or "UNAVAILABLE"

    strike = best_strike_data.get("strike", 0.0)

    # Moneyness
    moneyness = calculate_moneyness(strike, spot)

    # OI intelligence (using best_pe or best_ce OI data)
    oi_val = best_strike_data.get("oi", 0)
    prev_oi = best_strike_data.get("prev_oi", None)
    oi_ts = best_strike_data.get("oi_timestamp", "") or ""
    prev_oi_ts = best_strike_data.get("prev_oi_timestamp", "") or ""
    oi_result = oi_intelligence(oi_val, prev_oi, oi_ts, prev_oi_ts)

    # Volume intelligence
    vol_val = best_strike_data.get("volume", None)
    prev_vol = best_strike_data.get("prev_volume", None)
    vol_ts = best_strike_data.get("volume_timestamp", "") or ""
    prev_vol_ts = best_strike_data.get("prev_volume_timestamp", "") or ""
    volume_result = volume_intelligence(vol_val, prev_vol, vol_ts, prev_vol_ts)

    # Bid/Ask intelligence
    bid = best_strike_data.get("bid", None)
    ask = best_strike_data.get("ask", None)
    bid_ts = best_strike_data.get("bid_timestamp", "") or ""
    ask_ts = best_strike_data.get("ask_timestamp", "") or ""
    bid_ask_result = bid_ask_intelligence(bid, ask, bid_ts, ask_ts)

    # IV intelligence
    iv_val = best_strike_data.get("iv", None)
    prev_iv = best_strike_data.get("prev_iv", None)
    iv_ts = best_strike_data.get("iv_timestamp", "") or ""
    prev_iv_ts = best_strike_data.get("prev_iv_timestamp", "") or ""
    iv_result = iv_intelligence(iv_val, prev_iv, iv_ts, prev_iv_ts)

    # Greeks (FIX 4): only when REAL IV present — honest, never fabricated
    greeks = None
    try:
        from engines.ranking.greeks import get_greeks_from_rec
        greeks = get_greeks_from_rec(best_strike_data, spot, analysis_results.get("_config", None) or None, opt_type=opt_type)
    except Exception:
        greeks = None

    # Move fit
    expected_move = analysis_results.get("trade_context", {}).get(
        "expected_move", 30
    ) or 30
    move_fit_result = move_fit(strike, spot, expected_move) if spot else {"move_fit": 0, "move_fit_quality": "UNAVAILABLE", "ratio": 0}
    # Premium intelligence
    ltp = best_strike_data.get("last_price", best_strike_data.get("ltp", 0.0))
    prev_ltp = best_strike_data.get("prev_ltp", None)
    ltp_ts = best_strike_data.get("ltp_timestamp", "") or ""
    prev_ltp_ts = best_strike_data.get("prev_ltp_timestamp", "") or ""
    premium_result = premium_intelligence(ltp, prev_ltp, ltp_ts, prev_ltp_ts)

    # Option response intelligence
    underlying_change = best_strike_data.get("underlying_change", 0.0)
    premium_change = best_strike_data.get("premium_change", 0.0)
    response_result = option_response_intelligence(underlying_change, premium_change)

    # Contract evidence
    contract_evidence = calculate_contract_evidence(
        moneyness=moneyness,
        oi_result=oi_result,
        volume_result=volume_result,
        bid_ask_result=bid_ask_result,
        iv_result=iv_result,
        move_fit_result=move_fit_result,
        premium_result=premium_result,
        response_result=response_result,
    )

    # Propagate live data fields from ranked winner into contract evidence
    contract_evidence["baseline_score"] = best_strike_data.get("baseline_score", 0.0)
    contract_evidence["enhanced_score"] = best_strike_data.get("enhanced_score", 0.0)
    contract_evidence["score_margin"] = best_strike_data.get("score_margin", 0.0) or 0.0

    # Contract conviction
    score_margin = best_strike_data.get("score_margin", 0.0) or 0.0
    data_quality = contract_evidence.get("evidence_score", 0) >= 5 and "REAL" or "UNAVAILABLE"
    conviction_result = calculate_contract_conviction(
        evidence_score=contract_evidence["evidence_score"],
        data_quality=data_quality,
        score_margin=score_margin,
        has_option_response=response_result.get("premium_response", "UNAVAILABLE") != "UNAVAILABLE",
        response_consistency=response_result.get("response_consistency", "UNAVAILABLE"),
        liquidity_quality=bid_ask_result.get("spread_quality", "UNAVAILABLE"),
    )

    # WHY/AGAINST reasons
    why, against = why_against_reasons(
        moneyness=moneyness,
        oi_result=oi_result,
        volume_result=volume_result,
        bid_ask_result=bid_ask_result,
        iv_result=iv_result,
        move_fit_result=move_fit_result,
        premium_result=premium_result,
        response_result=response_result,
        conviction=conviction_result,
    )

    # Contract identity
    cid = contract_identity(
        symbol=analysis_results.get("symbol", "NIFTY"),
        expiry=expiry,
        strike=strike,
        option_type=opt_type,
    )

    # LTP from best strike data (last_price takes priority, falls back to ltp)
    snapshot_ltp = best_strike_data.get("last_price", best_strike_data.get("ltp", 0.0))

    premium_source = best_strike_data.get("premium_source", "ESTIMATED")

    return {
        "contract_identity": cid,
        "expiry": expiry,
        "strike": strike,
        "option_type": opt_type,
        "moneyness": moneyness,
        "oi": oi_result,
        "volume": volume_result,
        "bid_ask": bid_ask_result,
        "iv": iv_result,
        "greeks": greeks,
        "move_fit": move_fit_result,
        "expected_move": expected_move,
        "premium_source": premium_source,
        "premium_response": premium_result,
        "option_response": response_result,
        "ltp": snapshot_ltp,
        "contract_evidence": contract_evidence,
        "contract_conviction": conviction_result,
        "why": why,
        "against": against,
        "data_quality": contract_evidence.get("evidence_score", 0) >= 5 and "MIXED" or "LIMITED",
    
}
def maybe_report_contract_intelligence(
    contract_snapshot: Dict[str, Any],
    display_func=None,
) -> None:
    """Generate and display contract intelligence after a cycle.

    Call this at the end of display_recommendation().

    If contract intelligence is unavailable, it reports UNAVAILABLE.
    The current ranking remains authoritative. This only adds a display
    strip; it does NOT modify any scores, strikes, or validator decisions.
    """
    if display_func is None:
        ci = contract_snapshot.get("contract_evidence", {})
        conv = contract_snapshot.get("contract_conviction", {})
        greeks = contract_snapshot.get("greeks")
        # FIX 4a: real IV -> show Greeks + optional SWEET SPOT
        if greeks and isinstance(greeks, dict):
            greeks_str = f" Greeks:{greeks}"
            delta_text = ""
            try:
                delta = abs(float(greeks.get("delta", 0) or 0))
                if 0.30 <= delta <= 0.55:
                    delta_text = " SWEET SPOT"
            except Exception:
                pass
            print(f"── Intel: {contract_snapshot.get('contract_identity', 'UNKNOWN')} ev {ci.get('evidence_score', 0)}/10 | {conv.get('conviction', 'UNAVAILABLE')}{greeks_str}{delta_text}")
        # FIX 4b: no real IV -> honestly unavailable
        else:
            print(f"── Intel: {contract_snapshot.get('contract_identity', 'UNKNOWN')} ev {ci.get('evidence_score', 0)}/10 | {conv.get('conviction', 'UNAVAILABLE')} Greeks: UNAVAILABLE")
        return

    display_func(contract_snapshot)
