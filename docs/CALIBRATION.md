# Calibration & Evaluation Methodology — BLOCKORA_TRADE v3

## 1. The two concepts

### model_score (HEURISTIC)
Composite ranking score, 0–100, built from weighted heuristic components (docs/SCORING.md). It expresses
*relative attractiveness*, never probability. No number it produces may be shown to a user as "% chance".

### calibrated_confidence (CALIBRATED — only after Phase 8)
An estimate of P(outcome = WIN) — defined precisely as **P(T1 reached before SL within max holding period)**
— for a candidate with a given model_score in a given context (market regime, side, strike distance bucket,
IV bucket, session segment). It is produced exclusively by a frozen calibrator fitted on historical outcomes.

Three states, always explicit in output:
- `UNAVAILABLE` — insufficient outcome history (default until Phase 8 gate passes);
- `BUCKETED` — empirical win-rate of the score×context bucket (with sample size shown);
- `MODEL` — logistic/isotonic/Platt calibrator output (with model hash + fit window shown).

**Hard rule:** a bucket or model with fewer than `min_bucket_samples` (default 30) outcomes reports
UNAVAILABLE for decision-gating purposes. Small-sample win rates are never used to justify a trade.

---

## 2. Historical probability — spec §5 rewritten

The spec's `calculate_historical_probability` + `adjust_probability_for_confidence` (+10 if confidence>80 …)
is **rejected as-is**: it adds ad-hoc bonuses to a raw rate, which manufactures confidence.

Replacement: stratified empirical rates. For each context cell (score bucket × regime × side × session
segment), compute hit rate, sample count, Wilson 95% CI. The reported calibrated confidence is the CI-aware
rate; no additive bonuses. Covariate adjustments (IV rank, ADX) become *conditioning variables* (separate
buckets), not score bumps. If cell data is thin, the calibrator falls back to the parent bucket and reports
the coarser state — never interpolates a flattering number.

---

## 3. Outcome definition (exact, referenced by everything downstream)

A tracked recommendation is evaluated on the recorded LTP/candle series of the exact contract
(symbol + expiry + strike + type):

- **WIN** — T1 (premium level) reached before SL within `max_hold_bars` of the execution timeframe.
- **LOSS** — SL reached before T1 within the window.
- **TIMEOUT** — neither level reached by window end. (PnL attribution for TIMEOUT uses last recorded price;
  TIMEOUT does NOT count as a win in any metric.)
- **Same-bar ambiguity:** if a bar's high and low both touch plan levels and the open does not disambiguate
  the sequence → record **LOSS** (conservative, deterministic). Documented in ASSUMPTIONS.md A-10.
- **MFE / MAE** — max favourable / adverse excursion of premium from entry within the window (informational
  features for calibration; not outcome substitutes).
- Outcomes computed on DEGRADED/MISSING data are marked `data_quality != OK` and excluded from calibration.

Win-rate is only meaningful together with expectancy; see §5.

---

## 4. Backtest methodology (Phase 7)

Event-driven, single pass over chronological bars; at each decision timestamp the engine may use only data
with `bar_close_ts <= t`. Concretely enforced by:
- candle store refusing unclosed bars (schema-level guarantee);
- indicators computed only on bars strictly closed before the decision timestamp;
- option-chain features read from the snapshot stored *at* that timestamp, never reconstructed later;
- outcome replay starting strictly after the decision timestamp;
- replayed fills: entry at `ask + slippage_ticks`, exits at `bid - slippage_ticks` (long options), with
  configurable per-contract slippage and latency (default: 1 bar acknowledgment delay in backtest).

Costs included per side: brokerage (flat/lot model), exchange fees, STT on sell, spread crossing. The
backtester reuses the *live* pipeline code path (same scorers, same filters) — no separate "backtest scoring".

Outputs: trade list, equity curve, and every metric in §5, per config-hash so results are attributable.

---

## 5. Metric definitions (exact)

Given closed outcomes with per-trade return series r_i (in premium % and in index points, both reported):

| metric | definition |
|---|---|
| win_rate | wins / closed (TIMEOUT counted as closed, not win) |
| expectancy | E[r] = mean(r_i) |
| profit_factor | Σ wins·r⁺ / Σ losses·|r⁻| (∞ if no losses; report n) |
| avg_win / avg_loss | mean(r_i | r_i>0), mean(|r_i| | r_i<0) |
| reward_risk (realized) | avg_win / avg_loss |
| max_drawdown | max peak-to-trough decline of cumulative equity curve |
| Brier score | mean((p̂_i − y_i)²), y_i ∈ {0,1} T1-before-SL |
| calibration error (ECE) | Σ_b (n_b/N)·|win_rate_b − mean_p̂_b| over score buckets |
| ROC-AUC | rank-based AUC of p̂ (or model_score, for score-discrimination reporting) vs y |
| precision / recall | at the operating threshold chosen in Phase 8, with the threshold itself reported |
| MFE/MAE distribution | per bucket median + p90 (for target placement sanity) |

Reporting rules:
- Every reported metric carries n and the exact window.
- **Expectancy is the headline metric.** A high win_rate with expectancy ≤ 0 after costs is a failure, not a
  success (the brief's explicit concern).
- Score discrimination (ROC-AUC of model_score vs outcome) is reported before any calibration: if the score
  cannot separate outcomes, calibration cannot rescue it and the weights/feature set must be revised first.
- Thresholds (e.g. min calibrated confidence to trade) are chosen on a training window and validated on a
  held-out, later window (walk-forward). No threshold is tuned on the evaluation window.

---

## 6. Calibrator selection (Phase 8)

Candidates, in increasing sophistication, all compared by walk-forward Brier/ECE/AUC and expectancy of the
resulting trade policy:

1. Empirical bucketing (score decile × regime), Wilson-CI-adjusted, `min_bucket_samples` gate.
2. Logistic regression on (model_score, regime one-hot, side, iv_rank, distance_atm) — interpretable,
   coefficient audit required.
3. Isotonic regression (monotone score→probability), overfitting-checked via walk-forward.
4. Platt scaling (as a logistic special case / sanity baseline).

Selection rule: choose the *simplest* model whose walk-forward ECE is within one standard error of the best
candidate. Complexity must buy measurable calibration quality or it is rejected. The fitted artifact is
frozen (calibration_models table, `is_active=1`) and hash-pinned into every subsequent recommendation.

Re-fit cadence: monthly or on regime-shift alarm; activation is a reviewed manual step.

---

## 7. NO-TRADE interaction with calibration

- "score = 91 but this regime historically performs poorly" is implemented as a context gate:
  `bucket.hit_rate < min_contextual_hit_rate (default 0.45) AND n >= min_bucket_samples` → NO_TRADE
  (reason: `calibrated_edge_absent`). Until Phase 8 data exists, this gate is dormant (UNAVAILABLE), never
  fabricated.
- NO_TRADE decisions are stored with their context so the calibration lab can also evaluate "would this
  NO_TRADE policy have helped/hurt" (counterfactual precision of rejections).

---

## 8. What may never be claimed

- "Institutional grade", "high probability", "95% confidence" — banned in output and docs unless the frozen
  calibrator's walk-forward metrics for that exact context support the number, with n ≥ min_bucket_samples.
- Grade labels (A+/A/B) may label *score bands* only, never probability claims.
