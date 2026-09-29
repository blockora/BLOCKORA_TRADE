"""BLOCKORA_TRADE v3 — data adapters for offline/replay mode.

SyntheticSource generates a deterministic, reproducible market scenario
(seeded random walk) with a consistent option chain — used for tests and
pipeline verification. CSVSource replays recorded candles from CSV.

Live broker adapters plug in later against the same core.models types;
neither adapter ever fabricates missing fields (None stays None).
Candles are CLOSED bars only: the series is anchored so the newest bar
is closed at the decision snapshot (`as_of`) — no future data, ever.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from core.models import Candle, DataQuality, OptionQuote, UnderlyingTick

IST = ZoneInfo("Asia/Kolkata")


class SyntheticSource:
    """Deterministic NIFTY-like market with NIFTY-style 50-step option chain.

    regime: "bull" | "bear" | "range" controls drift.
    as_of: decision snapshot time; the candle series only contains bars
        closed at or before this instant (session-anchored backward walk).
    """

    def __init__(self, seed: int = 42, spot: float = 24500.0,
                 regime: str = "range", bars: int = 120,
                 as_of: datetime | None = None) -> None:
        self.rng = random.Random(seed)
        self.base_spot = spot
        self.regime = regime
        self.bars = bars
        self._as_of = as_of.replace(tzinfo=IST) if as_of and as_of.tzinfo is None else as_of
        self._candles = self._gen_candles()
        drift = {"bull": 0.06, "bear": -0.06, "range": 0.0}[regime]
        self._spot = self._candles[-1].close * (1 + drift * self.rng.random())

    # -- candles ---------------------------------------------------------
    def _gen_candles(self) -> list[Candle]:
        price = self.base_spot
        drift = {"bull": 0.0009, "bear": -0.0009, "range": 0.0}[self.regime]
        as_of = self._as_of or datetime.now(IST)
        # Last CLOSED bar open: floor as_of to the 5m grid, then back one bar.
        # (Aligned NSE 5m slots: 09:15, 09:20, … 15:25.)
        last_open = as_of.replace(second=0, microsecond=0)
        last_open -= timedelta(minutes=(last_open.minute % 5) + 5)
        # Walk backwards collecting session slots (Mon-Fri 09:15 .. <15:30)
        # until we have `bars` closed bars — never a bar in the future.
        opens: list[datetime] = []
        cur = last_open
        guard = 0
        while len(opens) < self.bars and guard < self.bars * 40:
            guard += 1
            if cur.weekday() < 5 and time(9, 15) <= cur.time() < time(15, 30):
                opens.append(cur)
            cur -= timedelta(minutes=5)
        opens.reverse()

        out: list[Candle] = []
        for bar_ts in opens:
            o = price
            step = self.rng.gauss(drift, 0.0011) * price
            c = o + step
            hi = max(o, c) + abs(self.rng.gauss(0, 0.0006)) * price
            lo = min(o, c) - abs(self.rng.gauss(0, 0.0006)) * price
            out.append(Candle(
                symbol="NIFTY", timeframe="5m", bar_ts=bar_ts.isoformat(),
                open=round(o, 2), high=round(hi, 2), low=round(lo, 2),
                close=round(c, 2), volume=int(100000 + self.rng.random() * 90000),
                quality=DataQuality(source="SYNTH", data_ts=bar_ts.isoformat(),
                                    received_ts=bar_ts.isoformat(), latency_ms=1.0),
            ))
            price = c
        return out

    def get_candles(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        return self._candles[-count:]

    # -- underlying ------------------------------------------------------
    def get_underlying_tick(self, symbol: str) -> UnderlyingTick:
        q = DataQuality(source="SYNTH", data_ts=datetime.now(IST).isoformat(),
                        received_ts=datetime.now(IST).isoformat(), latency_ms=1.0)
        change = (self._spot - self._candles[0].close) / self._candles[0].close * 100
        return UnderlyingTick(symbol, round(self._spot, 2), round(change, 3), q)

    # -- chain ------------------------------------------------------------
    def _quote(self, strike: float, opt: str, spot: float, expiry_days: float) -> OptionQuote:
        T = max(expiry_days, 0.5) / 365.0
        sigma = 0.12
        intrinsic = max(0.0, (spot - strike) if opt == "CE" else (strike - spot))
        approx = intrinsic + spot * sigma * math.sqrt(T) * 0.4
        premium = max(approx, 0.55)
        bid = round(max(premium - 0.6, 0.05), 2)
        ask = round(premium + 0.6, 2)
        ltp = round((bid + ask) / 2, 2)
        moneyness = (strike - spot) if opt == "CE" else (spot - strike)
        base_oi = 150_000 if abs(moneyness) <= 150 else 60_000
        if self.regime == "bull":
            change = int(base_oi * (0.03 if opt == "CE" else -0.01) * self.rng.random() * 10)
        elif self.regime == "bear":
            change = int(base_oi * (-0.01 if opt == "CE" else 0.03) * self.rng.random() * 10)
        else:
            change = int(base_oi * (0.01 if self.rng.random() > 0.5 else -0.01))
        q = DataQuality(source="SYNTH", data_ts=datetime.now(IST).isoformat(),
                        received_ts=datetime.now(IST).isoformat(), latency_ms=1.0)
        return OptionQuote(
            strike=float(strike), option_type=opt, expiry="NEXT_WEEKLY",
            ltp=ltp, bid=bid, ask=ask, iv=round(sigma * 100, 2),
            volume=int(6000 + self.rng.random() * 40000),
            oi=base_oi, change_oi=change, quality=q,
        )

    def get_chain(self, expiry: str, strikes: list[float]) -> list[OptionQuote]:
        spot = self._spot
        return [self._quote(s, o, spot, 6.0) for s in strikes for o in ("CE", "PE")]

    def is_healthy(self) -> bool:
        return True

    def is_market_open(self, now=None) -> bool:
        from core.session import is_market_open
        return is_market_open(now)


def strikes_around_atm(spot: float, step: float = 50.0, window: int = 3) -> list[float]:
    atm = round(spot / step) * step
    return [atm + step * i for i in range(-window, window + 1)]
