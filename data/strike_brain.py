"""
BLOCKORA_TRADE - Strike Brain Scoring Engine
Pure Python implementation of brain.md algorithms
"""

NIFTY_LOT_SIZE = 65


def delta_score(delta):
    """Delta scoring: ideal 0.40-0.60 = 10, acceptable 0.30-0.70 = 7, poor 0.20-0.80 = 4, avoid else = 2"""
    abs_delta = abs(delta)
    if 0.40 <= abs_delta <= 0.60:
        return 10
    elif 0.30 <= abs_delta < 0.40 or 0.60 < abs_delta <= 0.70:
        return 7
    elif 0.20 <= abs_delta < 0.30 or 0.70 < abs_delta <= 0.80:
        return 4
    return 2


def iv_score(iv_rank):
    """IV Rank scoring for BUYING: <20=10, 20-40=8, 40-60=6, 60-80=4, >80=2"""
    if iv_rank < 20:
        return 10
    elif iv_rank < 40:
        return 8
    elif iv_rank < 60:
        return 6
    elif iv_rank < 80:
        return 4
    return 2


def oi_score(oi_change, price_direction, option_type):
    """OI interpretation matrix"""
    if price_direction == "BEARISH" and option_type == "PE":
        if oi_change > 1.5:
            return 10
        elif oi_change > 0.5:
            return 8
        elif oi_change > 0:
            return 6
        else:
            return 4
    elif price_direction == "BULLISH" and option_type == "CE":
        if oi_change > 1.5:
            return 10
        elif oi_change > 0.5:
            return 8
        elif oi_change > 0:
            return 6
        else:
            return 4
    return 5


def liquidity_score(volume, spread_percent):
    """Liquidity scoring: vol>10k&spread<2%=10, >5k&<5%=8, >1k&<8%=6, >100&<10%=4, else=2"""
    if volume > 10000 and spread_percent < 2:
        return 10
    elif volume > 5000 and spread_percent < 5:
        return 8
    elif volume > 1000 and spread_percent < 8:
        return 6
    elif volume > 100 and spread_percent < 10:
        return 4
    return 2


def rsi_score(rsi, direction):
    """RSI scoring per direction"""
    if direction == "BULLISH":
        if 40 <= rsi <= 60:
            return 8
        elif rsi < 30:
            return 9
        elif rsi > 70:
            return 3
        else:
            return 6
    else:
        if 40 <= rsi <= 60:
            return 8
        elif rsi > 70:
            return 9
        elif rsi < 30:
            return 3
        else:
            return 6


def adx_score(adx):
    """ADX scoring: >25=10, >20=7, >15=5, else=3"""
    if adx > 25:
        return 10
    elif adx > 20:
        return 7
    elif adx > 15:
        return 5
    return 3


def vwap_score(price, vwap, direction):
    """VWAP scoring: price on correct side = 9, wrong side = 5"""
    if direction == "BULLISH":
        return 9 if price > vwap else 5
    else:
        return 9 if price < vwap else 5


def macd_score(macd_hist, direction):
    """MACD histogram scoring"""
    if direction == "BULLISH":
        return 9 if macd_hist > 0 else 5
    else:
        return 9 if macd_hist < 0 else 5


def technical_score(rsi, adx, price, vwap, macd_hist, direction):
    """Composite technical score (average of 4 factors)"""
    rs = rsi_score(rsi, direction)
    ad = adx_score(adx)
    vw = vwap_score(price, vwap, direction)
    mc = macd_score(macd_hist, direction)
    return (rs + ad + vw + mc) / 4


def rr_score(rr_ratio):
    """Risk-Reward scoring: >=3=10, >=2=8, >=1.5=6, else=3"""
    if rr_ratio >= 3:
        return 10
    elif rr_ratio >= 2:
        return 8
    elif rr_ratio >= 1.5:
        return 6
    return 3


def candle_score(pattern, at_key_level):
    """Candle pattern scoring with key level bonus"""
    bullish = {
        "Bullish Engulfing": 10, "Morning Star": 9, "Hammer": 8,
        "Piercing Line": 8, "Three White Soldiers": 9, "No Pattern": 4
    }
    bearish = {
        "Bearish Engulfing": 10, "Evening Star": 9, "Shooting Star": 8,
        "Dark Cloud Cover": 8, "Three Black Crows": 9, "No Pattern": 4
    }
    base = bullish.get(pattern, bearish.get(pattern, 4))
    if at_key_level:
        base = min(10, base + 1)
    return base


