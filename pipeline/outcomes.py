"""BLOCKORA_TRADE v3 — outcome tracker (Phase 6).

Replays a recorded plan against the contract's premium candle/quote series
that arrived AFTER the decision timestamp. Deterministic and conservative:

  WIN  = T1 reached before SL within max bars
  LOSS = SL reached before T1 (same-bar ambiguity -> LOSS)
  TIMEOUT = neither within window (never counted as a win)

Only CLOSED bars are consumed; the bar containing the decision timestamp is
skipped to guarantee no look-ahead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.models import Outcome


@dataclass
class PremiumBar:
    ts: str          # bar open time ISO (UTC or IST — consistent within a series)
    open: float
    high: float
    low: float
    close: float


def evaluate_outcome(entry: float, sl: float, t1: float,
                     bars: list[PremiumBar], decision_ts: str,
                     max_bars: int = 24) -> dict[str, Any]:
    """Return {outcome, mfe, mae, bars_to_outcome, exit_reason}."""
    mfe, mae = 0.0, 0.0
    started = False
    n = 0
    for b in bars:
        if not started:
            if b.ts <= decision_ts:
                continue                     # strictly after decision
            started = True
        n += 1
        if n > max_bars:
            break
        mfe = max(mfe, b.high - entry)
        mae = min(mae, b.low - entry)
        hit_t1 = b.high >= t1
        hit_sl = b.low <= sl
        if hit_t1 and hit_sl:
            # same-bar ambiguity -> conservative LOSS (docs/CALIBRATION.md section 3)
            return {"outcome": Outcome.LOSS.value, "mfe": round(mfe, 2),
                    "mae": round(mae, 2), "bars_to_outcome": n,
                    "exit_reason": "SL (same-bar ambiguity, conservative)"}
        if hit_sl:
            return {"outcome": Outcome.LOSS.value, "mfe": round(mfe, 2),
                    "mae": round(mae, 2), "bars_to_outcome": n, "exit_reason": "SL hit"}
        if hit_t1:
            return {"outcome": Outcome.WIN_T1.value, "mfe": round(mfe, 2),
                    "mae": round(mae, 2), "bars_to_outcome": n, "exit_reason": "T1 hit"}
    return {"outcome": Outcome.TIMEOUT.value, "mfe": round(mfe, 2),
            "mae": round(mae, 2), "bars_to_outcome": min(n, max_bars),
            "exit_reason": "timeout (max holding period)"}
