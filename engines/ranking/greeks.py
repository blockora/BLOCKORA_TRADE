"""Black-Scholes Greeks calculator - pure functions, no state, no network.

Delta = P(ITM at expiry under risk-neutral measure) - mathematical proxy
for "up jane ka chance". Only computed when a REAL IV is available;
iv <= 0 / missing always returns None (honest, never fabricated).
"""
import math
from datetime import datetime, timedelta


def days_to_expiry(config):
    """Next weekly expiry date (config analysis.expiry_weekday) minus today.

    Same logic as market_data_engine._current_expiry.
    Returns int days remaining (>=0).
    """
    exp_day = 1
    if config is not None:
        try:
            exp_day = config.get_int("analysis.expiry_weekday", 1)
        except Exception:
            exp_day = 1
    today = datetime.now().date()
    exp = today + timedelta(days=((exp_day - today.weekday()) % 7))
    return max(0, (exp - today).days)


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def black_scholes(spot, strike, days_to_expiry, iv, opt_type, r=0.06):
    """Black-Scholes greeks for a European option.

    Returns dict {delta, theta, gamma, vega} or None when iv is not
    positive (honest: no fake greeks).
    """
    try:
        iv = float(iv)
    except (TypeError, ValueError):
        iv = 0
    if iv is None or iv <= 0:
        return None
    if iv > 1.0:
        iv = iv / 100.0  # NSE impliedVolatility = percent; BS needs decimal
    if spot <= 0 or strike <= 0:
        return None

    T = max(days_to_expiry, 1) / 365.0
    sqrtT = math.sqrt(T)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * T) / (iv * sqrtT)
    d2 = d1 - iv * sqrtT

    if str(opt_type).upper() == "CE":
        delta = _norm_cdf(d1)
        theta = -((spot * _norm_pdf(d1) * iv) / (2 * sqrtT)
                  + r * strike * math.exp(-r * T) * _norm_cdf(d2)) / 365.0
    else:
        delta = _norm_cdf(d1) - 1
        theta = -((spot * _norm_pdf(d1) * iv) / (2 * sqrtT)
                  - r * strike * math.exp(-r * T) * _norm_cdf(-d2)) / 365.0

    gamma = _norm_pdf(d1) / (spot * iv * sqrtT)
    vega = spot * _norm_pdf(d1) * sqrtT / 100.0

    return {
        "delta": round(delta, 4),
        "theta": round(theta, 4),
        "gamma": round(gamma, 6),
        "vega": round(vega, 4),
    }


def get_greeks_from_rec(rec, spot, config, opt_type=None):
    """Compute greeks from a chain record only when IV is REAL (> 0)."""
    if not rec or not isinstance(rec, dict):
        return None
    iv = rec.get("iv", 0)
    try:
        iv = float(iv)
    except (TypeError, ValueError):
        iv = 0
    if iv <= 0:
        return None
    strike = rec.get("strike", 0)
    try:
        strike = float(strike)
    except (TypeError, ValueError):
        strike = 0
    if strike <= 0:
        return None
    _opt = str(opt_type or rec.get("option_type", "") or "").upper()
    if _opt not in ("CE", "PE"):
        return None
    return black_scholes(spot, strike, days_to_expiry(config), iv, _opt)


"""
Pure Python Greeks Calculator - NO scipy required
Works on Termux without compilation
"""
import math


class NSEGreeksCalculator:
    """
    NSE se mila IV use karke Greeks calculate karta hai.
    Pure Python - NO external dependencies except math module.
    """

    RISK_FREE_RATE = 0.06

    @staticmethod
    def _erf(x):
        """
        Error function - pure Python implementation
        scipy.norm.cdf ki jagah use hoga
        """
        # Abramowitz and Stegun approximation
        a1 =  0.254829592
        a2 = -0.284496736
        a3 =  1.421413741
        a4 = -1.453152027
        a5 =  1.061405429
        p  =  0.3275911

        sign = 1 if x >= 0 else -1
        x = abs(x)

        t = 1.0 / (1.0 + p * x)
        y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)

        return sign * y

    @staticmethod
    def _norm_cdf(x):
        """
        Standard Normal CDF - pure Python
        scipy.stats.norm.cdf ki jagah
        """
        return 0.5 * (1.0 + NSEGreeksCalculator._erf(x / math.sqrt(2.0)))

    @staticmethod
    def _norm_pdf(x):
        """
        Standard Normal PDF - pure Python
        scipy.stats.norm.pdf ki jagah
        """
        return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

    @staticmethod
    def _days_to_expiry(expiry_str):
        from datetime import datetime
        try:
            expiry = datetime.strptime(expiry_str, "%d-%b-%Y")
            now = datetime.now()
            diff = expiry - now
            hours_left = diff.total_seconds() / 3600
            return max(hours_left / 24, 0.01)
        except Exception:
            return 7.0

    @staticmethod
    def calculate_greeks(S, K, T_days, iv_percent, option_type='CE'):
        T = max(T_days, 0.01) / 365
        r = NSEGreeksCalculator.RISK_FREE_RATE
        sigma = iv_percent / 100 if iv_percent > 0 else 0.15

        try:
            d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)

            nd1 = NSEGreeksCalculator._norm_cdf(d1)
            nd2 = NSEGreeksCalculator._norm_cdf(d2)
            pdf_d1 = NSEGreeksCalculator._norm_pdf(d1)

            gamma = pdf_d1 / (S * sigma * math.sqrt(T))
            vega = (S * pdf_d1 * math.sqrt(T)) / 100

            if option_type == 'CE':
                delta = nd1
                theta = (-(S * pdf_d1 * sigma) / (2 * math.sqrt(T)) -
                         r * K * math.exp(-r * T) * nd2) / 365
                rho = (K * T * math.exp(-r * T) * nd2) / 100
            else:
                delta = nd1 - 1
                theta = (-(S * pdf_d1 * sigma) / (2 * math.sqrt(T)) +
                         r * K * math.exp(-r * T) * NSEGreeksCalculator._norm_cdf(-d2)) / 365
                rho = -(K * T * math.exp(-r * T) * NSEGreeksCalculator._norm_cdf(-d2)) / 100

            return {
                'delta': round(float(delta), 4),
                'gamma': round(float(gamma), 6),
                'theta': round(float(theta), 4),
                'vega': round(float(vega), 4),
                'rho': round(float(rho), 4),
                'iv': round(float(iv_percent), 2)
            }

        except Exception:
            return {
                'delta': 0, 'gamma': 0, 'theta': 0,
                'vega': 0, 'rho': 0, 'iv': iv_percent
            }

    @classmethod
    def add_greeks_to_df(cls, df):
        if df is None or (hasattr(df, "empty") and df.empty):
            return df

        import pandas as pd
        greeks_list = []
        for _, row in df.iterrows():
            T_days = cls._days_to_expiry(row['expiry'])
            greeks = cls.calculate_greeks(
                S=row['underlying'],
                K=row['strike'],
                T_days=T_days,
                iv_percent=row['iv'],
                option_type=row['type']
            )
            greeks_list.append(greeks)

        greeks_df = pd.DataFrame(greeks_list)
        return pd.concat([df.reset_index(drop=True), greeks_df], axis=1)