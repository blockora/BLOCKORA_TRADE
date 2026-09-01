"""Jugaad Data IV Fetcher - real NSE implied volatility (IV) without IP blocking.

NSE ki public API directly block hoti hai (Akamai 403/404) - direct scrape se IP
block hone ka risk hai. Jugaad-data library NSE ke public endpoints ko alag
networking (cookie warmup + rate-limiting friendly) se access karti hai.

Yahan se milta hai:
  - REAL impliedVolatility per strike (CE + PE)
  - Real LTP, OI, volume (secondary - Angel se milega)
  - Current weekly expiry (25-Aug-2026 etc.)

Fail-safe: agar jugaad-data fetch fail ho ya IV missing ho -> None/0 return,
Angel One pipeline pe koi asar nahi (IV sirf enrich karta hai, kabhi crash nahi).
"""
import time
from datetime import datetime

try:
    from jugaad_data.nse import NSELive
    _JUGGAD_AVAILABLE = True
except Exception:
    _JUGGAD_AVAILABLE = False


class JugaadIVFetcher:
    """NIFTY option chain se real IV fetch karta hai (jugaad-data ke through)."""

    def __init__(self, logger=None, expiry=None, cache_ttl=55.0):
        self.logger = logger
        self.expiry = expiry  # optional: '25-Aug-2026' format override
        self.cache_ttl = cache_ttl
        self._chain_cache = None
        self._chain_time = 0.0
        self._iv_map = {}  # (option_type, strike) -> iv
        self._last_fetch_ok = False
        self._working = _JUGGAD_AVAILABLE

    def _log(self, msg):
        if self.logger is not None:
            self.logger.info(msg)

    def _fetch_chain(self):
        """Fresh NIFTY option chain fetch (jugaad-data). None on failure."""
        if not _JUGGAD_AVAILABLE:
            return None
        try:
            n = NSELive()
            oc = n.index_option_chain("NIFTY")
            if not oc or not isinstance(oc, dict):
                return None
            rec = oc.get("records") or {}
            if not rec.get("data"):
                return None
            self._last_fetch_ok = True
            return rec
        except Exception:
            return None

    def _get_cached_chain(self):
        """Chain cache (TTL window) - har cycle me extra API call se bachna."""
        now = time.time()
        if self._chain_cache and (now - self._chain_time) < self.cache_ttl:
            return self._chain_cache
        chain = self._fetch_chain()
        if chain is not None:
            self._chain_cache = chain
            self._chain_time = now
        return chain

    def _build_iv_map(self, chain):
        """Chain records se (type, strike) -> iv map banata hai (expiry match ke saath)."""
        iv_map = {}
        target = self.expiry
        expiry_dates = chain.get("expiryDates") or []
        for it in chain.get("data") or []:
            s = it.get("strikePrice")
            if s is None:
                continue
            exp = it.get("expiryDate") or it.get("expiryDates")
            if target and exp and target not in str(exp):
                continue
            for opt_type, key in (("CE", "CE"), ("PE", "PE")):
                side = it.get(key)
                if not side:
                    continue
                iv = side.get("impliedVolatility")
                try:
                    iv_f = float(iv) if iv is not None else 0.0
                except (TypeError, ValueError):
                    iv_f = 0.0
                if iv_f > 0:
                    iv_map[(opt_type, int(s))] = iv_f
        if not target and expiry_dates:
            # default: pehli (nearest) expiry
            self.expiry = expiry_dates[0]
            self._log(f"JugaadIVFetcher expiry auto-set: {self.expiry}")
        return iv_map

    def refresh(self):
        """Full refresh - chain fetch + IV map build. True if any IV found."""
        chain = self._get_cached_chain()
        if chain is None:
            self._working = False
            return False
        self._iv_map = self._build_iv_map(chain)
        self._working = bool(self._iv_map)
        return self._working

    def get_iv(self, option_type, strike):
        """Strike ka real IV. Missing/failed -> 0.0 (Angel pipeline ko damage nahi)."""
        try:
            if not self._working:
                return 0.0
            if not self._iv_map:
                self.refresh()
            return float(self._iv_map.get((option_type, int(strike)), 0.0))
        except Exception:
            return 0.0

    def get_iv_map(self):
        """Purra (CE/PE) IV map for batch fill."""
        if not self._iv_map:
            self.refresh()
        return dict(self._iv_map)

    @property
    def working(self):
        return self._working

    @property
    def last_fetch_ok(self):
        return self._last_fetch_ok

    def shutdown(self):
        """Cleanup - sessions close karne ke liye (agar ho)."""
        self._chain_cache = None
        self._iv_map = {}


# ---- standalone test helper ----
if __name__ == "__main__":
    f = JugaadIVFetcher()
    ok = f.refresh()
    print("jugaad available:", _JUGGAD_AVAILABLE)
    print("refresh ok:", ok, "| working:", f.working)
    if ok:
        for (t, s), iv in sorted(f.get_iv_map().items()):
            if s % 50 == 0 and 24000 <= s <= 24600:
                print(f"  {t} {s}: IV={iv}")