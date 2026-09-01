"""Option Chain Engine v3 - Multi-Source Failover (NSE + Proxies + Derived Fallback)"""
import time
import requests
from datetime import datetime
from urllib.parse import quote

try:
    from data.nse_direct_fetcher import NSEDirectFetcher
    NSE_DIRECT_AVAILABLE = True
except ImportError:
    NSE_DIRECT_AVAILABLE = False
    NSEDirectFetcher = None


class OptionChainEngine:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.option_chain_data = {}
        self.session = None
        self.last_fetch = 0
        self.fetch_gap = 30
        self.nse_blocked = False
        self.working_source = None
        self._prev_timestamp = None

    def _fix_timestamp(self, chain):
        """Ensure chain has a valid timestamp; apply fallbacks if missing/invalid."""
        if not chain or not isinstance(chain, dict):
            return chain
        ts = chain.get("timestamp", "")
        # Try parsing the existing timestamp
        try:
            import datetime as _dt
            _dt.datetime.fromisoformat(str(ts))
            self._prev_timestamp = ts
            return chain
        except Exception:
            pass
        # Fallback 1: use previous cycle's timestamp
        if self._prev_timestamp:
            self.logger.info(f"Using fallback timestamp: {self._prev_timestamp}")
            chain["timestamp"] = self._prev_timestamp
            return chain
        # Fallback 2: use current IST time
        now_ist = datetime.now().isoformat()
        self.logger.info(f"Using fallback timestamp: {now_ist}")
        chain["timestamp"] = now_ist
        self._prev_timestamp = now_ist
        return chain

    def initialize(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
        })
        try:
            self.session.get("https://www.nseindia.com/", timeout=10)
            self.session.get("https://www.nseindia.com/option-chain", timeout=10)
        except Exception:
            pass
        self.logger.info("Option Chain Engine initialized (Multi-Source)")

    # ══════════ SOURCE FETCHERS ══════════
    def _direct_nse(self, url):
        self.session.headers.update({
            "Accept": "*/*",
            "Referer": "https://www.nseindia.com/option-chain",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        })
        r = self.session.get(url, timeout=8)
        if r.status_code == 200:
            return r.json()
        return None

    def _proxy_fetch(self, url, proxy_tpl):
        proxy_url = proxy_tpl.replace("{URL}", quote(url, safe=""))
        r = requests.get(proxy_url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0"
        })
        if r.status_code == 200:
            try:
                return r.json()
            except Exception:
                return None
        return None

    def _fetch_chain_json(self):
        url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
        sources = []
        if not self.nse_blocked:
            sources.append(("DIRECT", lambda: self._direct_nse(url)))
        sources.append(("ALLORIGINS", lambda: self._proxy_fetch(url, "https://api.allorigins.win/raw?url={URL}")))
        sources.append(("CODETABS", lambda: self._proxy_fetch(url, "https://api.codetabs.com/v1/proxy?quest={URL}")))
        sources.append(("CORSPROXY", lambda: self._proxy_fetch(url, "https://corsproxy.io/?url={URL}")))

        # NSE Direct Fetcher (real IV) — cookie warmup + dedicated failover
        if NSE_DIRECT_AVAILABLE and NSEDirectFetcher is not None:
            sources.append(("NSEDIRECT", lambda: self._nse_direct_chain()))

        # Jo source pehle kaam kar chuka hai, use pehle try karo
        if self.working_source:
            sources.sort(key=lambda s: 0 if s[0] == self.working_source else 1)

        for name, fetcher in sources:
            try:
                data = fetcher()
                if data and isinstance(data, dict):
                    # NSE dict chain (ce_data/pe_data) — already built format
                    if "ce_data" in data and "pe_data" in data:
                        self.working_source = name
                        self.logger.info(f"NSE Option Chain connected via {name}")
                        return {"_chain_dict": data}
                    # Raw NSE records (records.data) — build later
                    if "records" in data:
                        self.working_source = name
                        self.logger.info(f"NSE Option Chain connected via {name}")
                        return data
            except Exception:
                continue

        self.nse_blocked = True
        return None

    def _nse_direct_chain(self):
        """NSEDirectFetcher: real IV wali NSE chain (dict format)."""
        try:
            f = NSEDirectFetcher(logger=self.logger)
            chain = f.fetch_option_chain("NIFTY")
            if not chain or not chain.get("ce_data"):
                return None
            self.working_source = "NSEDIRECT"
            self.logger.info(f"NSE Direct chain ready: {len(chain['ce_data'])} strikes | PCR {chain.get('pcr')}")
            return chain
        except Exception:
            return None

    # ══════════ CHAIN BUILDER ══════════
    def _build_chain(self, spot_price):
        data = self._fetch_chain_json()
        if not data:
            return None

        # NSE Direct dict chain — already built (real IV), return as-is
        if "_chain_dict" in data:
            return data["_chain_dict"]

        items = data.get("records", {}).get("data", [])
        if not items:
            return None

        atm_strike = round(spot_price / 50) * 50
        nearby = self.config.get_int("strikes.nearby_count", 5)
        valid_strikes = [atm_strike + (i * 50) for i in range(-nearby, nearby + 1)]

        ce_data, pe_data = {}, {}
        total_ce_oi, total_pe_oi = 0, 0

        for item in items:
            strike = item.get("strikePrice", 0)
            if strike not in valid_strikes:
                continue
            if "CE" in item:
                ce = item["CE"]
                ce_data[strike] = {
                    "strike": strike, "ltp": ce.get("lastPrice", 0),
                    "oi": ce.get("openInterest", 0), "change_oi": ce.get("changeinOpenInterest", 0),
                    "volume": ce.get("totalTradedVolume", 0), "iv": ce.get("impliedVolatility", 0),
                    "bid": ce.get("bidprice", 0), "ask": ce.get("askPrice", 0),
                    "expiry": ce.get("expiryDate", "UNAVAILABLE"),
                }
                total_ce_oi += ce.get("openInterest", 0)
            if "PE" in item:
                pe = item["PE"]
                pe_data[strike] = {
                    "strike": strike, "ltp": pe.get("lastPrice", 0),
                    "oi": pe.get("openInterest", 0), "change_oi": pe.get("changeinOpenInterest", 0),
                    "volume": pe.get("totalTradedVolume", 0), "iv": pe.get("impliedVolatility", 0),
                    "bid": pe.get("bidprice", 0), "ask": pe.get("askPrice", 0),
                    "expiry": pe.get("expiryDate", "UNAVAILABLE"),
                }
                total_pe_oi += pe.get("openInterest", 0)

        if not ce_data or not pe_data:
            return None

        pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi else 1.0
        return {
            "timestamp": datetime.now().isoformat(),
            "spot_price": spot_price,
            "atm_strike": atm_strike,
            "strikes": valid_strikes,
            "ce_data": ce_data, "pe_data": pe_data,
            "pcr": pcr,
            "max_pain": self._calc_max_pain(valid_strikes, ce_data, pe_data),
            "source": self.working_source or "NSE",
        }

    def _calc_max_pain(self, strikes, ce_data, pe_data):
        min_loss, max_pain = float('inf'), (strikes[0] if strikes else 0)
        for strike in strikes:
            loss = 0
            for s in strikes:
                c_oi = ce_data.get(s, {}).get("oi", 0)
                p_oi = pe_data.get(s, {}).get("oi", 0)
                if s < strike: loss += c_oi * (strike - s)
                if s > strike: loss += p_oi * (s - strike)
            if loss < min_loss:
                min_loss, max_pain = loss, strike
        return max_pain

    # ══════════ MAIN ENTRY ══════════
    def get_option_chain(self, market_data):
        try:
            if not market_data:
                return None
            spot_price = market_data.get("ltp", 0)
            if spot_price == 0:
                return None

            now = time.time()
            if self.option_chain_data and (now - self.last_fetch) < self.fetch_gap:
                self.option_chain_data["spot_price"] = spot_price
                return self._fix_timestamp(self.option_chain_data)

            chain = self._build_chain(spot_price)
            if chain:
                self.option_chain_data = chain
                self.last_fetch = now
                return self._fix_timestamp(chain)

            if self.option_chain_data:
                self.option_chain_data["spot_price"] = spot_price
                return self._fix_timestamp(self.option_chain_data)
            return None
        except Exception:
            if self.option_chain_data:
                self.option_chain_data["spot_price"] = market_data.get("ltp", 0)
                return self._fix_timestamp(self.option_chain_data)
            return None

    def shutdown(self):
        self.logger.info("Option Chain Engine shutdown")
