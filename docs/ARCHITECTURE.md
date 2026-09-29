# BLOCKORA_TRADE v3 — Architecture

**Policy:** RECOMMENDATION ONLY. The system never places orders. Final decision always belongs to the user.

**Prime directive:** the system must never be forced to produce a trade. `NO_TRADE` is a first-class outcome of
every pipeline run.

---

## 1. Two-stage decision process (from the spec, hardened)

**Stage 1 — Direction.** Classify the market as `BULLISH / BEARISH / RANGE / UNCERTAIN`, then score the CALL
side and PUT side independently. A side becomes a *valid* side only if it passes its gate: regime alignment,
minimum side score, score margin over the opposite side, and all cross-cutting data-quality requirements.

**Stage 2 — Strike.** Only within a valid side, rank candidate strikes. The top-ranked candidate must
additionally pass liquidity, spread, data-quality, risk/reward, entry-quality, expiry, volatility and regime
hard filters. Any failure at any point → `NO_TRADE` (with the reason recorded).

Raw score alone never selects a strike; hard filters always outrank score.

---

## 2. Pipeline

```
LIVE DATA  (broker WS/API + option chain + candle history)
    |
DATA VALIDATION  (freshness, completeness, sanity, staleness → reject or degrade)
    |
FEATURE ENGINE  (per-strike feature vector from candles + chain + greeks)
    |
MARKET REGIME ENGINE  (HTF regime / MTF trend / LTF execution context)
    |
CALL/PUT SIDE SCORING  (directional evidence, aggregated by feature groups)
    |
STRIKE SCORING  (per-candidate composite model_score, same group logic)
    |
RISK/REWARD ENGINE  (entry/SL/targets from premium ATR + spread-adjusted levels)
    |
HARD FILTERS  (binary veto gates; any FAIL → NO_TRADE)
    |
CANDIDATE RANKING  (score-ordered, filter-surviving, side-separated)
    |
CALIBRATED CONFIDENCE  (empirical mapping score→P(win) from historical outcomes)
    |
FINAL DECISION  (RECOMMENDATION | NO_TRADE, with machine-readable reasons)
    |
DATABASE  (snapshots, candles, features, scores, recommendations, outcomes)
    |
OUTCOME TRACKING  (tick/bar replay: WIN / LOSS / TIMEOUT per deterministic rules)
    |
BACKTESTING  (event-driven, no look-ahead, costs+slippage included)
    |
MODEL CALIBRATION  (regime/score-bucket win rates → calibrated confidence)
    |                                          |
    +------------------------------------------+--> feedback into CALIBRATED CONFIDENCE
```

The loop from OUTCOME TRACKING onward is the *measurement* loop. It never feeds back into the live scoring
weights automatically; weight changes are reviewed artifacts (Phase 8), not silent online adaptation.

---

## 3. Module tree (implemented now, Phase 1 scope)

```
main.py                     entry point: run one decision cycle (live, replay, or dry-run) — Phase 2+
config/
  settings.yaml             market rules, session, thresholds, data-quality limits
  weights.yaml              scoring weights + feature groups (the ONLY place weights live)
  filters.yaml              hard-filter thresholds and NO_TRADE policy
core/
  models.py                 typed dataclasses: Direction, Regime, FeatureVector, StrikeCandidate,
                            SideScore, TradePlan, Recommendation, Outcome
  scoring_utils.py          clamp/normalize helpers shared by every scorer
  signal_scorer.py          group-aware weighted scorer (the double-counting control point)
  hard_filters.py           deterministic veto engine (Phase 5, stub now)
  calibration.py            score→probability mapping (Phase 8, interface now)
data/
  interfaces.py             BrokerSource / ChainSource protocols (swap-in adapters)
database/
  schema.sql                full SQLite DDL (all tables, v1)
  db.py                     connection, init, upserts, queries (schema-verified)
tests/                      pytest suite per phase (see docs/TESTS.md — Phase 1: 45+ cases)
docs/
  ARCHITECTURE.md           this file
  SCHEMA.md                 tables + data models + storage policy
  SCORING.md                formulas, feature groups, double-counting control
  CALIBRATION.md            model_score vs calibrated_confidence, backtest + metrics methodology
  FILTERS.md                hard-filter rules, NO-TRADE policy, MTF and pattern policy
  ASSUMPTIONS.md            every assumption, marked HEURISTIC or CALIBRATED
```

