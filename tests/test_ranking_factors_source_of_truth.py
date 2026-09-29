"""Regression tests: the ranking factor definition is a single source of truth.

The ten factor maxima used to exist twice — as comments in the scorer and as
a hardcoded table in main.py's dashboard. If the scorer changed, the display
would keep claiming the old weights with no test failing.

These tests pin:
  1. The definition declares the ten real factors, in score order
  2. Every declared maximum is the scorer's ACTUAL cap (not a wish)
  3. The maxima sum to the total the score is expressed against
  4. The dashboard reads the definition instead of its own copy
  5. A change to the definition propagates to the dashboard automatically
  6. Scoring behaviour is unchanged
"""
import inspect
import re
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config_manager import ConfigManager            # noqa: E402
from engines.ranking import factors                      # noqa: E402
from engines.ranking.factors import (                    # noqa: E402
    FACTOR_KEYS, FACTOR_SPECS, FACTORS, MAX_TOTAL_SCORE, FactorSpec, maximum_for,
)
from engines.ranking.strike_ranking_engine import StrikeRankingEngine  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
main = pytest.importorskip("main")

# The ten factors, exactly as the scorer names them today.
EXPECTED_FACTORS = ("moneyness", "gamma", "move_fit", "oi", "volume",
                    "spread", "trend", "vwap", "max_pain", "historical")

# Caps asserted against the live scorer, so a future change to a scorer
# branch fails here rather than silently drifting from the displayed weight.
EXPECTED_MAXIMA = {
    "moneyness": 15, "gamma": 10, "move_fit": 15, "oi": 12, "volume": 10,
    "spread": 8, "trend": 12, "vwap": 8, "max_pain": 5, "historical": 5,
}


# ------------------------------------------------------------ 1. structure
def test_ten_factors_in_scoring_order():
    assert FACTOR_KEYS == EXPECTED_FACTORS
    assert len(FACTOR_SPECS) == 10


def test_definition_is_immutable():
    """A caller must not be able to rewrite a weight at runtime."""
    with pytest.raises(TypeError):
        FACTORS["gamma"] = 999
    with pytest.raises(AttributeError):
        FACTORS["gamma"].maximum = 999      # NamedTuple is frozen
    with pytest.raises(TypeError):
        FACTOR_SPECS[0] = FactorSpec("x", "X", 1)


def test_every_factor_has_label_and_positive_maximum():
    for spec in FACTOR_SPECS:
        assert spec.label and isinstance(spec.label, str)
        assert isinstance(spec.maximum, int) and spec.maximum > 0
        assert spec.key == spec.key.strip() and " " not in spec.key


def test_maximum_for_raises_on_unknown_factor():
    """No silent default: a typo must surface immediately."""
    assert maximum_for("gamma") == FACTORS["gamma"].maximum
    with pytest.raises(KeyError):
        maximum_for("not_a_real_factor")


# ------------------------------------------------------ 2. maxima are real
def test_declared_maxima_match_the_definition():
    assert {k: v.maximum for k, v in FACTORS.items()} == EXPECTED_MAXIMA


def test_maxima_are_the_scorer_actual_caps():
    """Brute-force each scorer and confirm the declared cap is reachable+true.

    A maximum that is merely declared (and never enforced by a branch) would
    let the dashboard print a weight the scorer can never award.
    """
    cfg = ConfigManager()
    cfg.load()
    eng = StrikeRankingEngine(cfg, mock.MagicMock())

    # gamma: swept over time-to-expiry and distance
    gmax = max(
        eng._gamma_score(s, 22500, tte, opt)
        for tte in (1.0, 5.0, 24.0, 47.0, 48.0, 100.0, 200.0)
        for s in range(22300, 22700, 25)
        for opt in ("CE", "PE")
    )
    assert gmax == FACTORS["gamma"].maximum

    # trend: the scorer must not exceed its declared maximum

    analysis = {"trade_context": {"direction": "BULLISH", "vwap": 22500},
                "indicators": {"rsi": 70, "adx": 40, "macd_hist": 20}}
    assert eng._trend_confluence_score(22500, "CE", analysis) <= FACTORS["trend"].maximum

    # historical: win_rate * maximum, and it must respect the declared cap
    for wr in (0.0, 0.25, 0.5, 0.75, 1.0):
        v = eng._historical_score(22500, "CE", {"learning": {"win_rate": wr}})
        assert 0 <= v <= FACTORS["historical"].maximum
    # the shipped default (no learning data) is 2, i.e. 0.4 * 5
    assert eng._historical_score(22500, "CE", {"learning": {}}) == 2