def calculate_confidence(scores):
    """
    Calculate weighted confidence with penalties.
    Returns (final_confidence, weighted_total, penalty_details)
    """
    weights = {
        'delta': 0.20, 'iv': 0.15, 'oi': 0.15, 'liquidity': 0.10,
        'technical': 0.20, 'rr': 0.10, 'candle': 0.10
    }

    weighted_total = (
        scores['delta'] * weights['delta'] +
        scores['iv'] * weights['iv'] +
        scores['oi'] * weights['oi'] +
        scores['liquidity'] * weights['liquidity'] +
        scores['technical'] * weights['technical'] +
        scores['rr'] * weights['rr'] +
        scores['candle'] * weights['candle']
    )

    raw_confidence = weighted_total * 10
    confidence = raw_confidence
    penalties = []

    if scores.get('counter_trend', False):
        penalty = confidence * 0.30
        confidence -= penalty
        penalties.append(f"counter_trend -30% ({penalty:.1f})")
    if scores.get('iv_rank', 0) > 80:
        penalty = confidence * 0.20
        confidence -= penalty
        penalties.append(f"high_iv -20% ({penalty:.1f})")
    if scores.get('low_volume', False):
        penalty = confidence * 0.15
        confidence -= penalty
        penalties.append(f"low_volume -15% ({penalty:.1f})")
    if scores.get('news_event', False):
        penalty = confidence * 0.40
        confidence -= penalty
        penalties.append(f"news_event -40% ({penalty:.1f})")

    final = min(100, max(0, round(confidence, 1)))
    return final, round(raw_confidence, 1), penalties


def calculate_entry_price(bid, ask):
    """Entry = mid-price + 25% slippage, rounded to 0.05"""
    mid = (bid + ask) / 2
    spread = ask - bid
    slippage = spread * 0.25
    entry = mid + slippage
    return round(entry / 0.05) * 0.05


def calculate_stop_loss(entry, atr, direction):
    """
    7-POINT SCALPING MODE: fixed 5-point tight stop.
    SL: entry - 5 (fixed points, no ATR dependency)
    """
    return entry - 5


def calculate_targets(entry, atr, direction):
    """
    7-POINT SCALPING MODE: fixed point targets.
    T1: entry + 7 | T2: entry + 10 | T3: entry + 14
    ATR parameter kept for signature compatibility - ignored.
    """
    t1 = entry + 7
    t2 = entry + 10
    t3 = entry + 14
    return round(t1, 2), round(t2, 2), round(t3, 2)


def calculate_invalidation(spot, vwap, atr, direction):
    """
    Keep as-is (VWAP ± 1*ATR) - this is spot-based, not premium.
    """
    if direction == "BEARISH":
        return round(vwap + 1.0 * atr, 2)
    else:
        return round(vwap - 1.0 * atr, 2)


def calculate_probabilities(confidence, iv_rank, adx):
    """Confidence-adjusted probabilities"""
    t1_base, t2_base, t3_base = 65, 45, 25

    def adjust(base):
        p = base
        if confidence > 80:
            p += 10
        elif confidence > 70:
            p += 5
        if iv_rank < 30:
            p += 5
        if adx > 25:
            p += 5
        return min(95, p)

    return adjust(t1_base), adjust(t2_base), adjust(t3_base)


def kelly_position_size(win_rate, avg_win, avg_loss, capital, premium):
    """
    Half-Kelly position sizing with 5% capital cap.
    Returns (units, lots, capital_used, kelly_pct)
    """
    if avg_loss <= 0:
        return 0, 0, 0, 0

    b = avg_win / avg_loss
    p = win_rate
    q = 1 - p
    kelly_fraction = (b * p - q) / b
    kelly_fraction = max(0, kelly_fraction / 2)  # half-Kelly
    kelly_fraction = min(kelly_fraction, 0.05)   # 5% cap

    position_capital = capital * kelly_fraction
    units = int(position_capital / premium) if premium > 0 else 0
    lots = units / NIFTY_LOT_SIZE
    capital_used = units * premium

    return units, round(lots, 2), capital_used, round(kelly_fraction * 100, 2)


def make_decision(confidence, rr_ratio):
    """Decision logic with RR grade cap"""
    if confidence < 60:
        return "NO_TRADE", "C SETUP", "AVOID - LOW PROBABILITY"
    if rr_ratio < 1.0:
        return "WATCHLIST", "B SETUP", "RR < 1:1 - WATCH ONLY"
    if rr_ratio < 1.5:
        if confidence >= 80:
            return "BUY", "A SETUP", "GOOD RECOMMENDATION (RR weak - book full profit at T2)"
        elif confidence >= 70:
            return "BUY", "A SETUP", "GOOD RECOMMENDATION (RR weak - book full profit at T2)"
        else:
            return "WATCHLIST", "B SETUP", "WATCH FOR CONFIRMATION"
    if confidence >= 80:
        return "BUY", "A+ SETUP", "STRONG RECOMMENDATION"
    elif confidence >= 70:
        return "BUY", "A SETUP", "GOOD RECOMMENDATION"
    else:
        return "WATCHLIST", "B SETUP", "WATCH FOR CONFIRMATION"


def format_position(units, capital_used):
    """Format position display per locked rules"""
    lots = units / NIFTY_LOT_SIZE
    return f"{units} units (₹{capital_used:,.0f}) = {lots:.2f} lots"


