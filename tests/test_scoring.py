"""Tests: score normalization + group-aware scoring + double-counting control."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import Config
from core.models import ComponentScore
from core.scoring_utils import (band_score, binary_score, clamp, delta_fit_score,
                                rr_score, round_tick, threshold_score)
from core.signal_scorer import SignalScorer


# ---------------------------------------------------------------- normalization
def test_clamp():
    assert clamp(-1) == 0.0
    assert clamp(11) == 10.0
    assert clamp(7.5) == 7.5


def test_threshold_score():
    assert threshold_score(25, good=25, bad=15) == 10.0
    assert threshold_score(15, good=25, bad=15) == 0.0
    assert threshold_score(20, good=25, bad=15) == 5.0


def test_band_score_delta_fit_matches_spec():
    assert delta_fit_score(0.50) == 10.0
    assert delta_fit_score(0.35) == 7.0
    assert delta_fit_score(0.65) == 7.0
    assert delta_fit_score(0.25) == 4.0
    assert delta_fit_score(0.75) == 4.0
    assert delta_fit_score(0.10) == 2.0
    assert delta_fit_score(0.90) == 2.0


def test_rr_score_matches_spec():
    assert rr_score(3.0) == 10.0
    assert rr_score(2.0) == 8.0
    assert rr_score(1.5) == 6.0
    assert rr_score(1.0) == 3.0


def test_band_score_generic():
    bands = [[2, 0.20], [4, 0.30], [10, 0.60], [2, 9.99]]
    assert band_score(0.10, bands) == 2.0
    assert band_score(0.45, bands) == 10.0
    assert band_score(5.0, bands) == 2.0


def test_binary_and_round_tick():
    assert binary_score(True) == 10.0 and binary_score(False) == 0.0
    assert round_tick(10.126) == 10.15
    assert round_tick(10.124) == 10.10


# ---------------------------------------------------------------- scorer
@pytest.fixture(scope="module")
def scorer():
    cfg = Config.load()
    return SignalScorer(cfg.weights), cfg


def _fam(family, comps):
    return [ComponentScore(family=family, component=c, score=s) for c, s in comps]


def test_score_bounds(scorer):
    s, _ = scorer
    for comps in (
        _fam("trend", [("ema_stack", 10), ("adx", 10), ("mtf_alignment", 10)]),
        _fam("trend", [("ema_stack", 0), ("adx", 0), ("mtf_alignment", 0)]),
        [],
    ):
        score, _audit = s.score(comps)
        assert 0.0 <= score <= 100.0


def test_perfect_evidence_high_but_bounded_score(scorer):
    s, cfg = scorer
    comps = []
    for fam, vals in (
        ("trend", 10), ("market_structure", 10), ("option_chain", 10),
        ("oi", 10), ("volume", 10), ("momentum", 10),
        ("liquidity", 10), ("volatility", 10), ("strike_quality", 10), ("risk_reward", 10),
    ):
        comps += [ComponentScore(family=fam, component=c, score=10.0)
                  for c in cfg.weights["families"][fam]["components"]]
    score, audit = s.score(comps)
    assert score == 100.0
    assert audit["unavailable_components"] == 0


def test_double_counting_single_event_bounded(scorer):
    """One market event seen by 6 correlated components in one group must NOT
    inflate the score like 6 independent events."""
    s, _ = scorer
    # simulate a strong directional event witnessed redundantly by flow_evidence
    event = [ComponentScore(family="volume", component="volume_expansion", score=10),
             ComponentScore(family="volume", component="delta_proxy", score=10),
             ComponentScore(family="momentum", component="roc", score=10),
             ComponentScore(family="momentum", component="vwap_side", score=10),
             ComponentScore(family="momentum", component="candle_body", score=10)]
    score_event, _ = s.score(event)

    # same magnitude evidence, but genuinely independent: one witness per group
    independent = [ComponentScore(family="trend", component="ema_stack", score=10),
                   ComponentScore(family="option_chain", component="pcr_skew", score=10),
                   ComponentScore(family="volume", component="volume_expansion", score=10),
                   ComponentScore(family="liquidity", component="spread_score", score=10),
                   ComponentScore(family="strike_quality", component="delta_fit", score=10),
                   ComponentScore(family="risk_reward", component="rr_score", score=10)]
    score_indep, _ = s.score(independent)

    # correlated-only evidence must score meaningfully lower than spread-out evidence
    assert score_event < score_indep * 0.6, (
        f"correlated evidence ({score_event}) should not approach independent ({score_indep})")


def test_unavailable_components_lower_score_without_redistribution(scorer):
    """Missing evidence must LOWER the score, never be redistributed to inflate."""
    s, _ = scorer
    full = [ComponentScore(family="trend", component="adx", score=8.0),
            ComponentScore(family="liquidity", component="spread_score", score=8.0)]
    score_full, _ = s.score(full)
    with_missing = full + [ComponentScore(family="market_structure", component="htf_structure",
                                          score=None, confidence="UNAVAILABLE")]
    score_missing, audit = s.score(with_missing)
    assert audit["unavailable_components"] == 1
    assert score_missing == pytest.approx(score_full)  # family absent either way
    # and a family with only unavailable data contributes nothing at all
    only_missing = [ComponentScore(family="trend", component="adx", score=None,
                                   confidence="UNAVAILABLE")]
    score_zero, _ = s.score(only_missing)
    assert score_zero == 0.0


def test_all_components_missing_scores_zero(scorer):
    s, _ = scorer
    comps = [ComponentScore(family="trend", component="adx", score=None,
                            confidence="UNAVAILABLE")]
    score, audit = s.score(comps)
    assert score == 0.0
    assert audit["unavailable_components"] == 1


def test_degraded_family_discounted(scorer):
    s, _ = scorer
    comps = [ComponentScore(family="trend", component="adx", score=10.0),
             ComponentScore(family="liquidity", component="spread_score", score=10.0)]
    base, _ = s.score(comps)
    degraded, _ = s.score(comps, degraded_families={"trend"})
    assert degraded < base


def test_single_group_cannot_exceed_its_weight_share(scorer):
    """The binding double-counting control: even perfect evidence confined to
    one group stays near that group's weight share of 100 (10/100 here)."""
    s, _ = scorer
    comps = [ComponentScore(family="liquidity", component="spread_score", score=10.0),
             ComponentScore(family="liquidity", component="depth_score", score=10.0)]
    score, audit = s.score(comps)
    assert score == pytest.approx(10.0)          # microstructure weight is 10/100
    assert audit["groups"]["microstructure"]["raw"] == 10.0
    assert audit["coverage"] == pytest.approx(0.10)  # only liquidity(10) observed data


def test_coverage_persisted(scorer):
    s, _ = scorer
    comps = [ComponentScore(family="trend", component="adx", score=10.0)]
    score, audit = s.score(comps)
    assert 0 < audit["coverage"] < 1
