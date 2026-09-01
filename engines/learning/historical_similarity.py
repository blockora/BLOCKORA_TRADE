"""Historical Similarity + Evidence Engine — Phase 21C.

Deterministic, explainable similarity between current market setups
and past stored observations. Pure evidence layer only — does NOT
modify ranking, scores, strikes, or winner selection.

Historical evidence is INFORMATIONAL ONLY.
"""


# --- Similarity weights (bounded, sum to 100) ---

SIMILARITY_WEIGHTS = {
    "direction": 15,
    "market_regime": 15,
    "option_type": 10,
    "moneyness": 15,
    "expected_move": 10,
    "mtf_state": 10,
    "adx": 5,
    "rsi": 5,
    "vwap": 5,
    "oi_context": 5,
    "volume_context": 5,
}


def calculate_similarity(current: dict, historical: dict) -> int:
    """Calculate similarity score between 0–100 for two observations.

    Only fields that exist and are comparable contribute points.
    Missing fields contribute 0 and are listed as UNKNOWN in the evidence.

    Returns integer 0–100.
    """
    if not current or not historical:
        return 0

    score = 0
    explanations = []

    # 1. Direction (15 pts)
    cur_dir = current.get("direction")
    hist_dir = historical.get("direction")
    if cur_dir is not None and hist_dir is not None:
        if cur_dir == hist_dir:
            score += SIMILARITY_WEIGHTS["direction"]
            explanations.append(f"Direction matched: {cur_dir}")
        else:
            explanations.append(
                f"Direction mismatch: current={cur_dir}, historical={hist_dir}"
            )
    # If either is missing, 0 pts for this factor (no guess)

    # 2. Market regime (15 pts)
    cur_regime = current.get("market_regime")
    hist_regime = historical.get("market_regime")
    if cur_regime is not None and hist_regime is not None:
        if cur_regime == hist_regime:
            score += SIMILARITY_WEIGHTS["market_regime"]
            explanations.append(f"Regime matched: {cur_regime}")
        else:
            explanations.append(
                f"Regime mismatch: current={cur_regime}, historical={hist_regime}"
            )

    # 3. Option type (10 pts)
    cur_opt = current.get("option_type")
    hist_opt = historical.get("option_type")
    if cur_opt is not None and hist_opt is not None:
        if cur_opt == hist_opt:
            score += SIMILARITY_WEIGHTS["option_type"]
            explanations.append(f"Option type matched: {cur_opt}")
        else:
            explanations.append(
                f"Option type mismatch: current={cur_opt}, historical={hist_opt}"
            )

    # 4. Moneyness / strike distance from spot (15 pts)
    cur_spot = current.get("spot")
    hist_spot = historical.get("spot")
    cur_strike = current.get("strike")
    hist_strike = historical.get("strike")

    if cur_spot is not None and hist_spot is not None and cur_strike is not None and hist_strike is not None:
        cur_moneyness = abs(cur_strike - cur_spot)
        hist_moneyness = abs(hist_strike - hist_spot)
        # Normalise by spot; closer = more similar
        # We consider "close" as within 1% spot, "moderate" as within 2%, etc.
        cur_pct = cur_moneyness / max(1, cur_spot) * 100
        hist_pct = hist_moneyness / max(1, hist_spot) * 100

        # Both within 1% spot = full points; both within 2% = 80%; etc.
        if cur_pct <= 1 and hist_pct <= 1:
            score += SIMILARITY_WEIGHTS["moneyness"]
            explanations.append(
                f"Moneyness similar: both within 1% spot"
            )
        elif cur_pct <= 2 and hist_pct <= 2:
            score += int(SIMILARITY_WEIGHTS["moneyness"] * 0.8)
            explanations.append(
                f"Moneyness similar: both within 2% spot"
            )
        elif cur_pct <= 3 and hist_pct <= 3:
            score += int(SIMILARITY_WEIGHTS["moneyness"] * 0.6)
            explanations.append(
                f"Moneyness similar: both within 3% spot"
            )
        else:
            explanations.append(
                f"Moneyness different: current {cur_pct:.1f}% spot, historical {hist_pct:.1f}% spot"
            )
    # If strike or spot missing, 0 pts for moneyness (no fabrication)

    # 5. Expected-move relationship (10 pts)
    cur_exp = current.get("expected_move")
    hist_exp = historical.get("expected_move")
    if cur_exp is not None and hist_exp is not None and cur_exp > 0 and hist_exp > 0:
        # Compare expected move as percentage of spot
        cur_pct = cur_exp / max(1, cur_spot) * 100 if cur_spot else 0
        hist_pct = hist_exp / max(1, hist_spot) * 100 if hist_spot else 0
        if abs(cur_pct - hist_pct) <= 5:
            score += SIMILARITY_WEIGHTS["expected_move"]
            explanations.append(
                f"Expected-move similar: both ~{hist_pct:.0f}% spot"
            )
        else:
            explanations.append(
                f"Expected-move different: current {cur_pct:.0f}% spot, historical {hist_pct:.0f}% spot"
            )
    # If expected move missing, 0 pts

    # 6. MTF state (10 pts)
    cur_mtf = current.get("mtf_state")
    hist_mtf = historical.get("mtf_state")
    if cur_mtf is not None and hist_mtf is not None:
        if cur_mtf == hist_mtf:
            score += SIMILARITY_WEIGHTS["mtf_state"]
            explanations.append(f"MTF state matched: {cur_mtf}")
        else:
            explanations.append(
                f"MTF state mismatch: current={cur_mtf}, historical={hist_mtf}"
            )

    # 7. ADX (5 pts)
    cur_adx = current.get("adx")
    hist_adx = historical.get("adx")
    if cur_adx is not None and hist_adx is not None:
        # Lower ADX = weaker trend; higher = stronger; match if within 5 pts
        if abs(cur_adx - hist_adx) <= 5:
            score += SIMILARITY_WEIGHTS["adx"]
            explanations.append(f"ADX similar: {hist_adx:.1f}")
        else:
            explanations.append(
                f"ADX different: current {cur_adx:.1f}, historical {hist_adx:.1f}"
            )

    # 8. RSI (5 pts)
    cur_rsi = current.get("rsi")
    hist_rsi = historical.get("rsi")
    if cur_rsi is not None and hist_rsi is not None:
        # RSI: overbought >70, oversold <30; match if within 10 pts
        if abs(cur_rsi - hist_rsi) <= 10:
            score += SIMILARITY_WEIGHTS["rsi"]
            explanations.append(f"RSI similar: {hist_rsi:.1f}")
        else:
            explanations.append(
                f"RSI different: current {cur_rsi:.1f}, historical {hist_rsi:.1f}"
            )

    # 9. VWAP relationship (5 pts)
    cur_vwap = current.get("vwap_relationship")
    hist_vwap = historical.get("vwap_relationship")
    if cur_vwap is not None and hist_vwap is not None:
        if cur_vwap == hist_vwap:
            score += SIMILARITY_WEIGHTS["vwap"]
            explanations.append(f"VWAP relationship matched: {cur_vwap}")
        else:
            explanations.append(
                f"VWAP relationship mismatch: current={cur_vwap}, historical={hist_vwap}"
            )

    # 10. OI context (5 pts)
    cur_oi = current.get("oi_context")
    hist_oi = historical.get("oi_context")
    if cur_oi is not None and hist_oi is not None:
        if cur_oi == hist_oi:
            score += SIMILARITY_WEIGHTS["oi_context"]
            explanations.append(f"OI context matched: {cur_oi}")
        else:
            explanations.append(
                f"OI context mismatch: current={cur_oi}, historical={hist_oi}"
            )

    # 11. Volume context (5 pts)
    cur_vol = current.get("volume_context")
    hist_vol = historical.get("volume_context")
    if cur_vol is not None and hist_vol is not None:
        if cur_vol == hist_vol:
            score += SIMILARITY_WEIGHTS["volume_context"]
            explanations.append(f"Volume context matched: {cur_vol}")
        else:
            explanations.append(
                f"Volume context mismatch: current={cur_vol}, historical={hist_vol}"
            )

    # Bounded 0–100
    score = max(0, min(100, score))
    return score


