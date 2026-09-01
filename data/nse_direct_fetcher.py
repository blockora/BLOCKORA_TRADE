"""NSE Direct Option Chain Fetcher - real IV + greeks data (free, no auth).

NSE ki public option-chain API se real impliedVolatility (IV) milta hai.
Yahan se mila IV hi greeks calculation me use hota hai (NSEGreeksCalculator).

Multi-source failover:
  1. DIRECT (cookie warmup ke saath) — NSE bot-protection bypass attempt
  2. PROXIES (allorigins/codetabs/corsproxy) — DIRECT block ho to
  3. Sab fail -> None (Angel One fallback main.py me pehle se hai)

Output format = main.py ke _build_angel_chain jaisa dict (dict-based chain).
"""
import time
import requests
from datetime import datetime
from urllib.parse import quote

API_URL = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
HOME_URL = "https://www.nseindia.com/"
OPTION_CHAIN_URL = "https://www.nseindia.com/option-chain"

PROXIES = [
    ("ALLORIGINS", "https://api.allorigins.win/raw?url={URL}"),
    ("CODETABS", "https://api.codetabs.com/v1/proxy?quest={URL}"),
    ("CORSPROXY", "https://corsproxy.io/?url={URL}"),
]


class NSEDirectFetcher:
    def __init__(self, logger=None, timeout=10):
        self.logger = logger
        self.timeout = timeout
        self.working_source = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
            "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
        })
        
        # Source cooldown tracking (Akamai 403/429 protection)
        self._source_cooldowns = {}  # source -> cooldown_until_timestamp
        self._cooldown_seconds = 60

    def _log(self, msg):
        if self.logger is not None:
            self.logger.info(msg)

    def _is_source_cooled_down(self, source):
        """Check if source is in cooldown."""
        until = self._source_cooldowns.get(source, 0)
        if time.time() < until:
            return True
        return False

    def _set_source_cooldown(self, source):
        """Put source in 60s cooldown."""
        self._source_cooldowns[source] = time.time() + self._cooldown_seconds
        self._log(f"NSE source cooldown: {source} (60s)")
        self.logger.debug(f"NSE source cooldown: {source} (60s)")
        self.logger.debug(f"NSE source cooldown: {source} (60s)")
        self.logger.debug(f"NSE source cooldown: {source} (60s)")
        self.logger.debug(f"NSE source cooldown: {source} (60s)")

    def _warmup_cookies(self):
        """NSE bot-protection: pehle homepage + option-chain hit karo (cookies set)."""
        for url in (HOME_URL, OPTION_CHAIN_URL):
            try:
                self.session.get(url, timeout=self.timeout)
            except Exception:
                pass
            time.sleep(1.0)

    def _direct_fetch(self):
        self._warmup_cookies()
        self.session.headers.update({
            "Accept": "*/*",
            "Referer": OPTION_CHAIN_URL,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-Requested-With": "XMLHttpRequest",
        })
        r = self.session.get(API_URL, timeout=self.timeout)
        if r.status_code in (403, 429):
            self._set_source_cooldown("DIRECT")
            return None
        if r.status_code == 200:
            # HTML guard: check response starts with '{' or '['
            text = r.text.strip()
            if not (text.startswith('{') or text.startswith('[')):
                self._log("DIRECT: HTML error page detected, treating as failure")
                return None
            try:
                data = r.json()
            except Exception:
                return None
            if data and isinstance(data, dict) and data.get("records"):
                return data
        return None

    def _proxy_fetch(self, tpl, source_name):
        # Check cooldown before attempting
        if self._is_source_cooled_down(source_name):
            return None
        
        proxy_url = tpl.replace("{URL}", quote(API_URL, safe=""))
        r = requests.get(proxy_url, timeout=self.timeout, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0"
        })
        if r.status_code in (403, 429):
            self._set_source_cooldown(source_name)
            return None
        if r.status_code == 200:
            # HTML guard: check response starts with '{' or '['
            text = r.text.strip()
            if not (text.startswith('{') or text.startswith('[')):
                self._log(f"{source_name}: HTML error page detected, treating as failure")
                return None
            try:
                data = r.json()
            except Exception:
                return None
            if data and isinstance(data, dict) and data.get("records"):
                return data
        return None

    def _fetch_json(self):
        sources = [("DIRECT", lambda: self._direct_fetch())]
        
        # 2s delay before proxy attempts
        time.sleep(2.0)
        for name, tpl in PROXIES:
            sources.append((name, lambda t=tpl, n=name: self._proxy_fetch(t, n)))
        
        # Filter out cooled-down sources
        sources = [(name, fetcher) for name, fetcher in sources if not self._is_source_cooled_down(name)]

        if self.working_source:
            sources.sort(key=lambda s: 0 if s[0] == self.working_source else 1)

        for name, fetcher in sources:
            try:
                data = fetcher()
                if data:
                    self.working_source = name
                    self._log(f"NSE Direct connected via {name}")
                    return data
            except Exception:
                continue
        return None

    def fetch_option_chain(self, symbol="NIFTY"):
        """Return dict chain (same format as main._build_angel_chain) or None."""
        if symbol and symbol.upper() != "NIFTY":
            return None
        data = self._fetch_json()
        if not data:
            return None
        records = data.get("records", {})
        items = records.get("data", [])
        if not items:
            return None

        spot = records.get("underlyingValue", 0) or 0
        expiry = None
        ce_data, pe_data = {}, {}
        tot_ce, tot_pe = 0, 0
        for it in items:
            strike = it.get("strikePrice", 0)
            if "CE" in it:
                ce = it["CE"]
                if expiry is None and ce.get("expiryDate"):
                    expiry = ce.get("expiryDate")
                ce_data[strike] = {
                    "strike": strike, "ltp": ce.get("lastPrice", 0),
                    "oi": ce.get("openInterest", 0),
                    "change_oi": ce.get("changeinOpenInterest", 0),
                    "volume": ce.get("totalTradedVolume", 0),
                    "iv": ce.get("impliedVolatility", 0),
                    "bid": ce.get("bidprice", 0), "ask": ce.get("askPrice", 0),
                    "expiry": ce.get("expiryDate", "UNAVAILABLE"),
                    "oi_source": "REAL" if ce.get("openInterest", 0) > 0 else "MISSING",
                    "iv_source": "REAL" if ce.get("impliedVolatility", 0) > 0 else "UNKNOWN",
                }
                tot_ce += ce.get("openInterest", 0)
            if "PE" in it:
                pe = it["PE"]
                if expiry is None and pe.get("expiryDate"):
                    expiry = pe.get("expiryDate")
                pe_data[strike] = {
                    "strike": strike, "ltp": pe.get("lastPrice", 0),
                    "oi": pe.get("openInterest", 0),
                    "change_oi": pe.get("changeinOpenInterest", 0),
                    "volume": pe.get("totalTradedVolume", 0),
                    "iv": pe.get("impliedVolatility", 0),
                    "bid": pe.get("bidprice", 0), "ask": pe.get("askPrice", 0),
                    "expiry": pe.get("expiryDate", "UNAVAILABLE"),
                    "oi_source": "REAL" if pe.get("openInterest", 0) > 0 else "MISSING",
                    "iv_source": "REAL" if pe.get("impliedVolatility", 0) > 0 else "UNKNOWN",
                }
                tot_pe += pe.get("openInterest", 0)

        if not ce_data or not pe_data:
            return None

        strikes = sorted(set(list(ce_data.keys()) + list(pe_data.keys())))
        pcr = round(tot_pe / tot_ce, 2) if tot_ce else 1.0
        return {
            "timestamp": datetime.now().isoformat(),
            "spot_price": spot,
            "atm_strike": round(spot / 50) * 50 if spot else 0,
            "strikes": strikes,
            "ce_data": ce_data, "pe_data": pe_data,
            "pcr": pcr,
            "pcr_source": "CALCULATED",
            "max_pain": self._calc_max_pain(strikes, ce_data, pe_data),
            "max_pain_source": "CALCULATED",
            "expiry": expiry,
            "source": "NSE_LIVE",
        }

    def _calc_max_pain(self, strikes, ce_data, pe_data):
        min_loss, max_pain = float('inf'), (strikes[0] if strikes else 0)
        for strike in strikes:
            loss = 0
            for s in strikes:
                c_oi = ce_data.get(s, {}).get("oi", 0)
                p_oi = pe_data.get(s, {}).get("oi", 0)
                if s < strike:
                    loss += c_oi * (strike - s)
                if s > strike:
                    loss += p_oi * (s - strike)
            if loss < min_loss:
                min_loss, max_pain = loss, strike
        return max_pain