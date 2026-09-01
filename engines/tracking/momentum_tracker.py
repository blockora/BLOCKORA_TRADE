"""MomentumTracker - 5-Cycle LTP Momentum Tracker (independent, non-invasive).

Har 5 cycles ka ek block:
  Cycle 1 : top-ranked CE + PE strike LOCK karo, base_ltp record karo.
  Cycle 2-4: locked strikes ka current LTP track karo (ranking change se effect nahi).
  Cycle 5 : movement = current_ltp - base_ltp. >5 Rs ho to 🚀 print karo. Reset.

Existing scoring/ranking/console output pe koi asar NAHI (sirf extra print).
"""
import time


class MomentumTracker:
    BLOCK_SIZE = 5
    MOVEMENT_THRESHOLD = 5.0

    def __init__(self, logger=None):
        self.logger = logger
        self.reset()

    def reset(self):
        """Block state reset (cycle 5 ke baad ya initialize par)."""
        self.cycle_count = 0
        self.locked_ce_strike = None
        self.locked_pe_strike = None
        self.ce_base_ltp = None
        self.pe_base_ltp = None
        self.ce_current_ltp = None
        self.pe_current_ltp = None

    def _get_ltp(self, chain, strike, opt_type):
        """Chain data se locked strike ka live LTP nikalo (no extra API call)."""
        try:
            if not chain or not isinstance(chain, dict):
                return None
            side = chain.get("ce_data" if opt_type == "CE" else "pe_data", {})
            rec = side.get(strike) or {}
            if isinstance(rec, dict):
                ltp = rec.get("ltp", 0) or 0
                return float(ltp) if ltp else None
        except Exception:
            return None
        return None

    def update(self, best_ce, best_pe, chain):
        """Har cycle ke baad call karo (ranking ke baad, chain data ke saath).

        Args:
            best_ce: ranked_strikes['best_ce'] (dict with 'strike')
            best_pe: ranked_strikes['best_pe'] (dict with 'strike')
            chain:   live option chain (ce_data/pe_data with ltp)
        """
        try:
            ce_strike = int((best_ce or {}).get("strike", 0) or 0)
            pe_strike = int((best_pe or {}).get("strike", 0) or 0)
        except (TypeError, ValueError):
            ce_strike = pe_strike = 0

        if self.cycle_count == 0:
            # ── Cycle 1 (block start): strikes LOCK + base LTP ──
            self.locked_ce_strike = ce_strike
            self.locked_pe_strike = pe_strike
            self.ce_base_ltp = self._get_ltp(chain, ce_strike, "CE")
            self.pe_base_ltp = self._get_ltp(chain, pe_strike, "PE")
            self.ce_current_ltp = self.ce_base_ltp
            self.pe_current_ltp = self.pe_base_ltp
            self.cycle_count = 1
            return

        # ── Cycles 2-5: locked strikes ka current LTP track karo ──
        self.ce_current_ltp = self._get_ltp(chain, self.locked_ce_strike, "CE")
        self.pe_current_ltp = self._get_ltp(chain, self.locked_pe_strike, "PE")
        self.cycle_count += 1

        if self.cycle_count >= self.BLOCK_SIZE:
            # ── Cycle 5: evaluate momentum + print + reset ──
            self._evaluate_and_print()
            self.reset()

    def _evaluate_and_print(self):
        """Cycle 5 par movement check + 🚀 print (threshold > 5 Rs)."""
        lines = []
        for label, strike, base, cur in (
            ("CE", self.locked_ce_strike, self.ce_base_ltp, self.ce_current_ltp),
            ("PE", self.locked_pe_strike, self.pe_base_ltp, self.pe_current_ltp),
        ):
            try:
                if base is None or cur is None:
                    continue
                movement = round(float(cur) - float(base), 2)
                if movement > self.MOVEMENT_THRESHOLD:
                    lines.append(f"🚀 {strike} {label} better LTP Rs. {movement}+ MILE in {self.BLOCK_SIZE} cycles!")
            except Exception:
                continue

        if lines:
            if self.logger:
                self.logger.info(" | ".join(lines))
        # Both <= 5 ya data missing -> kuch bhi print nahi (silent)