def analyze_strike(delta, iv_rank, oi_change, volume, spread_percent, rsi, adx,
                   price, vwap, macd_hist, rr_ratio, pattern, at_key_level,
                   bid, ask, atr, direction, capital):
    """Complete single-strike analysis"""

    # Factor scores
    scores = {
        'delta': delta_score(delta),
        'iv': iv_score(iv_rank),
        'oi': oi_score(oi_change, direction, "PE" if delta < 0 else "CE"),
        'liquidity': liquidity_score(volume, spread_percent),
        'technical': technical_score(rsi, adx, price, vwap, macd_hist, direction),
        'rr': rr_score(rr_ratio),
        'candle': candle_score(pattern, at_key_level),
        'iv_rank': iv_rank,
        'counter_trend': False,
        'low_volume': volume < 1000,
        'news_event': False
    }

    # Confidence
    confidence, weighted_total, penalties = calculate_confidence(scores)

    # Entry, SL, Targets
    entry = calculate_entry_price(bid, ask)
    sl = calculate_stop_loss(entry, atr, direction)
    t1, t2, t3 = calculate_targets(entry, atr, direction)

    # RR
    rr = abs(t2 - entry) / abs(entry - sl) if entry != sl else 0

    # Probabilities
    t1_p, t2_p, t3_p = calculate_probabilities(confidence, iv_rank, adx)

    # Kelly sizing
    win_rate = t1_p / 100
    avg_win = abs(t2 - entry)
    avg_loss = abs(entry - sl)
    units, lots, cap_used, kelly_pct = kelly_position_size(win_rate, avg_win, avg_loss, capital, entry)

    # Decision
    action, grade, reason = make_decision(confidence, rr)

    return {
        'scores': scores,
        'weighted_total': weighted_total,
        'confidence': confidence,
        'penalties': penalties,
        'entry': entry,
        'sl': round(sl, 2),
        't1': t1, 't2': t2, 't3': t3,
        'rr': round(rr, 2),
        't1_p': t1_p, 't2_p': t2_p, 't3_p': t3_p,
        'units': units, 'lots': lots, 'capital_used': cap_used, 'kelly_pct': kelly_pct,
        'action': action, 'grade': grade, 'reason': reason
    }


def print_recommendation(spot, result, direction, regime):
    """Print full recommendation in brain.md format"""
    print("=" * 70)
    print(f"BEST PICK: NIFTY {result.get('strike', '24200')} {'PE' if direction=='BEARISH' else 'CE'}")
    print(f"DECISION: {result['action']} | {result['grade']} | {result['reason']}")
    print(f"Spot: {spot} | Regime: {regime}")
    print("-" * 70)
    print(f"Entry: Rs.{result['entry']:.2f} | SL: Rs.{result['sl']:.2f}")
    print(f"T1: Rs.{result['t1']:.2f} ({result['t1_p']}% probability) | Book 50%")
    print(f"T2: Rs.{result['t2']:.2f} ({result['t2_p']}% probability) | Book 30%")
    print(f"T3: Rs.{result['t3']:.2f} ({result['t3_p']}% probability) | Book 20%")
    print(f"Confidence: {result['confidence']:.1f}% ({result['grade']})")
    if result['penalties']:
        print(f"  (Weighted: {result['weighted_total']:.1f}% -> {', '.join(result['penalties'])} = {result['confidence']:.1f}%)")
    print(f"Risk-Reward: 1:{result['rr']:.2f}")
    print("-" * 70)
    print("WHY THIS STRIKE:")
    s = result['scores']
    print(f"  Delta: {s['delta']}/10 | IV: {s['iv']}/10 | OI: {s['oi']}/10 | Liq: {s['liquidity']}/10")
    print(f"  Tech: {s['technical']:.1f}/10 | RR: {s['rr']}/10 | Candle: {s['candle']}/10")
    print("-" * 70)
    pos_str = format_position(result['units'], result['capital_used'])
    print(f"Position: {pos_str} | Kelly: {result['kelly_pct']}%")
    print("=" * 70)


if __name__ == "__main__":
    # Sample data from task
    spot = 24235.3
    delta = -0.52
    iv_rank = 16
    oi_change = 1.7
    volume = 85420
    spread_percent = 1.47
    rsi = 43.5
    adx = 11.3
    price = 24235
    vwap = 24242
    macd_hist = -0.81
    rr_ratio = 1.33
    pattern = "Bearish Engulfing"
    at_key_level = True
    bid = 87.50
    ask = 88.80
    atr = 6.5
    direction = "BEARISH"
    capital = 100000

    result = analyze_strike(
        delta, iv_rank, oi_change, volume, spread_percent, rsi, adx,
        price, vwap, macd_hist, rr_ratio, pattern, at_key_level,
        bid, ask, atr, direction, capital
    )

    # Regime detection
    if adx > 25:
        regime = "TRENDING_BULLISH" if price > vwap else "TRENDING_BEARISH"
    elif adx < 20:
        regime = "RANGE_BOUND"
    else:
        regime = "TRANSITIONAL"

    print_recommendation(spot, result, direction, regime)