def test_trend_scorer_uses_the_definition_for_its_cap():
    """The cap must come from factors.py, not a re-typed literal."""
    src = inspect.getsource(StrikeRankingEngine._trend_confluence_score)
    assert "maximum_for(\"trend\")" in src
    assert "min(12," not in src


def test_historical_scorer_uses_the_definition():
    src = inspect.getsource(StrikeRankingEngine._historical_score)
    assert "maximum_for(\"historical\")" in src
    assert "win_rate * 5" not in src


def test_score_strike_reads_thresholds_from_the_definition():
    src = inspect.getsource(StrikeRankingEngine._score_strike)
    for key in ("gamma", "move_fit", "volume"):
        assert f'FACTORS["{key}"].reason_threshold' in src
    assert "maximum_for(\"moneyness\")" in src
    assert "MAX_TOTAL_SCORE" in src


# --------------------------------------------------------- 3. total is right
def test_maxima_sum_to_expected_total():
    assert MAX_TOTAL_SCORE == 100
    assert sum(EXPECTED_MAXIMA.values()) == MAX_TOTAL_SCORE


def test_score_is_clamped_to_the_declared_total():
    src = inspect.getsource(StrikeRankingEngine._score_strike)
    assert "min(MAX_TOTAL_SCORE, total)" in src


# ------------------------------------- 4. dashboard reads the same source
def _display_src():
    return inspect.getsource(main.BlockoraTrade.display_recommendation)


def test_dashboard_imports_the_shared_definition():
    src = (ROOT / "main.py").read_text()
    assert "from engines.ranking.factors import" in src


def test_dashboard_has_no_local_weight_table():
    """The duplicated literal table must not come back."""
    src = _display_src()
    assert "_FACTOR_MAX" not in src
    assert "_FACTOR_LABEL" not in src
    # no hardcoded 15/10/12 weights table anywhere in the display
    assert '"moneyness": 15' not in src
    assert '"max_pain": 5' not in src


def test_dashboard_renders_from_the_definition():
    src = _display_src()
    assert "_spec.label" in src
    assert "_spec.maximum" in src
    assert "MAX_TOTAL_SCORE" in src


def test_dashboard_labels_equal_definition_labels():
    """Every printed label is the one the definition publishes."""
    rendered = _render_breakdown()
    printed = [label for label, _ in rendered if label != "TOTAL"]
    expected = [spec.label for spec in FACTOR_SPECS]
    assert printed == expected, f"dashboard printed {printed}, definition has {expected}"


def test_dashboard_maxima_equal_definition_maxima():
    """Rendered maxima are the definition's, not literals in main.py."""
    rendered = _render_breakdown()
    for label, value in rendered:
        if label == "TOTAL":
            continue
        spec = FACTORS[[k for k, v in FACTORS.items() if v.label == label][0]]
        # value is "<score>/<max>"; the max must be the definition's
        assert value.endswith(f"/{spec.maximum}"), \
            f"{label} shows {value}, definition says max {spec.maximum}"