def classify_sample_size(count: int) -> str:
    """Classify historical evidence sample quality by match count."""
    if count == 0:
        return "NO_HISTORICAL_EVIDENCE"
    if count <= 4:
        return "INSUFFICIENT_SAMPLE"
    if count <= 19:
        return "LIMITED_SAMPLE"
    if count <= 49:
        return "USEFUL_SAMPLE"
    return "STRONG_SAMPLE"


def _timestamp_cutoff(current_ts: str, historical_ts: str) -> bool:
    """Return True if historical observation is strictly older than current.

    No look-ahead bias: only observations with historical.timestamp < current.timestamp
    may be used.
    """
    if not current_ts or not historical_ts:
        return False
    try:
        from datetime import datetime
        cur = datetime.fromisoformat(str(current_ts))
        hist = datetime.fromisoformat(str(historical_ts))
        return hist < cur
    except Exception:
        # If timestamps can't be parsed, exclude from similarity
        return False


def find_similar(
    current: dict,
    historical: list,
    threshold: int = 70,
    max_results: int = 20,
) -> list:
    """Find historical observations similar to the current setup.

    Only observations with historical.timestamp < current.timestamp are considered.

    Returns list of (similarity_score, observation) tuples, sorted highest first,
    limited to max_results, filtered by threshold.
    """
    if not current or not historical:
        return []

    current_ts = current.get("timestamp", "")
    matches = []

    for obs in historical:
        hist_ts = obs.get("timestamp", "")
        if not _timestamp_cutoff(current_ts, hist_ts):
            continue  # skip future/unknown timestamps

        sim = calculate_similarity(current, obs)
        if sim >= threshold:
            matches.append((sim, obs))

    # Sort highest similarity first
    matches.sort(key=lambda x: x[0], reverse=True)

    # Limit to max_results
    matches = matches[:max_results]

    return matches


