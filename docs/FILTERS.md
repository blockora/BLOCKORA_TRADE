# Hard Filters, NO-TRADE Policy, Multi-Timeframe & Pattern Rules

## 1. Principle

Hard filters are **binary vetoes evaluated on every cycle**, independent of score. A score of 99 does not
survive a failed filter. Filters run *after* the risk engine computes the plan (some need entry/SL/T levels)
and *before* ranking output becomes a recommendation.

Config lives in `config/filters.yaml`. Every filter returns `(PASS | FAIL, reason)` and FAIL reasons are
recorded on the recommendation/NO_TRADE row.

---

## 2. NO_TRADE is a first-class decision

NO_TRADE is emitted — with a machine-readable reason — whenever:

1. both side gates fail (`no_side`);
2. the valid side has no candidate surviving strike-level filters (`no_candidate`);
3. any hard filter fails on the top candidate (`filter:<filter_name>`);
4. regime is UNCERTAIN or genuinely conflicting (`regime_uncertain`, `regime_conflict`);
5. calibrated context gate fires (`calibrated_edge_absent`) — dormant until Phase 8;
6. circuit breakers active (`circuit_breaker:<which>`);
7. session closed / pre-open / post-close (`session_closed`);
8. data-quality critical failure (`data:<field>:<quality>`);
9. duplicate/signal-throttle: same contract re-signalled inside `dedup_window_min` (`duplicate_signal`);
10. score incomplete due to missing critical data (`score_incomplete`).

NO_TRADE rows are persisted (context + reasons) so rejection quality can be measured later (counterfactual
precision). The system must never be forced into a trade; when in doubt → NO_TRADE.

---

## 3. Hard filter catalogue (v1)

| id | filter | rule (defaults; all in filters.yaml) |
|---|---|---|
| F1 | session | inside 09:15–15:30 IST, Mon–Fri, non-holiday |
| F2 | source health | last successful source heartbeat within `max_source_lag_s` (default 10s live) |
| F3 | data freshness | underlying + chain `latency_ms <= max_latency_ms` and age <= `max_age_s` (default 5s/2s) |
| F4 | critical completeness | spot, LTP, bid, ask present and > 0; IV required for volatility gates or gate degrades |
| F5 | spread | `spread_pct <= max_spread_pct` (default 3.0 for near-ATM NIFTY options) |
| F6 | liquidity | `volume >= min_volume` (default 1000) AND `oi >= min_oi` (default 500) |
| F7 | entry sanity | |entry − ltp| / ltp <= max_entry_deviation (default 5%); entry within [bid, ask + slippage] |
| F8 | score completeness | UNAVAILABLE components ≤ `max_unavailable_components` (default 2) and family redistribution within cap (docs/SCORING.md §5) |
| F9 | volatility sanity | IV within [min_iv, max_iv] band for buying (default 8–80); IV rank ≤ max_iv_rank (spec: >80 → no buy) unless explicitly overridden |
| F10 | risk/reward | planned R:R ≥ min_rr (default 1.5) after costs and spread-adjusted exits |
| F11 | expiry validity | contract not expired; DTE ≥ min_dte (default 1); expiry matches execution timeframe policy |
| F12 | regime conflict | MTF classification = ALIGNED or PULLBACK; TREND_CONFLICT / REVERSAL_RISK / UNCERTAIN → fail |
| F13 | abnormal event | candle range > k×ATR or circuit-limit flag → fail (abnormal volatility/event risk) |
| F14 | duplicate | same (side, strike, expiry, type) within dedup window; and max signals per day (spec: 2) |
| F15 | stale chain | chain snapshot older than `max_chain_age_s` (default 3s live) relative to decision ts |

Notes:
- F4/F3/F15 are evaluated first; on failure the pipeline short-circuits to NO_TRADE before scoring to avoid
  garbage-in scoring.
- Defaults are HEURISTIC starting points, deliberately conservative, to be revisited with outcome data.

---

## 4. Conflict handling: score never overrides filters

Implementation detail: `HardFilterEngine.evaluate(candidate)` is called even when the engine is "confident".
There is no code path from high score to bypassing a filter. The only score-related filter (F8) concerns
missing data, not low score; a *low* score alone yields NO_TRADE at the side/rank gates, not a filter bypass.

---

## 5. Multi-timeframe policy (no blind all-agreement requirement)

Three layers, each classified independently (Phase 3 engine):

- **HTF (regime):** daily/1h structure + trend. Values: BULLISH / BEARISH / RANGE.
- **MTF (trend):** 15m trend + structure.
- **LTF (execution):** 5m/1m momentum context for timing.

Classification of combinations:

| HTF | MTF | LTF | classification | tradeable? |
|---|---|---|---|---|
| bull | bull | bearish pullback | PULLBACK | yes — buy dips in direction (LTF timing only) |
| bull | bull | bull | ALIGNED | yes |
| bull | bear | any | TREND_CONFLICT | no (MTF counter-trend against HTF not accepted v1) |
| bull | flat | bull | WEAK_ALIGNMENT | conditional — requires margin ≥ normal |
| bull | bull→bear transition (structure break on MTF) | any | REVERSAL_RISK | no |
| mixed/flat all | | | UNCERTAIN | no |

Explicit rules:
- LTF counter-move inside aligned HTF+MTF is a **pullback**, not a conflict; it may improve entry timing but
  never flips the side.
- MTF against HTF is a **conflict** in v1 → NO_TRADE (conservative; revisit with data in Phase 8).
- Distinguishing pullback vs reversal uses MTF structure (higher-highs intact?) — Phase 3 engine; until then
  ambiguous cases classify as UNCERTAIN → NO_TRADE. Never guess in favour of trading.

---

## 6. Pattern/policy rules (context, never triggers)

A detected pattern produces a *witness vector*: `{pattern, direction, quality, confirmation_status,
volume_confirmation, location, trend_context, htf_context}`. It enters scoring only through
`momentum.candle_body` (docs/SCORING.md §1) and only as **confirmation evidence** (needs an independent group
≥ 6 to contribute). No pattern may flip a side, override a filter, or create a recommendation alone.

---

## 7. Circuit breakers (spec §6.3, carried over)

Per-day state: max trades (2), max consecutive losses (3), max daily loss (5% of capital), max daily losses
count (2). Breaker state is checked before side gating; active breaker → NO_TRADE(circuit_breaker) for the
rest of the session. Breakers are per-config; tracked in DB (`recommendations` outcomes feed them).
