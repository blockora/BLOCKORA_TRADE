"""BLOCKORA_TRADE v3 — Black-Scholes greeks for index options.

Used for strike-quality features (delta fit etc.). European, no dividends,
continuous compounding — adequate for NIFTY ranking features (not pricing).
r and T defaults are HEURISTIC (docs/ASSUMPTIONS.md).
"""
from __future__ import annotations

import math

TRADING_DAYS_PER_YEAR = 365.0  # calendar DTE convention for T


def _d1(S: float, K: float, sigma: float, T: float, r: float) -> float:
    return (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_greeks(S: float, K: float, sigma: float, T_years: float,
              r: float = 0.065, option_type: str = "CE") -> dict[str, float | None]:
    """Return delta/gamma/theta/vega (per 1.0 vol point = 1%). None on bad input."""
    if S <= 0 or K <= 0 or sigma <= 0 or T_years <= 0:
        return {"delta": None, "gamma": None, "theta": None, "vega": None}
    sqT = math.sqrt(T_years)
    d1 = _d1(S, K, sigma, T_years, r)
    d2 = d1 - sigma * sqT
    pdf_d1 = _norm_pdf(d1)
    gamma = pdf_d1 / (S * sigma * sqT)
    vega = S * pdf_d1 * sqT / 100.0          # per 1 vol point
    if option_type == "CE":
        delta = _norm_cdf(d1)
        theta = (-(S * pdf_d1 * sigma) / (2 * sqT) - r * K * math.exp(-r * T_years)
                 * _norm_cdf(d2)) / 365.0
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = (-(S * pdf_d1 * sigma) / (2 * sqT) + r * K * math.exp(-r * T_years)
                 * _norm_cdf(-d2)) / 365.0
    return {"delta": round(delta, 4), "gamma": round(gamma, 6),
            "theta": round(theta, 4), "vega": round(vega, 4)}


def bs_price(S: float, K: float, sigma: float, T_years: float,
             r: float = 0.065, option_type: str = "CE") -> float | None:
    if S <= 0 or K <= 0 or sigma <= 0 or T_years <= 0:
        return None
    sqT = math.sqrt(T_years)
    d1 = _d1(S, K, sigma, T_years, r)
    d2 = d1 - sigma * sqT
    if option_type == "CE":
        return S * _norm_cdf(d1) - K * math.exp(-r * T_years) * _norm_cdf(d2)
    return K * math.exp(-r * T_years) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def dte_to_years(dte_days: float) -> float:
    return max(dte_days, 0.04) / TRADING_DAYS_PER_YEAR   # floor ~1 hour to avoid div0
