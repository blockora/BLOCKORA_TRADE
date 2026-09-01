"""Market Data Engine - Live Candle Update + Error Suppression"""
import io
import sys
import time
import logging
import requests
from datetime import datetime, timedelta

logging.getLogger('smartConnect').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)
logging.getLogger('requests').setLevel(logging.CRITICAL)
logging.getLogger('urllib3.connectionpool').setLevel(logging.CRITICAL)


class MarketDataEngine:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.connected = False
        self.client = None
        self.live_data = {}
        self.feed_token = None
        self.jwt_token = None
        self.historical_candles = []
        self.last_candle_time = None
        self.last_api_call = 0
        self.min_api_gap = 4.0
        self.candles_15m = []
        self.candles_1h = []
        self.last_15m_time = None
        self.last_1h_time = None
        
        # Rate limiting state
        self._api_call_times = []  # Rolling minute timestamps
        self._backoff_until = 0
        self._backoff_delay = 0
        
        # Session management
        self._login_time = 0
        self._session_max_age = 50 * 60  # 50 minutes
        
        # Scrip master cache
        self._tokens_loaded = False
        self._tokens_time = 0
        self._tokens = {}
        
        # Freshness flag for DataFreshnessGuard
        self._last_get_live_fresh = False
    def _rate_limit_wait(self):
        """Wait with exponential backoff and rolling minute rate limiting."""
        now = time.time()
        
        # Check if in backoff period
        if now < self._backoff_until:
            wait = self._backoff_until - now
            self.logger.debug(f"Rate limiter: waiting {wait:.1f}s before next request (backoff)")
            time.sleep(wait)
            self.last_api_call = time.time()
            return
        
        # Rolling minute request counter
        self._api_call_times = [t for t in self._api_call_times if now - t < 60]
        if len(self._api_call_times) >= 12:
            self.min_api_gap = 6.0
            self.logger.debug(f"Rate limiter: throttling to 6s ({len(self._api_call_times)} calls/min)")
        else:
            self.min_api_gap = 4.0
        
        # Normal wait
        elapsed = now - self.last_api_call
        if elapsed < self.min_api_gap:
            wait = self.min_api_gap - elapsed
            self.logger.debug(f"Rate limiter: waiting {wait:.1f}s before next request")
            time.sleep(wait)
        
        self.last_api_call = time.time()
        self._api_call_times.append(time.time())

    def _trigger_backoff(self):
        """Call on 429/timeout to pause for 30s."""
        self._backoff_until = time.time() + 30
        self._backoff_delay = 2
        self.logger.debug("Rate limiter: pausing 30s after 429/timeout")

    def _silent_call(self, func, *args, **kwargs):
        """Call SmartAPI while suppressing ALL stdout, stderr, and logging.
        Detects 429/timeout and triggers backoff."""
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        logging.disable(logging.CRITICAL)
        
        try:
            result = func(*args, **kwargs)
        except requests.exceptions.ReadTimeout:
            self._trigger_backoff()
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            logging.disable(logging.NOTSET)
            raise
        except requests.exceptions.HTTPError as e:
            if hasattr(e, 'response') and e.response is not None and e.response.status_code == 429:
                self._trigger_backoff()
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            logging.disable(logging.NOTSET)
            raise
        except Exception as e:
            err_str = str(e).lower()
            if '429' in err_str or 'too many' in err_str or 'rate limit' in err_str:
                self._trigger_backoff()
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            logging.disable(logging.NOTSET)
            raise
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            logging.disable(logging.NOTSET)
        return result

    def initialize(self):
        try:
            from SmartApi import SmartConnect
            import pyotp

            api_key = self.config.get("ANGEL_API_KEY")
            client_id = self.config.get("ANGEL_CLIENT_ID")
            password = self.config.get("ANGEL_PASSWORD")
            totp_secret = self.config.get("ANGEL_TOTP_SECRET")

            if not all([api_key, client_id, password, totp_secret]):
                raise ValueError("Missing Angel One credentials")

            self.client = SmartConnect(api_key=api_key)
            totp = pyotp.TOTP(totp_secret).now()
            data = None
            
            # Exponential backoff: 2s, 4s, 8s
            backoff = 2
            for attempt in range(3):
                try:
                    data = self._silent_call(
                        self.client.generateSession, client_id, password, totp
                    )
                    break
                except Exception as e:
                    self.logger.warning(f"Login attempt {attempt+1}/3 failed: {e}")
                    if attempt == 2:
                        raise
                    self.logger.debug(f"Rate limiter: waiting {backoff}s before retry")
                    time.sleep(backoff)
                    backoff *= 2
            
            if data and data.get("status"):
                self.connected = True
                self.feed_token = data["data"]["feedToken"]
                self.jwt_token = data["data"]["jwtToken"]
                self._login_time = time.time()
                self.logger.info("Angel One SmartAPI connected successfully")
            else:
                self.logger.warning(f"Angel login failed: {data.get('message') if data else 'No response'}; continuing with fallback data")
                self.connected = False
        except Exception as e:
            self.logger.error(f"Market data init error: {str(e)}")
            self.connected = False
            raise

    def _force_load_historical(self):
        max_retries = 3
        backoff = 2
        for attempt in range(max_retries):
            try:
                self._rate_limit_wait()
                now = datetime.now()
                from_date = now - timedelta(days=7)

                params = {
                    "exchange": "NSE",
                    "symboltoken": "99926000",
                    "interval": "FIVE_MINUTE",
                    "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
                    "todate": now.strftime("%Y-%m-%d %H:%M")
                }

                historical_data = self._silent_call(
                    self.client.getCandleData, params
                )

                if historical_data and historical_data.get("status"):
                    raw_data = historical_data["data"]
                    if isinstance(raw_data, dict):
                        candles = raw_data.get("candles", [])
                    elif isinstance(raw_data, list):
                        candles = raw_data
                    else:
                        candles = []

                    if len(candles) > 0:
                        self.historical_candles = candles
                        self.last_candle_time = now.replace(
                            minute=(now.minute // 5) * 5, second=0, microsecond=0
                        )
                        self.logger.info(f"Historical data loaded: {len(candles)} candles")
                        return True
            except Exception as e:
                self.logger.warning(f"Historical attempt {attempt+1}/3 failed: {e}")
                if attempt < max_retries - 1:
                    self.logger.debug(f"Rate limiter: waiting {backoff}s before retry")
                    time.sleep(backoff)
                    backoff *= 2
        return False

    def _maybe_update_historical(self):
        now = datetime.now()
        current_candle_time = now.replace(
            minute=(now.minute // 5) * 5, second=0, microsecond=0
        )

        if self.last_candle_time == current_candle_time and len(self.historical_candles) > 0:
            return

        try:
            self._rate_limit_wait()
            from_date = now - timedelta(days=7)
            params = {
                "exchange": "NSE", "symboltoken": "99926000", "interval": "FIVE_MINUTE",
                "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
                "todate": now.strftime("%Y-%m-%d %H:%M")
            }
            historical_data = self._silent_call(self.client.getCandleData, params)

            if historical_data and historical_data.get("status"):
                raw_data = historical_data["data"]
                candles = raw_data if isinstance(raw_data, list) else raw_data.get("candles", [])
                if len(candles) > 0:
                    self.historical_candles = candles
                    self.last_candle_time = current_candle_time
        except Exception:
            pass

    def get_live_data(self):
        self._last_get_live_fresh = False  # default = cached/stale
        try:
            # Proactive session refresh after 50 minutes
            if self.connected and time.time() - self._login_time > self._session_max_age:
                self.logger.info("Session refresh: re-login")
                self.initialize()
            
            if not self.connected:
                return None
            self._rate_limit_wait()
            ltp_data = self._silent_call(
                self.client.ltpData, "NSE", "NIFTY 50", "99926000"
            )

            if ltp_data and ltp_data.get("status"):
                self._last_get_live_fresh = True  # fresh broker response
                current_ltp = float(ltp_data["data"]["ltp"])
                current_high = float(ltp_data["data"].get("high", current_ltp))
                current_low = float(ltp_data["data"].get("low", current_ltp))
                
                self.live_data = {
                    "timestamp": datetime.now().isoformat(),
                    "symbol": "NIFTY",
                    "ltp": current_ltp,
                    "open": float(ltp_data["data"].get("open", 0)),
                    "high": current_high,
                    "low": current_low,
                    "close": float(ltp_data["data"].get("close", 0)),
                    "exchange": "NSE",
                    "market_status": "OPEN",
                    "data_source": "LIVE"
                }

                # P0-2: ltpData ka high/low = DAY high/low (current 5-min candle ke NAHI).
                # Candle ko sirf current LTP se update karo — day values inject MAT karo.
                if self.historical_candles and len(self.historical_candles) > 0:
                    last_candle = self.historical_candles[-1]
                    # Format: [timestamp, open, high, low, close, volume]
                    last_candle[2] = max(float(last_candle[2]), current_ltp)  # High = max(existing, LTP)
                    last_candle[3] = min(float(last_candle[3]), current_ltp)  # Low = min(existing, LTP)
                    last_candle[4] = current_ltp                              # Close = LTP

                self._maybe_update_historical()
                self.update_mtf_candles()
                self.live_data["candles_15m"] = self.candles_15m
                self.live_data["candles_1h"] = self.candles_1h
                self.live_data["candles"] = self.historical_candles
                return self.live_data

            return None

        except Exception as e:
            err_str = str(e).lower()
            # Auth error → immediate re-login
            if any(k in err_str for k in ('token', 'auth', 'unauthorized', 'session', 'login', 'jwt', 'invalid')):
                self.logger.info("Session refresh: re-login (auth error)")
                self.connected = False
                self.initialize()
            
            # Mark stale so DataFreshnessGuard flags it
            self._last_get_live_fresh = False
            
            # Silent fallback to cache
            if self.historical_candles and self.live_data:
                self.live_data["candles"] = self.historical_candles
                return self.live_data
            return None
    def _fetch_interval(self, interval, days_back):
        try:
            now = datetime.now()
            params = {
                "exchange": "NSE",
                "symboltoken": "99926000",
                "interval": interval,
                "fromdate": (now - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M"),
                "todate": now.strftime("%Y-%m-%d %H:%M")
            }
            data = self._silent_call(self.client.getCandleData, params)
            if data and data.get("status"):
                raw = data["data"]
                return raw if isinstance(raw, list) else raw.get("candles", [])
        except Exception:
            pass
        return []

    def update_mtf_candles(self):
        """15m & 1h candles - sirf nayi candle banne par fetch (rate-limit safe)"""
        now = datetime.now()
        t15 = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
        if self.last_15m_time != t15:
            c = self._fetch_interval("FIFTEEN_MINUTE", 7)
            if c:
                self.candles_15m = c
                self.last_15m_time = t15
        t1h = now.replace(minute=0, second=0, microsecond=0)
        if self.last_1h_time != t1h:
            c = self._fetch_interval("ONE_HOUR", 7)
            if c:
                self.candles_1h = c
                self.last_1h_time = t1h

    def get_vix(self):
        """India VIX - range-validated (galat value se protection)"""
        try:
            data = self._silent_call(self.client.ltpData, "NSE", "INDIA VIX", "26000")
            if data and data.get("status"):
                v = float(data.get("data", {}).get("ltp", 0))
                if 5 <= v <= 80:
                    return v
        except Exception:
            pass
        return None


    def get_option_tokens(self):
        """NIFTY weekly option tokens (expiry-bound cache + 12hr max).
        Live cycle uses cache only; download only at startup if cache missing/stale."""
        import zipfile, io as _io, os, json as _json, requests
        from datetime import datetime, timedelta
        now = time.time()
        
        # Helper: Current expiry calculate karo
        def _current_expiry():
            exp_day = self.config.get_int("analysis.expiry_weekday", 1)
            exp = datetime.now().date() + timedelta(days=((exp_day - datetime.now().weekday()) % 7))
            return exp.strftime("%d%b%Y").upper()
        
        curr_exp = _current_expiry()
        
        # In-memory cache check (with expiry validation)
        if (getattr(self, "_tokens_loaded", False) and 
            (now - getattr(self, "_tokens_time", 0)) < 12 * 3600):
            cached_exp = getattr(self, "_tokens", {}).get("_expiry", "")
            if cached_exp == curr_exp:
                return getattr(self, "_tokens", {})
            # If expiry changed but cache still has data, use it with warning
            self.logger.info(f"Cache expiry changed: {cached_exp} → {curr_exp}, using available cache")
        
        # LOCAL SCRIP MASTER: check if user copied file to data/ folder
        # This is the preferred source - no network download needed
        local_scrip = os.path.join(os.path.dirname(__file__), "OpenAPIScripMaster.json")
        if os.path.exists(local_scrip):
            self.logger.info("Using local scrip master file (no download needed)...")
            try:
                with open(local_scrip) as f:
                    raw = f.read()
                if not raw.strip():
                    self.logger.info("Local scrip file is empty, proceeding with download logic")
                else:
                    # Local scrip master is valid - parse and extract NIFTY tokens for current expiry
                    self.logger.info("Local scrip master has content, extracting tokens - SKIPPING download")
                    try:
                        master = _json.loads(raw)
                    except Exception:
                        master = None
                    
                    if master:
                        # Auto-detect available expiries from local scrip master
                        available_exps = set()
                        for it in master:
                            if str(it.get("name")) == "NIFTY" and str(it.get("instrumenttype")) == "OPTIDX":
                                available_exps.add(str(it.get("expiry", "")).upper())
                        
                        # Sort by date, pick latest FUTURE expiry (after today)
                        from datetime import datetime as _dt
                        today = _dt.now().date()
                        future_exps = []
                        for exp in available_exps:
                            try:
                                exp_date = _dt.strptime(exp, "%d%b%Y").date()
                                if exp_date >= today:
                                    future_exps.append((exp_date, exp))
                            except:
                                continue
                        
                        if future_exps:
                            future_exps.sort()
                            curr_exp = future_exps[0][1]  # Earliest future expiry
                            self.logger.info(f"Auto-detected expiry from file: {curr_exp} (available: {[e[1] for e in future_exps[:3]]})")
                        else:
                            # Fallback to calendar calculation (existing logic)
                            exp_day = self.config.get_int("analysis.expiry_weekday", 1)
                            exp = datetime.now().date() + timedelta(days=((exp_day - datetime.now().weekday()) % 7))
                            curr_exp = exp.strftime("%d%b%Y").upper()
                        
                        tok = {}
                        for it in master:
                            exch = str(it.get("exch_seg") or it.get("exchange") or "")
                            if exch != "NFO" and exch != "NSE":
                                continue
                            sym = str(it.get("symbol", ""))
                            name = str(it.get("name", ""))
                            if name != "NIFTY" or len(sym) < 3:
                                continue
                            otype = sym[-2:]  # last 2 chars: "CE" ya "PE"
                            if otype not in ("CE", "PE"):
                                continue
                            # Check expiry matches current - only use tokens for current expiry
                            if str(it.get("expiry", "")) != curr_exp:
                                continue
                            try:
                                stk_raw = float(it.get("strike", 0))
                            except Exception:
                                continue
                            # Angel One strike * 100 store karta hai
                            strike = int(stk_raw // 100) if stk_raw > 100000 else int(stk_raw)
                            if strike <= 0:
                                continue
                            token = str(it.get("token") or it.get("symboltoken") or "")
                            if token:
                                tok[f"{strike}_{otype}"] = token
                        
                        # Cache the extracted tokens with current expiry
                        self._tokens = tok
                        self._tokens_time = now
                        self.logger.info(f"Tokens extracted from local master: {len(tok)}")
                        # Diagnostic: log available expiries
                        self.logger.info(f"Local file has these NIFTY expiries: {sorted(available_exps)[-5:]}")
                        return tok
                    else:
                        self.logger.warning("Local scrip master found but no NIFTY tokens for current expiry extracted")
            except Exception as e:
                self.logger.warning(f"Could not read local scrip file: {e}")
            # If we reach here (exception or no tokens extracted), fall through to cache/download logic
        
        # CACHE: check nifty_tokens.json (age < 12h) - use if valid and expiry matches
        cache = os.path.join(os.path.dirname(__file__), "nifty_tokens.json")
        tok = {}
        if os.path.exists(cache) and (now - os.path.getmtime(cache)) < 12 * 3600:
            try:
                with open(cache) as f:
                    cached = _json.load(f)
                cached_exp = cached.get("_expiry", "")
                if cached_exp == curr_exp:
                    tok = cached
                    self.logger.info("Using cached token file (age < 12h, expiry matches)")
                else:
                    self.logger.info(f"Cache expiry: {cached_exp}, current: {curr_exp} - cache stale, will revalidate")
            except Exception as e:
                self.logger.warning(f"Could not read cache file: {e}")
        
        # Only attempt download if cache doesn't have valid data for current expiry
        if not tok or tok.get("_expiry") != curr_exp:
            # Download instrument master from Angel One
            exp_day = self.config.get_int("analysis.expiry_weekday", 1)
            exp = datetime.now().date() + timedelta(days=((exp_day - datetime.now().weekday()) % 7))
            exp_str = exp.strftime("%d%b%Y").upper()
            
            self.logger.info("Instrument master download (~30MB, startup only)...")
            import gzip
            # Prefer smartapi.angelone.in first; apiconnect only as fallback
            urls = [u for u in [
                self.config.get("INSTRUMENT_URL", "") or "",
                "https://smartapi.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json",
                "https://apiconnect.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json",
            ] if u]
            items = None
            last = ""
            # RETRY LOGIC: 3 attempts with 10s delay between (mobile network slow hota hai)
            max_attempts = 3
            for attempt in range(max_attempts):
                for url in urls:
                    try:
                        raw = requests.get(url, timeout=120,
                                           headers={"User-Agent": "Mozilla/5.0"}).content
                        last = raw[:80]
                        try:
                            raw = gzip.decompress(raw)
                        except Exception:
                            pass
                        try:
                            z = zipfile.ZipFile(_io.BytesIO(raw))
                            raw = z.read(z.namelist()[0])
                        except Exception:
                            pass
                        try:
                            items = _json.loads(raw.decode("utf-8", errors="ignore"))
                        except Exception:
                            items = None
                        if items:
                            self.logger.info(f"Master downloaded: {url}")
                            break
                    except Exception as e:
                        last = str(e)
                if items or attempt == max_attempts - 1:
                    break
                time.sleep(10)  # 10s delay between attempts
            
            # Process downloaded tokens for current expiry
            if items:
                tok = {}
                for it in items:
                    exch = str(it.get("exch_seg") or it.get("exchange") or "")
                    if exch != "NFO" and exch != "NSE":
                        continue
                    sym = str(it.get("symbol", ""))
                    name = str(it.get("name", ""))
                    if name != "NIFTY" or len(sym) < 3:
                        continue
                    otype = sym[-2:]  # last 2 chars: "CE" ya "PE"
                    if otype not in ("CE", "PE"):
                        continue
                    if str(it.get("expiry", "")) != exp_str:
                        continue
                    try:
                        stk_raw = float(it.get("strike", 0))
                    except Exception:
                        continue
                    # Angel One strike * 100 store karta hai
                    strike = int(stk_raw // 100) if stk_raw > 100000 else int(stk_raw)
                    if strike <= 0:
                        continue
                    token = str(it.get("token") or it.get("symboltoken") or "")
                    if token:
                        tok[f"{strike}_{otype}"] = token
                
                if not tok:
                    raise ValueError(f"No NIFTY tokens found for expiry {exp_str}")
                
                # Cache the tokens with current expiry
                tok["_expiry"] = curr_exp
                with open(cache, "w") as f:
                    _json.dump(tok, f)
                self.logger.info(f"Tokens downloaded and saved: {len(tok)}")
            else:
                # Download failed - try using old cache even if expiry doesn't match
                # but DO NOT falsely relabel it - report clearly
                if os.path.exists(cache):
                    try:
                        with open(cache) as f:
                            old_cache = _json.load(f)
                        old_exp = old_cache.get("_expiry", "")
                        self.logger.warning(f"Download failed; using OLD cache (expiry: {old_exp}) "
                                          f"- current expiry is {curr_exp}. Some strikes may be unavailable.")
                        # Use old cache as-is, mark expiry honestly
                        tok = old_cache
                        tok["_expiry"] = curr_exp  # Honest: mark what expiry this is for
                    except Exception:
                        pass
                else:
                    raise ValueError(f"All download attempts failed. Last error: {last!r}")
        else:
            self.logger.info("Using existing cache tokens with matching expiry")
        
        # Ensure tok is a dict (never None) - downstream safety
        if not tok:
            tok = {}
        
        self._tokens = tok
        self._tokens_time = now
        self._tokens_loaded = True
    def get_option_ltp(self, token):
        """Option ka REAL live LTP (token se)"""
        try:
            data = self._silent_call(self.client.ltpData, "NFO", "NIFTY", str(token))
            if data and data.get("status"):
                return float(data["data"]["ltp"])
        except Exception:
            pass
        return None

    def get_market_full(self, tokens):
        """EK call me saare tokens ka LIVE LTP + OI (batched if >25 tokens)"""
        try:
            BATCH_SIZE = 25  # Angel API safe limit
            out = {}
            for i in range(0, len(tokens), BATCH_SIZE):
                batch = tokens[i:i+BATCH_SIZE]
                if i > 0:  # Rate limit between batches
                    self._rate_limit_wait()
                data = self._silent_call(self.client.getMarketData, "FULL", {"NFO": batch})
                if data and data.get("status"):
                    for d in data.get("data", {}).get("fetched", []):
                        tk = str(d.get("symbolToken") or d.get("symboltoken") or "")
                        if tk:
                            out[tk] = d
                else:
                    # If batch fails, log but continue with other batches
                    if self.logger:
                        self.logger.warning(f"Batch {i//BATCH_SIZE + 1} failed in get_market_full")
            return out if out else None
        except Exception:
            pass
        return None

    def shutdown(self):
        try:
            if self.client and self.connected:
                self._silent_call(
                    self.client.terminateSession, self.config.get("ANGEL_CLIENT_ID")
                )
                self.connected = False
                self.logger.info("Market data connection closed")
        except Exception:
            pass
