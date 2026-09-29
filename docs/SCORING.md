# Scoring Design — BLOCKORA_TRADE v3

## 0. The cardinal rule

`model_score` is an **ordinal ranking metric**. It is NOT a probability. The spec's phrase
"Confidence > 80 → strong recommendation" is treated as a *ranking threshold placeholder*, to be replaced by
empirically calibrated thresholds in Phase 8 (see docs/CALIBRATION.md).

Two separate concepts, never conflated:

| concept | meaning | source |
|---|---|---|
| `model_score` | composite of weighted evidence, 0–100, used to rank candidates | heuristic engine (this doc) |
| `calibrated_confidence` | estimated P(target-before-stop) for a candidate given context | historical outcomes only (docs/CALIBRATION.md) |

Until the outcome database has enough samples, `calibrated_confidence` is reported as
`UNAVAILABLE` and decisions rely on ranking + hard filters only. **The system never invents a confidence
number.**

---

## 1. Score components (config-driven)

All weights live in `config/weights.yaml`. The seven spec factors are kept as *families*, each containing
named sub-components. Adding a module = adding a component entry + its group membership; no code change.

| family | components (Phase 1) | spec weight | group |
|---|---|---|---|
| trend | ema_stack, adx, mtf_alignment | 20 | directional_core |
| market_structure | htf_structure, swing_quality | 15 | directional_core |
| option_chain | pcr_skew, oi_wall_proximity | 15 | chain_evidence |
| oi | oi_change_direction, buildup_class | 10 | chain_evidence |
| volume | volume_expansion, delta_proxy | 10 | flow_evidence |
| momentum | roc, vwap_side, candle_body | 10 | flow_evidence |
| liquidity | spread_score, depth_score | 10 | microstructure |
| volatility | iv_rank_fit, atr_state | 5 | microstructure |
| strike_quality | delta_fit, distance_atm_fit | 3 | strike_fit |
| risk_reward | rr_score | 2 | strike_fit |

(The spec's 7 factors map in: delta_score → strike_quality.delta_fit; iv_score → volatility.iv_rank_fit;
oi_score → oi.*; liquidity_score → liquidity.*; technical_score → split across trend/momentum; rr_score →
risk_reward.rr_score; candle_score → momentum.candle_body — a pattern is one witness, not a verdict.)

Initial weights sum to 100 and are HEURISTIC placeholders — flagged for Phase 8 optimization against outcomes.

---

## 2. Component score normalization

Every component emits a raw value in [0, 10]. Normalization functions are explicit and shared
(`core/scoring_utils.py`):

- `band_score(value, bands)` — piecewise bands (e.g. delta fit: 0.40–0.60 → 10; 0.30/0.70 edges → 7; …).
- `threshold_score(value, good, bad)` — linear interpolation between a good and a bad threshold.
- `binary_score(bool, hit, miss)` — boolean witnesses.

Rules:
- 5.0 = "no information" neutral. A component with MISSING data is not scored 5 silently: it is marked
  UNAVAILABLE and handled by group compensation (§5.3).
- Component scores and their `confidence` (REAL / ESTIMATED / UNAVAILABLE) are persisted in
  `component_scores` for later re-weighting without recomputation.

---

## 3. Two-stage scoring

### Stage 1 — Side score (CALL vs PUT)

Directional families (trend, market_structure, option_chain, oi, volume, momentum) are aggregated to produce
`side_score_call` and `side_score_put`, each in [0, 100], plus a `margin = |call - put|`.

Side gate (config in filters.yaml, all must hold):
- regime classifies the side as aligned, not conflicted (docs/FILTERS.md §5);
- side_score >= min_side_score (default 55, HEURISTIC);
- margin >= min_side_margin (default 10, HEURISTIC);
- no hard data-quality veto at underlying level.

If both sides fail → NO_TRADE("no_side") — never pick the "less bad" side.

### Stage 2 — Strike score

For each candidate on the valid side:

```
model_score = 10 × Σ_groups(raw_g × weight_g × factor_g) / Σ_all_configured_weights
```

where `raw_g` is the group-controlled aggregation defined in §4. Strikes failing liquidity/spread/
expiry/volatility hard gates are removed *before* ranking (docs/FILTERS.md §3). The top survivor is the
candidate; it must still pass candidate-level filters (R/R, entry quality) after the risk engine runs.

Tie-break order (deterministic): higher model_score → lower spread_pct → smaller |distance_atm| → higher
volume.

---

## 4. Double-counting control (mandatory)

The spec's modules (BOS, displacement, FVG, order block, volume expansion, momentum…) describe correlated
phenomena. Summing them independently lets one market event inflate the score through every channel.

Controls, in force at every aggregation level:

1. **Feature groups** (weights.yaml): components that measure the same underlying phenomenon share a family,
   and correlated families share a group (directional_core, chain_evidence, flow_evidence, microstructure,
   strike_fit).
2. **Within-family damping:** inside a family, the top component counts fully and every additional correlated
   component at `within_family_damp` (default 0.5):
   `family_mean = (top + damp·Σrest) / (1 + damp·n_rest)` — one event cannot dominate a family through six
   redundant witnesses.
3. **Within-group damping:** inside a group, the top family counts fully and additional correlated families
   at `within_group_damp` (default 0.5). One event witnessed by volume+momentum (both flow_evidence) cannot
   reach 100 through two weight-10 families: it is bounded near its group weight share.
4. **Total-weight normalization (the binding control):** the score is normalized by the *total configured*
   weight, not by the weights of families that happened to have data:
   `model_score = 10 × Σ_groups(raw_g × weight_g × factor_g) / Σ_all_weights`.
   Evidence existing in only one group can therefore never exceed that group's weight share of 100 — a
   correlated burst in one group lands far below the side/trade gates. Missing evidence *lowers* the score;
   it is never redistributed (removed the earlier redistribution design, which was exploitable).
5. **Cross-group confirmation structure:** evidence classes are tracked and persisted per candidate:
   - `independent`: distinct groups scoring ≥ `independent_group_min_score` (6.0);
   - `correlated`: multiple components/families inside one group pointing the same way (damped per above);
   - `confirmation`: groups that only contribute fully when at least one independent group already agrees
     (chain_evidence, flow_evidence) — otherwise at `confirmation_weight_share` (0.5).
6. **Audit trail:** each score persists its family means, group raws, damped flags and coverage, so
   calibration can later measure whether "many correlated witnesses" actually improved empirical hit rate
   (expected finding: much less than raw score suggests).

This structure is testable (tests/test_double_counting.py: one event, six correlated components → bounded
score inflation).

---

## 5. Data-quality interaction with scoring

- UNAVAILABLE components are excluded from the family mean; because normalization uses the total configured
  weight, missing evidence *lowers* the score. There is deliberately NO weight redistribution (an earlier
  1.25× redistribution design was removed: it let thin evidence look strong).
- A family computed from DEGRADED data contributes at `degraded_factor` (default 0.7) of its value.
- `coverage` (observed group weight / total configured weight) is persisted with every score; candidates
  below the configured coverage cannot pass the side gate.
- The number of UNAVAILABLE components is itself a hard-filter input (docs/FILTERS.md §3, F8).

---

## 6. What scoring explicitly does NOT do

- No "95 = 95% probability". No grade label implies a probability.
- No pattern → automatic trade. Patterns are witnesses (docs/FILTERS.md §6).
- No score without persisted component breakdown (auditable and re-weightable).
- No score survives a hard-filter failure. Score is a ranking input, never a veto override.
