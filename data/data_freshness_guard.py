"""Data Freshness Guard - stale data ko analysis se pehle reject karta hai"""
import time
from datetime import datetime


class DataFreshnessGuard:
    # Thresholds for data freshness validation
    # These can be overridden via config:
    #   freshness.spot_max_age_seconds (default: 60)
    #   freshness.chain_max_age_seconds (default: 60)
    # Candles threshold remains 20min (market hours only)
    SPOT_MAX_SEC = 60
    CHAIN_MAX_SEC = 60
    CANDLE_MAX_MIN = 20

    def __init__(self, logger=None):
        self.logger = logger
        self._fetch_time = 0

    def mark_fetch(self):
        self._fetch_time = time.time()

    def check(self, market_data, option_chain, force_market=None):
        reasons = []
        now = time.time()

        # 1) Spot stall detect
        spot_age = now - self._fetch_time
        if spot_age > self.SPOT_MAX_SEC:
            reasons.append(f"Spot stale {spot_age:.1f}s")

        # 2) Spot valid range
        spot = market_data.get("ltp", 0)
        if not spot or spot < 10000 or spot > 40000:
            reasons.append(f"Spot invalid ({spot})")

        # 3) Candle age (sirf market hours me; band hone par skip)
        hm = datetime.now().hour * 60 + datetime.now().minute
        in_market = force_market if force_market is not None else (555 <= hm <= 930)
        candles = market_data.get("candles", [])
        if not candles:
            chain_ts = (option_chain or {}).get("timestamp", "")
            if chain_ts:
                reasons.append("Candles: synthetic baseline (RSI neutral)")
            else:
                reasons.append("No candles")
        elif in_market:
            try:
                last_ts = str(candles[-1][0])
                if last_ts.isdigit():
                    ct = datetime.fromtimestamp(int(last_ts) / (1000 if len(last_ts) > 11 else 1))
                else:
                    ct = datetime.fromisoformat(last_ts)
                # Fix: Dono datetimes ko naive banao (timezone strip karo)
                ct_naive = ct.replace(tzinfo=None) if ct.tzinfo else ct
                now_naive = datetime.now().replace(tzinfo=None)
                age_min = (now_naive - ct_naive).total_seconds() / 60
                if age_min > self.CANDLE_MAX_MIN:
                    reasons.append(f"Candle stale {age_min:.0f}min")
            except Exception:
                pass

        # 4) Option chain timestamp (PATCH 2: fail-safe — missing/invalid/too-old → STALE)
        if in_market:
            chain_ts = (option_chain or {}).get("timestamp", "")
            chain_dt = None
            if chain_ts:
                # ISO format (Angel/NSE/fallback adapters)
                try:
                    chain_dt = datetime.fromisoformat(str(chain_ts))
                except Exception:
                    chain_dt = None
                # Epoch seconds/ms fallback (safe parse)
                if chain_dt is None:
                    try:
                        _v = float(chain_ts)
                        chain_dt = datetime.fromtimestamp(_v / (1000 if _v > 1e12 else 1))
                    except Exception:
                        chain_dt = None
            if chain_dt is None:
                reasons.append("Chain timestamp missing/invalid")
            else:
                try:
                    age = (datetime.now() - chain_dt.replace(tzinfo=None)).total_seconds()
                    if age > self.CHAIN_MAX_SEC:
                        reasons.append(f"Chain stale {age:.1f}s")
                except Exception:
                    reasons.append("Chain timestamp unparsable")

        return (len(reasons) == 0), reasons
