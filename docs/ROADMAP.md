# ROADMAP & Phase Gates — BLOCKORA_TRADE v3

Status legend: done · next (awaiting approval) · later

| Phase | Scope | Status | Gate |
|---|---|---|---|
| 1 | Architecture docs, config system, DB schema, data models, group-aware scorer, session/data interfaces, 44 new tests | done | suite green |
| 2 | Angel One adapter (BrokerSource/ChainSource), candle ingestion (closed-bar rule), indicator engine, option-chain normalization, per-strike feature vectors | next | feature tests green |
| 3 | Regime engine: HTF/MTF/LTF classification, pullback-vs-reversal rules (docs/FILTERS.md §5) | later | MTF-conflict tests green |
| 4 | Two-stage ranking: side gate + strike ranking with tie-breaks | later | ranking + double-counting tests green |
| 5 | Risk engine (entry/SL/T1–T3 per docs/ASSUMPTIONS.md C-1/C-2), hard filters F1–F15, NO_TRADE paths | later | filter veto tests green |
| 6 | Outcome tracker: LIVE_REPLAY evaluation per outcome definition, persistence | later | outcome-rule tests green (incl. same-bar → LOSS) |
| 7 | Event-driven backtester (no look-ahead, costs/slippage/latency) | later | no-lookahead tests green |
| 8 | Calibration lab: bucketing → logistic/isotonic/Platt comparison, walk-forward metrics, freeze/activate | later | calibration tests + first CALIBRATED report (min n respected) |
| 9 | SMC/ICT/Wyckoff/pattern modules as feature providers with confirmation gating | later | pattern-feature tests green |
| 10 | Telegram (filtered recommendations only) + monitoring/digest | later | end-to-end dry run |

## Legacy v2 code (existing repo content)

The repository contains the previous Termux-oriented v2 implementation (`engines/`, legacy
`database/db_manager.py`, `main.py`, legacy tests). Disposition:

- Kept untouched and runnable: legacy tests that still pass (`test_basic.py`, `test_market_memory.py`,
  `test_strike_continuity.py`, `test_contract_intelligence.py`, `test_volatility_gate.py` variants).
- Known-broken pre-existing (fail in this environment regardless of v3 work): `test_safety_regression.py`
  (targets v2 API drift), `test_replay_harness.py` + `test_historical_similarity.py` (missing modules).
  These are NOT touched by Phase 1; they will be ported or retired per-phase as v3 replaces each subsystem.
- v3 runs in parallel files (`core/config.py`, `database/db.py`, …) — no v2 file was modified.

## Decision points requiring user approval before the next phase

1. **Data source (Phase 2):** build the Angel One adapter first (README credentials imply it), with
   `data/interfaces.py` fakes for tests? Any secondary source (NSE direct) priority?
2. **Execution timeframe:** 5m bars for execution + 15m trend + 1h regime (current config default) — confirm.
3. **Expiry policy:** trade only the nearest weekly expiry unless DTE < 1 (then next weekly)? Spec is silent.
4. **Legacy v2 code:** keep running in parallel during Phase 2–4 (shadow comparison), or freeze it once the
   v3 pipeline reaches parity in Phase 5?
5. **Calibration data plan (Phase 6–8):** start collecting v3 recommendation/outcome rows immediately at
   Phase 5 completion so Phase 8 has data, accepting that calibrated_confidence stays UNAVAILABLE for the
   first weeks. Confirm acceptable.

## Definition of "phase complete"

- All new tests green (`python3 -m pytest tests/ -k "<phase scope>"`).
- Docs updated (ASSUMPTIONS.md entries for every silent decision made that phase).
- No change to v2 behavior unless explicitly listed in the phase scope.