### Reserved for later phases (not implemented yet — do not call them from live code)

```
engines/regime.py           Phase 3 — HTF/MTF/LTF classification rules
engines/features.py         Phase 2 — indicator + feature computation from candles
engines/ranking.py          Phase 4 — two-stage ranking implementation
engines/risk.py             Phase 5 — entry/SL/target computation, R/R checks
engines/backtest.py         Phase 7 — event-driven replay engine
engines/calibrate.py        Phase 8 — empirical bucketing, logistic/isotonic/Platt comparison
engines/patterns.py         Phase 9 — SMC/ICT/Wyckoff as feature providers (never trade generators)
telegram/notify.py          Phase 10 — sends only filter-passing recommendations
```

Each later-phase module is only wired into `main.py` after its tests pass (phase gate, §6).

---

## 4. Component responsibilities

| Component | Responsibility | Never does |
|---|---|---|
| Data adapters | fetch + timestamp + freshness metadata; never fabricate values (missing → None) | estimate volume from OI |
| Validation | reject stale/incomplete *critical* fields; degrade non-critical | silently fill gaps |
| Feature engine | compute per-strike features; attach quality flags | emit scores |
| Regime engine | HTF/MTF/LTF classification + conflict resolution per docs/FILTERS.md §5 | score strikes |
| Side scorer | aggregate directional evidence into CALL/PUT side scores with group caps | pick strikes |
| Strike scorer | per-strike composite model_score (0–100) via group-weighted normalization | classify regime |
| R/R engine | entry/SL/T1–T3 from premium ATR and spread-adjusted levels; compute R:R | veto (that is filters' job) |
| Hard filters | binary PASS/FAIL vetoes with reasons; always evaluated, never skippable | compute scores |
| Ranking | order surviving candidates; ensure side separation and margin checks | override filters |
| Calibration | map model_score + context → P(target-before-stop); mark CALIBRATED vs HEURISTIC | invent probabilities |
| Decision | combine side gate + best candidate + calibration regime check → RECOMMENDATION or NO_TRADE | force a trade |
| DB | append-only event store: snapshots, features, scores, recs, outcomes | delete history (except explicit retention policy) |
| Outcome tracker | replay recorded bars/ticks against recorded plan; deterministic tie rule | guess intrabar sequence |
| Backtester | re-run pipeline on historical data with costs; same code path as live | use future data |
| Calibration lab | fit/compare calibrators offline; export frozen mapping files | alter live scores silently |

---

## 5. Data flow contracts

- Every market-data object carries: `data_timestamp`, `received_timestamp`, `latency_ms`, `source`,
  `quality_status` ∈ {OK, DEGRADED, STALE, MISSING}.
- A feature or score computed from degraded data is itself marked DEGRADED and loses its normal weight share
  (see docs/SCORING.md §5.3); scores computed from MISSING critical data are invalid → NO_TRADE path.
- Recommendations, scores, features are append-only. Corrections are new rows, never updates of history.

---

## 6. Phase plan and gates (development order from the brief)

| Phase | Deliverable | Gate to proceed |
|---|---|---|
| 1 | Config system, DB schema, data models, pipeline skeleton, docs | tests green (45+ cases) |
| 2 | Candle + indicator engine, option-chain normalization, feature vectors | feature tests green |
| 3 | Regime + trend + market-structure engines | MTF-conflict tests green |
| 4 | Two-stage ranking (side + strike) | ranking + double-count tests green |
| 5 | Risk engine, hard filters, NO_TRADE logic | filter veto tests green |
| 6 | Outcome tracking + recommendation/outcome persistence | outcome-rule tests green |
| 7 | Event-driven backtester | no-lookahead tests green |
| 8 | Calibration lab (bucketing → logistic/isotonic/Platt), metrics | calibration tests + first calibrated report |
| 9 | SMC/ICT/Wyckoff/pattern modules as feature providers | pattern-feature tests green |
| 10 | Telegram + monitoring | end-to-end dry run; Telegram sends only filtered recs |

**Current status: Phase 1 complete. Phases 2–10 require approval (see docs/ROADMAP.md decision points).**
