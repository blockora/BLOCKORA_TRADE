#!/usr/bin/env python3
"""REPRODUCTION SCRIPT — live crash after '=== Adaptive Strike Ranking Started ==='

Builds a deterministic, log-faithful fixture (NOT the production path):
  - Angel LIVE chain: 31 strikes/side, PCR 0.85 (pe_oi < ce_oi), int strike keys
  - Liquidity filter keeps 61 of 62 (removes 1 illiquid)
  - HIGH_VOLATILITY regime: ADX 38.7, RSI 40.1, ATR% 0.12
then calls the exact production call chain:
  ranking_engine.rank(analysis_results, confidence)
and captures the FULL traceback of the live failure.

This mirrors main.py::run_analysis_cycle() line-for-line. It exists only to
reproduce + verify; production uses main.py.
"""
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engines.ranking.strike_ranking_engine import StrikeRankingEngine
from engines.decision.master_decision_engine import MasterDecisionEngine
from engines.confidence.confidence_engine import ConfidenceEngine
from engines.liquidity.liquidity_engine import LiquidityEngine
from engines.regime.market_regime_engine import MarketRegimeEngine


class _Logger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        print(f"WARN | {a[0] if a else ''}")

    def error(self, *a, **k):
        print(f"ERROR | {a[0] if a else ''}")

    def debug(self, *a, **k):
        pass


class _Cfg:
    def get(self, key, default=None):
        return default

    def get_int(self, key, default=0):
        return default

    def get_float(self, key, default=0.0):
        return default

    def get_bool(self, key, default=False):
        return default


def build_live_chain(spot=24503.0, n_strikes=31):
    """Angel-chain shape: int keys, rec fields exactly as main.py::_build_angel_chain."""
    import random
    rng = random.Random(29)  # deterministic; values plausible for PCR 0.85
    atm = round(spot / 50) * 50  # 24500
    ce_data, pe_data = {}, {}
    tot_ce = tot_pe = 0
    for i in range(-15, 16):
        s = atm + i * 50
        ce_oi = 400000 + rng.randrange(-100000, 100000) if i >= 0 else 80000 + rng.randrange(0, 40000)
        pe_oi = int(ce_oi * 0.72) if i >= 0 else 350000 + rng.randrange(-80000, 80000)  # PCR ~0.85
        depth_ce = {"buy": [{"price": 180.0}], "sell": [{"price": 181.5}]}
        depth_pe = {"buy": [{"price": 95.0}], "sell": [{"price": 96.5}]}
        ce_data[s] = {
            "strike": s, "ltp": 175.0 + i * 8, "oi": float(ce_oi), "change_oi": 12000.0,
            "volume": float(ce_oi * 0.1), "iv": 14.2, "bid": 180.0, "ask": 181.5,
            "oi_source": "REAL", "change_oi_source": "CALCULATED",
            "volume_source": "ESTIMATED", "iv_source": "REAL",
            "bid_source": "REAL", "ask_source": "REAL",
        }
        pe_data[s] = {
            "strike": s, "ltp": 92.0 - i * 6, "oi": float(pe_oi), "change_oi": -5000.0,
            "volume": float(pe_oi * 0.1), "iv": 15.1, "bid": 95.0, "ask": 96.5,
            "oi_source": "REAL", "change_oi_source": "CALCULATED",
            "volume_source": "ESTIMATED", "iv_source": "REAL",
            "bid_source": "REAL", "ask_source": "REAL",
        }
        tot_ce += ce_oi
        tot_pe += pe_oi
    # Make exactly ONE strike illiquid (ltp=0) -> liquidity removes 1, keeps 61
    far = atm + 15 * 50
    pe_data[far]["ltp"] = 0.0
    pcr = round(tot_pe / tot_ce, 2)
    return {
        "timestamp": "2026-09-29T10:15:00", "spot_price": spot, "atm_strike": atm,
        "strikes": [atm + i * 50 for i in range(-15, 16)],
        "ce_data": ce_data, "pe_data": pe_data, "pcr": pcr,
        "pcr_source": "CALCULATED", "max_pain": atm - 200, "max_pain_source": "CALCULATED",
        "source": "ANGEL_LIVE",
    }


def build_market_data(spot=24503.0):
    """market_data shape: candles [ts,o,h,l,c,v] + candle dict values; ADX 38.7 RSI 40.1."""
    import random
    rng = random.Random(7)
    candles = []
    px = spot - 25
    for i in range(60):
        ts = f"2026-09-29T09:{15 + i:02d}:00" if i < 45 else f"2026-09-29T10:{i - 45:02d}:00"
        o = px
        h = o + rng.uniform(2, 8)
        l = o - rng.uniform(2, 8)
        c = o + rng.uniform(-6, 7)
        candles.append([ts, o, h, l, c, 0])
        px = c
    candles[-1][4] = spot
    return {
        "ltp": spot, "atr": 12.5, "vix": 17.4, "volume": 0,
        "candles": candles, "candles_15m": [], "candles_1h": [],
        "timestamp": "2026-09-29T10:15:00", "data_source": "LIVE",
    }


def main():
    log = _Logger()
    spot = 24503.0
    market_data = build_market_data(spot)
    chain = build_live_chain(spot)

    print("=" * 70)
    print("STEP 1: live stages before ranking (mirror of run_analysis_cycle)")
    print("=" * 70)

    mde = MasterDecisionEngine(config=_Cfg(), logger=log,
                               confidence_engine=None, risk_engine=None,
                               ranking_engine=None)
    analysis = mde.run_analysis(market_data, chain)
    print(f"analysis_results OK: spot={analysis['market_data']['ltp']} "
          f"regime-ready ctx direction={analysis['trade_context']['direction']}")

    conf_engine = ConfidenceEngine(_Cfg(), log)
    confidence = conf_engine.calculate(analysis)
    print(f"confidence = {confidence['score']} ({confidence['grade']})")

    liq = LiquidityEngine(log)
    chain_f, liq_stats = liq.filter_chain(chain)
    kept_side = len(chain_f["ce_data"]) + len(chain_f["pe_data"])
    print(f"liquidity: removed {liq_stats['removed']}, kept {liq_stats['kept']} "
          f"(ce+pe={kept_side})")
    assert liq_stats["removed"] == 1 and liq_stats["kept"] == 61, \
        f"fixture mismatch: expected removed=1 kept=61, got {liq_stats}"
    analysis["option_chain"] = chain_f
    analysis["liquidity"] = liq_stats

    regime = MarketRegimeEngine(log, _Cfg()).detect(market_data, analysis)
    print(f"regime = {regime['type']} | ADX:{regime['adx']:.1f} RSI:{regime['rsi']:.1f} "
          f"ATR%:{regime['atr_pct']:.2f}")
    analysis["regime"] = regime

    print()
    print("=" * 70)
    print("STEP 2: === Adaptive Strike Ranking Started === (production call)")
    print("=" * 70)
    rk = StrikeRankingEngine(_Cfg(), log)
    try:
        ranked = rk.rank(analysis, confidence)
        print(f"rank() returned: {type(ranked).__name__}")
        # This is the exact line that crashes in main.py after the marker:
        _ce_ranks = ranked.get("ce_rankings", [])
        print("unexpected: no crash — ranked was a dict")
    except AttributeError:
        print(">>> REPRODUCED THE LIVE FAILURE — full traceback:")
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
