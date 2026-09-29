"""BLOCKORA_TRADE v3 — group-aware weighted scorer.

This is the double-counting control point (docs/SCORING.md section 4):

  1. components live in families, families in groups (config/weights.yaml)
  2. within a family: top component full value, remaining correlated
     components damped
  3. within a group: top family full value, remaining correlated families
     damped
  4. the score is normalized by the TOTAL configured weight, so evidence
     observed in only one group can never exceed that group's weight share —
     missing evidence lowers the score instead of amplifying the remainder
     (no silent weight redistribution)
  5. confirmation-type groups only contribute fully when an independent
     group already agrees

Output is a 0-100 model_score — an ordinal ranking metric, never a probability.
"""
from __future__ import annotations

from typing import Any

from core.models import ComponentScore
from core.scoring_utils import clamp

CONFIRMATION_GROUPS = ("chain_evidence", "flow_evidence")


class SignalScorer:
    def __init__(self, weights_cfg: dict[str, Any]) -> None:
        self.families: dict[str, Any] = weights_cfg["families"]
        agg = weights_cfg.get("aggregation", {})
        self.family_damp = float(agg.get("within_family_damp", 0.5))
        self.group_damp = float(agg.get("within_group_damp", 0.5))
        self.confirm_share = float(agg.get("confirmation_weight_share", 0.5))
        self.indep_min = float(agg.get("independent_group_min_score", 6.0))
        self.degraded_factor = float(agg.get("degraded_data_factor", 0.7))
        # total configured weight across ALL groups (normalization denominator)
        self.total_weight = sum(f["weight"] for f in self.families.values())

        self.group_weights: dict[str, float] = {}
        for fam, cfg in self.families.items():
            self.group_weights[cfg["group"]] = \
                self.group_weights.get(cfg["group"], 0.0) + cfg["weight"]

    # ------------------------------------------------------------------
    def _family_mean(self, comps: list[ComponentScore]) -> tuple[float | None, int]:
        """Damped mean over scored components; (None, n_unavailable) if none scored."""
        scored = sorted((c for c in comps if c.score is not None),
                        key=lambda c: c.score, reverse=True)
        unavailable = len(comps) - len(scored)
        if not scored:
            return None, unavailable
        top = scored[0].score
        rest = scored[1:]
        mean = (top + self.family_damp * sum(c.score for c in rest)) / (1 + self.family_damp * len(rest))
        return clamp(mean), unavailable

    def score(self, components: list[ComponentScore],
              degraded_families: set[str] | None = None,
              families_subset: set[str] | None = None) -> tuple[float, dict[str, Any]]:
        """Return (model_score 0-100, audit dict).

        degraded_families: families computed from DEGRADED data contribute at
        degraded_factor of their value. families_subset restricts which
        families may contribute (used later for side scoring); normalization
        always uses the full configured weight so partial evidence stays
        honestly partial.
        """
        degraded_families = degraded_families or set()
        audit: dict[str, Any] = {
            "families": {}, "groups": {}, "unavailable_components": 0,
            "coverage": 0.0, "confirmation_suppressed": [],
            "independent_groups": [],
        }

        by_family: dict[str, list[ComponentScore]] = {}
        for c in components:
            if families_subset is None or c.family in families_subset:
                by_family.setdefault(c.family, []).append(c)

        # 1) family means (within-family damping)
        family_means: dict[str, float] = {}
        for fam, comps in by_family.items():
            mean, n_unavail = self._family_mean(comps)
            audit["unavailable_components"] += n_unavail
            if mean is None:
                continue
            if fam in degraded_families:
                mean *= self.degraded_factor
            family_means[fam] = mean
            audit["families"][fam] = round(mean, 3)

        if not family_means or self.total_weight <= 0:
            return 0.0, audit

        # 2) group raws (within-group damping across family means)
        by_group: dict[str, list[float]] = {}
        group_observed_weight: dict[str, float] = {}
        for fam, mean in family_means.items():
            grp = self.families[fam]["group"]
            by_group.setdefault(grp, []).append(mean)
            group_observed_weight[grp] = group_observed_weight.get(grp, 0.0) + \
                self.families[fam]["weight"]

        group_raws: dict[str, float] = {}
        for grp, means in by_group.items():
            ordered = sorted(means, reverse=True)
            raw = (ordered[0] + self.group_damp * sum(ordered[1:])) / \
                (1 + self.group_damp * len(ordered[1:]))
            group_raws[grp] = clamp(raw)

        # 3) independent-group evaluation -> confirmation gating
        independent = [g for g, r in group_raws.items() if r >= self.indep_min]
        audit["independent_groups"] = independent

        # 4) weighted aggregate normalized by TOTAL configured weight.
        # A group contributes only through the weight of families that
        # actually observed data — missing families cannot borrow weight from
        # present ones (docs/SCORING.md section 4).
        acc = 0.0
        observed_weight = 0.0
        for grp, raw in group_raws.items():
            w_obs = group_observed_weight.get(grp, 0.0)
            factor = 1.0
            if not independent and grp in CONFIRMATION_GROUPS:
                factor = self.confirm_share
                audit["confirmation_suppressed"].append(grp)
            contribution = raw * w_obs * factor
            acc += contribution
            observed_weight += w_obs
            audit["groups"][grp] = {
                "raw": round(raw, 3), "observed_weight": round(w_obs, 1),
                "contribution": round(contribution, 2),
                "confirmation_damped": factor < 1.0,
            }

        audit["coverage"] = round(observed_weight / self.total_weight, 3)
        score = (acc / self.total_weight) * 10.0
        return round(clamp(score, 0.0, 100.0), 1), audit
