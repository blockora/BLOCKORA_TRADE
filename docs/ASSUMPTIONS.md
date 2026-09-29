# ASSUMPTIONS.md — every place the spec was silent or ambiguous

Each assumption is marked **HEURISTIC** (unvalidated rule chosen for safety/simplicity, revisit with data) or
**CALIBRATED** (value/decision derived from historical outcomes; none exist yet, so everything starts
HEURISTIC). Nothing here was silently invented: each item has an ID for review.

## A. Data & sources

- **A-1 (HEURISTIC).** Primary data path is the Angel One SmartAPI (per README credentials). The system is
  built source-agnostic: `data/interfaces.py` defines BrokerSource/ChainSource protocols; Angel adapter lands
  in Phase 2. Until a live adapter exists, a deterministic synthetic generator exists ONLY for tests.
- **A-2 (HEURISTIC).** Missing broker fields are `NULL`, never zero-filled (the repo's legacy main.py
  estimated volume as 10% of OI — rejected; estimation corrupts liquidity gates).
- **A-3 (HEURISTIC).** "Stale" = age > 5s for underlying ticks, > 2s latency, > 3s for chain snapshots
  (filters.yaml). NIFTY option chains move fast; conservative defaults.
- **A-4 (HEURISTIC).** Timezone is Asia/Kolkata everywhere; timestamps stored in UTC ISO-8601 in DB, rendered
  IST in output.

## B. Scoring

- **B-1 (HEURISTIC).** The spec's 7-factor weights (20/15/15/10/20/10/10) are carried into the family weights
  as the starting point (config/weights.yaml), clearly marked for Phase 8 optimization. They are not treated
  as validated.
- **B-2 (HEURISTIC).** Component band edges (delta 0.40–0.60 ideal, spread bands, volume bands) come from the
  spec and are kept as defaults. They encode plausible preferences, not measured edges.
- **B-3 (HEURISTIC).** Damping constant 0.5 for correlated components within a family, group cap +2,
  confirmation share 0.5 (docs/SCORING.md §4). Chosen to bound score inflation; exact values to be studied
  against outcomes.
- **B-4 (HEURISTIC).** Side gate: min side score 55, min margin 10. Placeholder ranking thresholds until
  calibration provides empirical ones.
- **B-5 (HEURISTIC).** A component with genuinely missing data is excluded and the score is normalized by
  the TOTAL configured weight — missing evidence lowers the score, no redistribution (docs/SCORING.md §5;
  an earlier redistribution design was removed after review).
- **B-6 (HEURISTIC).** Spec's "Confidence > 80 → A+ setup" bands are retained ONLY as internal grade labels
  for score bands. They never appear as probabilities in output.

## C. Risk & trade plan

- **C-1 (HEURISTIC).** For long options the spec's own correction is used: SL = entry − 1.5×ATR(premium),
  T1/T2/T3 = entry + 1/2/3×ATR(premium), targets rounded to 0.05 tick. Technical-level blending (spec §4.2)
  is deferred to Phase 5 review — index-level supports/resistances do not map linearly to premium levels and
  the blend could produce unreachable targets.
- **C-2 (HEURISTIC).** Entry = mid + 0.25×spread, rounded to 0.05 (spec §3.1), validated within ±5% of LTP.
- **C-3 (HEURISTIC).** Expected holding time: estimated from ATR pace and max_hold_bars default 24 bars of
  the 5m execution timeframe (= 2h), also bounded by expiry. Revisited in Phase 6 with empirical hold data.
- **C-4 (HEURISTIC).** Circuit breakers: 2 trades/day, stop after 2 consecutive losses (spec conflicts with
  itself: §6.3 says 3, FINAL NOTES says 3 vs "Stop after 2" in capital rules — we take the stricter 2 and
  expose it as config), daily loss 5%.
- **C-5 (HEURISTIC).** Position sizing (Kelly/2, 5% cap) is out of scope for a recommendation-only system v1;
  we output risk % and R:R instead. Kelly is documented for Phase 8+ if the user trades manually.
- **C-6 (HEURISTIC, resolves a spec contradiction).** The spec's plan multipliers (SL=1.5×ATR_prem,
  T1=1×ATR_prem) imply R:R(T1)=0.67, which can never pass its own min R:R=1.5 filter. Resolved: the
  filter evaluates the plan's book-ladder expectancy R:R = (0.5·(T1−E) + 0.3·(T2−E) + 0.2·(T3−E)) / (E−SL),
  matching the spec's own 50/30/20 booking scheme (§7.1). The per-target R:Rs are still shown in diagnostics.
- **C-7 (HEURISTIC, resolves a second spec contradiction).** Even with the book-ladder R:R, the spec's
  SL=1.5×ATR caps ladder R:R at 1.13 — below its own min_rr=1.5 — so the shipped defaults would make the
  system permanently NO_TRADE (broken, not conservative). Default SL multiplier is therefore 1.0×ATR_prem
  (ladder R:R = 1.7). Multipliers stay configurable in filters.yaml for Phase 8 optimization against outcomes.

## D. Calibration & outcomes

- **D-1 (CALIBRATED-target).** Outcome = T1-before-SL within max hold. TIMEOUT ≠ win. Same-bar ambiguity →
  LOSS (conservative; prevents optimistic calibration).
- **D-2 (HEURISTIC).** min_bucket_samples = 30 for any calibrated number to gate a decision; below that,
  report UNAVAILABLE.
- **D-3 (HEURISTIC).** Walk-forward (train → later held-out) is the only accepted evaluation window; no
  metric is tuned on the evaluation window itself.
- **D-4 (HEURISTIC).** Calibrator choice: simplest model within one standard error of best walk-forward ECE
  (docs/CALIBRATION.md §6).

## E. Regime & patterns

- **E-1 (HEURISTIC).** MTF table per docs/FILTERS.md §5; MTF-against-HTF = conflict → NO_TRADE in v1.
  Pullback vs reversal decided by MTF structure in Phase 3; until that engine exists, ambiguous = UNCERTAIN.
- **E-2 (HEURISTIC).** Patterns are confirmation witnesses only (no auto-trade), per brief.
- **E-3 (HEURISTIC).** The spec's 30+ "genius" modules (FFT cycles, Lyapunov, game theory, …) are NOT
  implemented. They are unfalsifiable heuristics for this dataset and would add noise. Any addition must
  enter as a feature with a group membership and prove itself in backtest. Documented, not silently dropped.

## F. Operations

- **F-1 (HEURISTIC).** Telegram sends only recommendations that passed all filters (Phase 10). NO_TRADE is
  never pushed as a signal; a daily digest may include rejection statistics.
- **F-2 (HEURISTIC).** Dedup window default 30 min per contract; max 2 signals/day.
- **F-3 (HEURISTIC).** Retention: market history kept indefinitely in SQLite; NO_TRADE rows retained for
  denominator statistics.
- **F-4 (HEURISTIC).** The system runs recommendation-only; there is deliberately no order-placement code
  path anywhere in the codebase.
