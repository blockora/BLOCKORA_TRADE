"""Liquidity Engine - illiquid strikes ko ranking se pehle filter karta hai"""


class LiquidityEngine:
    # Reject thresholds
    MIN_VOLUME = 100              # minimum option volume
    MAX_SPREAD_PCT = 30           # bid-ask spread max 30% of LTP
    JUMP_THRESHOLD_PCT = 50       # premium jump > 50% = suspicious
    MIN_OI = 500                  # minimum open interest

    def __init__(self, logger=None):
        self.logger = logger
        self._last_ltp = {}       # strike -> last LTP (jump detection)

    def filter_chain(self, option_chain):
        """Option chain se illiquid strikes hata deta hai (in-place copy)"""
        if not option_chain:
            return option_chain, {"removed": 0, "kept": 0}

        import copy
        chain = copy.deepcopy(option_chain)
        removed = 0
        kept = 0

        for side in ("ce_data", "pe_data"):
            opt_type = "CE" if side == "ce_data" else "PE"
            original = chain.get(side, {})
            filtered = {}
            for strike, rec in original.items():
                ok, reason = self._check_strike(strike, rec, opt_type)
                if ok:
                    filtered[strike] = rec
                    kept += 1
                else:
                    removed += 1
            chain[side] = filtered

        stats = {"removed": removed, "kept": kept}
        if removed > 0 and self.logger:
            self.logger.info(f"Liquidity: removed {removed} illiquid strikes, kept {kept}")
        return chain, stats

    def _check_strike(self, strike, rec, opt_type="UNKNOWN"):
        """Single strike ki liquidity check"""
        try:
            ltp = float(rec.get("ltp", 0) or 0)
            vol = float(rec.get("volume", 0) or 0)
            bid = float(rec.get("bid", 0) or 0)
            ask = float(rec.get("ask", 0) or 0)
            oi = float(rec.get("oi", 0) or 0)
        except Exception:
            return False, "parse_fail"

        # 1) LTP hona chahiye
        if ltp <= 0:
            return False, "no_ltp"

        # 2) Volume minimum (P0-5: ESTIMATED volume ko real liquidity mat maano)
        volume_source = str(rec.get("volume_source", "")).upper()
        if volume_source == "ESTIMATED":
            # Fake/estimated volume = REAL liquidity evidence NAHI
            # Volume check bypass karo; liquidity OI + LTP + spread se decide hogi
            pass
        elif vol < self.MIN_VOLUME and vol > 0:
            return False, f"low_vol({vol})"

        # 3) OI minimum (sirf jab data available ho)
        # Angel One me OI kabhi-kabhi missing hota hai
        if oi < self.MIN_OI and oi > 0:
            return False, f"low_oi({oi})"

        # 4) Spread check SIRF jab bid/ask available ho
        #    (Angel me bid/ask=0 = "not provided", reject MAT karo)
        if bid > 0 and ask > 0 and ltp > 0:
            spread = ask - bid
            if (spread / ltp) * 100 > self.MAX_SPREAD_PCT:
                return False, f"wide_spread({spread:.1f})"

        # 5) Sudden premium jump (CE/PE isolated — BUG #2 FIX)
        key = f"{opt_type}_{strike}"
        last = self._last_ltp.get(key)
        self._last_ltp[key] = ltp
        if last and last > 0:
            change_pct = abs(ltp - last) / last * 100
            if change_pct > self.JUMP_THRESHOLD_PCT:
                return False, f"jump_{change_pct:.0f}%"
        return True, ""