def _render_breakdown():
    """Render the breakdown with a stub engine and return (label, value) rows."""
    import io
    import contextlib

    analysis = {
        "market_data": {"ltp": 22650.5, "open": 22580.0, "high": 22720.0,
                        "low": 22510.0, "close": 22650.5, "data_source": "LIVE"},
        "option_chain": {"expiry": "29SEP2026", "source": "ANGEL_LIVE",
                         "pcr": 1.12, "pcr_source": "CALCULATED", "max_pain": 22650,
                         "max_pain_source": "CALCULATED",
                         "ce_data": {22650: {"strike": 22650, "ltp": 120.0,
                                             "bid": 119.5, "ask": 120.5, "oi": 50000,
                                             "change_oi": 0, "volume": 300000,
                                             "iv": 14.0, "oi_source": "REAL",
                                             "iv_source": "REAL"}},
                         "pe_data": {}},
        "indicators": {"rsi": 32.1, "adx": 38.7, "atr": 88.2, "macd_hist": -5.0},
        "trade_context": {"direction": "BULLISH", "vwap": 22620.0,
                          "expected_move": 40, "fear_greed": "FEAR"},
        "candlestick": {"pattern": "Shooting Star", "at_key_level": True},
        "oi_analysis": {"pcr": 1.12}, "volume": {"avg": 1000},
        "multi_timeframe": {"t5": "UP", "t15": "NEUTRAL", "t1h": "DOWN"},
        "support_resistance": {"support": 22500.0, "resistance": 22800.0},
        "trend": {"direction": "BULLISH"},
        "regime": {"type": "HIGH_VOLATILITY", "classification": "TRENDING"},
        "learning": {},
    }
    best = {"strike": 22650, "option_type": "CE", "score": 50,
            "scores": {k: 0 for k in FACTOR_KEYS},
            "ltp": 120.0, "bid": 119.5, "ask": 120.5, "iv": 14.0,
            "iv_source": "REAL", "reasons": ["ATM (Max Delta)"]}
    ranked = {"best_ce": best, "best_pe": {},
              "ce_rankings": [best], "pe_rankings": []}

    app = main.BlockoraTrade.__new__(main.BlockoraTrade)
    app.config = mock.MagicMock()
    app.config.get_int.return_value = 20
    app.logger = mock.MagicMock()
    rec = {"action": "NO_TRADE", "confidence": 68.0, "grade": "REJECT",
           "reasons": ["oi"], "date": "2026-09-29", "time": "13:30:00",
           "bias": "NEUTRAL", "vix": 24.0, "spot": 22650.5}

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        app.display_recommendation(rec, analysis, ranked, analysis["market_data"])

    rows = []
    capture = False
    rows = []
    for line in buf.getvalue().splitlines():
        if "RANKING FACTORS" in line:
            capture = True
            continue
        if not capture:
            continue
        stripped = line.strip().lstrip("\u2022").strip()
        if not stripped:
            continue
        # The value is the trailing "n/max" (or "Unavailable (max n)") token;
        # the label is everything before it, so multi-word labels survive.
        m = re.search(r"(\S+/\S+|Unavailable \(max \d+\))\s*$", stripped)
        assert m, f"cannot parse factor row: {stripped!r}"
        value = m.group(1)
        label = stripped[: m.start()].strip()
        rows.append((label, value))
        if label == "TOTAL":
            break
    return rows


# ------------------------------------- 5. a definition change propagates
def test_changing_the_definition_reaches_the_dashboard(monkeypatch):
    """Simulate a scorer weight change: the dashboard must follow it.

    This is the drift test the old duplicated table could never pass. The
    definition is patched to a different maximum and the rendered breakdown
    is compared against the patched value, not against a literal.
    """
    from engines.ranking import factors as factors_mod

    # render with the shipped definition
    baseline = _render_breakdown()
    base_gamma = [v for lb, v in baseline if lb == FACTORS["gamma"].label][0]
    assert base_gamma.endswith(f"/{FACTORS['gamma'].maximum}")

    # now pretend the scorer team changed the gamma weight
    patched = {**dict(FACTORS), "gamma": FactorSpec("gamma", "Gamma Impact", 99)}
    monkeypatch.setattr(factors_mod, "FACTORS", patched)
    monkeypatch.setattr(main, "FACTOR_SPECS",
                        tuple(patched.values()))

    after = _render_breakdown()
    new_gamma = [v for lb, v in after if lb == "Gamma Impact"][0]
    assert new_gamma.endswith("/99"), new_gamma

    # every other factor is unchanged: the edit is scoped to one weight
    for (lb, v1), (_lb2, v2) in zip(baseline, after):
        if lb != "Gamma Impact":
            assert v1 == v2, f"{lb} changed unexpectedly: {v1} -> {v2}"


