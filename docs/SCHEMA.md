# Database Schema — BLOCKORA_TRADE v3

SQLite (file: `database/blockora.db`), WAL mode. The canonical DDL lives in
`database/schema.sql` — this document explains the design intent.

Principles:

1. **Append-only for market history.** Snapshots, candles, features, scores and recommendations are never
   updated; corrections are new rows.
2. **Raw and derived separated.** `chain_snapshots` stores exactly what the source gave; `strike_features`
   stores what we computed. A bug in feature computation never corrupts raw history.
3. **Every derived row carries provenance** (`source`, `quality_status`) so any historical score can be
   audited against its inputs.
4. **Reproducibility.** A recommendation row plus its linked snapshot/feature rows must be sufficient to
   re-run the decision offline and get the same result (no-lookahead backtest requirement).

---

## Tables

### option_chain_snapshots
One row per option per snapshot cycle.

| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| snapshot_ts | TEXT UTC ISO | decision timestamp |
| received_ts | TEXT UTC ISO | when the row was written |
| latency_ms | REAL | received - source stamp |
| source | TEXT | e.g. ANGEL_LIVE, NSE_SNAPSHOT, REPLAY |
| expiry | TEXT YYYY-MM-DD | |
| strike | REAL | |
| option_type | TEXT | CE/PE |
| ltp, bid, ask, iv | REAL NULL | NULL = not provided (never zero-filled) |
| volume, oi, change_oi | INTEGER NULL | NULL = not provided |
| quality_status | TEXT | OK / DEGRADED / STALE / MISSING |

### underlying_ticks
Index/futures quotes per cycle (spot ltp, change, ts, source, quality).

### candles
OHLCV bars. `PK(symbol, timeframe, bar_ts)` with `bar_close_ts` separate; ingestion only accepts closed
bars (a bar is closed when a later bar with the same timeframe exists or the session clock says so). This is
the first no-lookahead guarantee.

### indicators
Computed indicator values per (symbol, timeframe, bar_ts) — RSI, EMA20/50/200, ATR, VWAP, ADX, MACD, delta
EMA slope, and regime inputs. Stored so backtests re-read *recorded* indicator values where possible.

### features
Per-strike feature vectors, JSON, one row per (snapshot_ts, expiry, strike, option_type):

`strike, distance_atm, ltp, volume, oi, change_oi, bid, ask, spread_pct, iv, iv_rank, delta, gamma, theta,
vega, underlying_price, momentum_5m, trend_flag, vwap_rel, ema_rel, market_structure, volatility_state,
liquidity_score, chain_confirmation, risk_reward, data_quality_flags`.

### component_scores
Per-strike per-component scores: `component ∈ {trend, market_structure, option_chain, oi, volume, momentum,
liquidity, volatility, strike_quality, risk_reward}`, each 0–10, plus `confidence ∈ {REAL, ESTIMATED,
UNAVAILABLE}` — supports later weight re-scoring without recomputing features.

### recommendations
The decision record. Append-only; one row per emitted recommendation or NO_TRADE (NO_TRADE rows are kept for
denominator statistics — you cannot measure precision without them).

Key columns: `decision_ts, market_bias, side (CALL/PUT), strike, expiry, entry, stop_loss, t1, t2, t3,
expected_hold_min, model_score, calibrated_confidence, risk_pct, reward_risk, trade_grade,
key_reasons (JSON), rejected_alternatives (JSON), no_trade_reason, diagnostics (JSON), pipeline_version,
weights_hash, calibrator_hash, replay_window_start/end, reviewed (0/1), outcome_id`.

`weights_hash` ties every recommendation to the exact weight configuration that produced it — mandatory for
honest A/B analysis of weight changes.

### outcomes
One row per tracked recommendation. Filled by the outcome tracker (live) or backtester (historical):

`outcome (WIN_T1/WIN_T2/WIN_T3/LOSS/TIMEOUT), mfe, mae, bars_to_outcome, seconds_to_outcome, exit_reason,
evaluated_ts, source (LIVE_REPLAY / BACKTEST), data_quality`.

**Outcome definitions (deterministic, conservative):**

- Bars are evaluated in chronological order; for each bar, `high`/`low` are compared against the recorded
  plan levels.
- WIN = target reached strictly before stop in bar sequence. T1 hit ends tracking for T1-outcome (further
  targets are informational only; exit policy assumption documented in ASSUMPTIONS.md A-11).
- LOSS = stop reached strictly before target.
- TIMEOUT = max holding period (bars or expiry, whichever first) without either level.
- **Same-bar ambiguity rule:** if a bar's high and low both cross plan levels and the open does not resolve
  the sequence, the outcome is LOSS (conservative). Rationale: option-buying signals suffer most from
  optimistic intrabar assumptions; conservatism biases calibration downward, never upward.
- Outcomes on DEGRADED data are marked as such and excluded from calibration.

### backtest_runs / backtest_trades
Run metadata (config hash, data range, costs) and per-trade results. Metrics definitions are in
docs/CALIBRATION.md §5.

### calibration_models
Frozen calibrator artifacts: `model_type, fit_ts, train_window, bucket_table (JSON), coefficients (JSON),
metrics (JSON: brier, calibration_error, roc_auc, n)`. A live mapping is only used if `is_active=1`; new
mappings are created by the calibration lab and activated manually after review — no silent online learning.

---

## Data models (core/models.py)

The pipeline passes typed dataclasses between stages, not dicts:

- `Direction` — enum BULLISH/BEARISH/RANGE/UNCERTAIN.
- `MarketRegime` — htf/mtf/ltf Direction each + `alignment` state + `conflict_type` (TREND_CONFLICT /
  PULLBACK / REVERSAL_RISK / ALIGNED / UNCERTAIN).
- `DataQuality` — status + reason; attached to every fetched and derived object.
- `FeatureVector` — per-strike container mirroring the `features` JSON above (missing data stays `None`).
- `StrikeCandidate` — FeatureVector + per-component scores + `model_score` + filter results + reason trail.
- `SideScore` — CALL/PUT side score + the evidence contributing to it.
- `TradePlan` — entry/SL/T1–T3 + `risk_pct` + `reward_risk` + `expected_hold_min`.
- `Recommendation` — final output object; includes `decision` ∈ {RECOMMENDATION, NO_TRADE} and the reason
  trail.

---

## Storage policy

- Raw snapshots and candles: retained forever (SQLite; compress/rotate only after calibration windows have
  been extracted).
- NO_TRADE rows: retained (needed for precision/denominator statistics).
- Nothing is ever zero-filled or forward-filled silently; missing is `NULL` and propagates as MISSING quality.