def build_evidence(
    current: dict,
    matches: list,
    historical: list | None = None,
) -> dict:
    """Build structured historical evidence display from similarity matches.

    Returns dict with:
    - similarity_score: int 0–10 (bounded, informational only)
    - sample_quality: str (NO_HISTORICAL_EVIDENCE / INSUFFICIENT / LIMITED / USEFUL / STRONG)
    - match_count: int
    - supporting: list of str reasons
    - against: list of str reasons
    - outcome: "AVAILABLE" or "UNKNOWN"
    - evidence_explanations: list of str
    """
    if not matches:
        return {
            "similarity_score": 0,
            "sample_quality": "NO_HISTORICAL_EVIDENCE",
            "match_count": 0,
            "supporting": [],
            "against": [],
            "outcome": "UNKNOWN",
            "evidence_explanations": [
                "No sufficiently similar historical setups found"
            ],
        }

    match_count = len(matches)

    # Classify sample quality
    sample_quality = classify_sample_size(match_count)

    # Collect supporting and against reasons from all matches
    supporting = []
    against = []
    outcome_available = False
    outcome_notes = []

    for sim, obs in matches:
        # Extract explanation parts from the similarity calc
        # (We re-evaluate to keep it deterministic and self-contained)
        cur = current

        # Direction
        if cur.get("direction") == obs.get("direction"):
            supporting.append("Direction matched")
        else:
            against.append(
                f"Direction: current={cur.get('direction')}, historical={obs.get('direction')}"
            )

        # Market regime
        if cur.get("market_regime") == obs.get("market_regime"):
            supporting.append("Regime matched")
        else:
            against.append(
                f"Regime: current={cur.get('market_regime')}, historical={obs.get('market_regime')}"
            )

        # Option type
        if cur.get("option_type") == obs.get("option_type"):
            supporting.append("Option type matched")
        else:
            against.append(
                f"Option type: current={cur.get('option_type')}, historical={obs.get('option_type')}"
            )

        # Moneyness
        cur_spot = cur.get("spot")
        hist_strike = obs.get("strike")
        cur_strike = cur.get("strike")
        if cur_spot is not None and hist_strike is not None and cur_strike is not None:
            cur_pct = abs(cur_strike - cur_spot) / max(1, cur_spot) * 100
            hist_pct = abs(hist_strike - hist_spot) / max(1, hist_spot) * 100 if (hist_spot := obs.get("spot")) else 0
            if cur_pct <= 1 and hist_pct <= 1:
                supporting.append("Similar moneyness")
            else:
                against.append(
                    f"Moneyness different: current {cur_pct:.1f}% spot"
                )

        # Expected move
        cur_exp = cur.get("expected_move")
        hist_exp = obs.get("expected_move")
        if cur_exp is not None and hist_exp is not None and cur_exp > 0 and hist_exp > 0:
            if abs(cur_exp - hist_exp) <= 5:
                supporting.append("Similar expected-move relationship")
            else:
                against.append(
                    f"Expected-move different"
                )

        # MTF state
        if cur.get("mtf_state") == obs.get("mtf_state"):
            supporting.append("MTF state matched")
        else:
            against.append(
                f"MTF state: current={cur.get('mtf_state')}, historical={obs.get('mtf_state')}"
            )

        # ADX
        cur_adx = cur.get("adx")
        hist_adx = obs.get("adx")
        if cur_adx is not None and hist_adx is not None:
            if abs(cur_adx - hist_adx) <= 5:
                supporting.append("ADX similar")
            else:
                against.append(
                    f"ADX different: current {cur_adx}, historical {hist_adx}"
                )

        # RSI
        cur_rsi = cur.get("rsi")
        hist_rsi = obs.get("rsi")
        if cur_rsi is not None and hist_rsi is not None:
            if abs(cur_rsi - hist_rsi) <= 10:
                supporting.append("RSI similar")
            else:
                against.append(
                    f"RSI different: current {cur_rsi}, historical {hist_rsi}"
                )

        # VWAP relationship
        if cur.get("vwap_relationship") == obs.get("vwap_relationship"):
            supporting.append("VWAP relationship matched")
        else:
            against.append(
                f"VWAP relationship: current={cur.get('vwap_relationship')}, historical={obs.get('vwap_relationship')}"
            )

        # OI context
        if cur.get("oi_context") == obs.get("oi_context"):
            supporting.append("OI context matched")
        else:
            against.append(
                f"OI context: current={cur.get('oi_context')}, historical={obs.get('oi_context')}"
            )

        # Volume context
        cur_vol = cur.get("volume_context")
        hist_vol = obs.get("volume_context")
        if cur_vol is not None and hist_vol is not None:
            if cur_vol == hist_vol:
                supporting.append("Volume context matched")
            else:
                against.append(
                    f"Volume context: current={cur_vol}, historical={hist_vol}"
                )

        # Outcome handling: check if outcome data is available in the historical observation
        # The observation stores outcome data separately; if it has valid outcome info, mark as available
        outcome_data = obs.get("outcome_data")
        if outcome_data and outcome_data != "UNKNOWN":
            outcome_available = True

    # Deduplicate supporting/against lists
    supporting = list(dict.fromkeys(supporting))
    against = list(dict.fromkeys(against))

    # Determine evidence score (0-10 bounded)
    # Base on similarity score / 10, adjusted by sample quality
    avg_similarity = sum(s for s, _ in matches) / len(matches) if matches else 0
    evidence_score = round(min(10, avg_similarity / 10))

    # Adjust by sample quality
    if sample_quality == "NO_HISTORICAL_EVIDENCE":
        evidence_score = 0
    elif sample_quality == "INSUFFICIENT_SAMPLE":
        evidence_score = min(evidence_score, 3)
    elif sample_quality == "LIMITED_SAMPLE":
        evidence_score = min(evidence_score, 5)
    elif sample_quality == "USEFUL_SAMPLE":
        evidence_score = min(evidence_score, 7)
    elif sample_quality == "STRONG_SAMPLE":
        evidence_score = min(evidence_score, 10)

    return {
        "similarity_score": evidence_score,  # 0–10 bounded
        "sample_quality": sample_quality,
        "match_count": match_count,
        "supporting": supporting,
        "against": against,
        "outcome": "AVAILABLE" if outcome_available else "UNKNOWN",
        "evidence_explanations": [
            f"{match_count} similar setups found out of historical database"
        ],
    }


# --- Convenience function for main.py integration ---

def get_historical_evidence(
    current_observation: dict,
    memory: MarketMemory,
    threshold: int = 70,
    max_results: int = 20,
) -> dict:
    """Fetch historical evidence for a current observation.

    Retrieves from MarketMemory, calculates similarity, classifies sample quality,
    and builds the evidence display dict.

    Returns evidence dict as described in build_evidence().
    Historical evidence is informational only — does NOT modify
    baseline_scores, enhanced_scores, or winner selection.
    """
    from engines.learning.market_memory import MarketMemory

    if not isinstance(memory, MarketMemory):
        memory = MarketMemory()

    # Retrieve recent observations from memory
    all_observations = memory.get_recent(limit=500)  # configurable max

    if not all_observations:
        return {
            "similarity_score": 0,
            "sample_quality": "NO_HISTORICAL_EVIDENCE",
            "match_count": 0,
            "supporting": [],
            "against": [],
            "outcome": "UNKNOWN",
            "evidence_explanations": ["No historical observations stored"],
        }

    # Find similar setups
    matches = find_similar(current_observation, all_observations, threshold, max_results)

    # Build evidence display
    evidence = build_evidence(current_observation, matches, all_observations)

    return evidence