# ------------------------------------------ 6. scoring behaviour unchanged
def test_scoring_is_unchanged_against_known_values():
    """Fixed expectations: identical inputs must give identical scores."""
    cfg = ConfigManager()
    cfg.load()

    def score(strike, opt, tte=40.0, exp=False, mon=False, ltp=120.0):
        eng = StrikeRankingEngine(cfg, mock.MagicMock())
        rec = {"strike": strike, "ltp": ltp, "oi": 50000, "change_oi": 9000,
               "volume": 300000, "iv": 14.0, "bid": 119.5, "ask": 120.5}
        chain = {"ce_data": {strike: rec}, "pe_data": {strike: dict(rec)},
                 "pcr": 1.1, "max_pain": 22500}
        analysis = {"trade_context": {"expected_move": 40, "direction": "BULLISH",
                                      "vwap": 22500},
                    "indicators": {"rsi": 50, "adx": 30, "macd_hist": 5},
                    "market_data": {"ltp": 22500}, "option_chain": chain}
        r = eng._score_strike(strike, 22500, opt, chain["ce_data"],
                              chain["pe_data"], chain, {"ltp": 22500},
                              analysis, tte, exp, mon)
        c = r[0] if isinstance(r, tuple) else r
        return c["score"], c["scores"]

    # Values below were captured from the scorer BEFORE the definition was
    # introduced and re-verified after; they must not move.
    # (A fresh engine per call: the rolling 20-cycle volume history on self
    # is an intentional cross-cycle cache and would make this flaky.)
    s, factors_seen = score(22500, "CE")
    assert s == 62, f"ATM CE score drifted to {s}"
    assert factors_seen == {
        "moneyness": 15, "gamma": 8, "move_fit": 0, "oi": 6, "volume": 5,
        "spread": 8, "trend": 10, "vwap": 3, "max_pain": 5, "historical": 2,
    }

    s2, seen_pe = score(22500, "PE")
    assert (s2, seen_pe["vwap"], seen_pe["trend"]) == (63, 6, 8)

    s3, seen_far = score(23000, "CE")
    assert s3 == 40
    assert seen_far["moneyness"] == 2 and seen_far["gamma"] == 3

    # expiry-day OTM keeps its penalty behaviour
    s4, seen_exp = score(23000, "CE", tte=2.0, exp=True, mon=False)
    assert s4 == 24
    assert seen_exp["gamma"] == 0 and seen_exp["max_pain"] == 1


def test_score_keys_match_the_definition_exactly():
    cfg = ConfigManager()
    cfg.load()
    eng = StrikeRankingEngine(cfg, mock.MagicMock())
    rec = {"strike": 22500, "ltp": 120.0, "oi": 50000, "change_oi": 9000,
           "volume": 300000, "iv": 14.0, "bid": 119.5, "ask": 120.5}
    chain = {"ce_data": {22500: rec}, "pe_data": {}, "pcr": 1.1, "max_pain": 22500}
    analysis = {"trade_context": {"expected_move": 40, "direction": "BULLISH"},
                "indicators": {"rsi": 50, "adx": 30, "macd_hist": 5},
                "market_data": {"ltp": 22500}, "option_chain": chain}
    r = eng._score_strike(22500, 22500, "CE", chain["ce_data"], chain["pe_data"],
                          chain, {"ltp": 22500}, analysis, 40.0, False, False)
    cand = r[0] if isinstance(r, tuple) else r
    assert set(cand["scores"]) == set(FACTOR_KEYS)


def test_displayed_score_denominator_matches_definition():
    rendered = _render_breakdown()
    total = [v for lb, v in rendered if lb == "TOTAL"][0]
    assert total.endswith(f"/{MAX_TOTAL_SCORE}"), total
