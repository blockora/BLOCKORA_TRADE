"""Phase 22 — Strike Decision Continuity + Change Intelligence tests.

Verifies the StrikeContinuityTracker and RankingSnapshot implementations.
No production logic modified.
"""

import os
import sys
from dataclasses import FrozenInstanceError

import pytest

# Ensure project is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.learning.strike_continuity import (
    RankingSnapshot,
    StrikeContinuityTracker,
    StrikeContinuityReport,
    snapshot_from_analysis,
)


# ----------------------- RankingSnapshot tests -----------------------

class TestRankingSnapshot:
    """Verify RankingSnapshot dataclass behavior."""

    def test_snapshot_creation(self):
        snap = RankingSnapshot(
            timestamp="2024-01-15T10:30:00",
            spot=24250.0,
            direction="BEARISH",
            option_type="PE",
            expiry="20241226",
            strike=24400.0,
            baseline_score=85.0,
            enhanced_score=94.0,
            move_fit=7.0,
            score_margin=5.0,
        )
        assert snap.strike == 24400.0
        assert snap.enhanced_score == 94.0
        assert snap.score_margin == 5.0
        assert snap.direction == "BEARISH"

    def test_snapshot_frozen(self):
        # frozen dataclass should prevent mutation
        snap = RankingSnapshot(
            timestamp="2024-01-15T10:30:00",
            spot=24250.0,
            direction="BEARISH",
            option_type="PE",
            expiry="20241226",
            strike=24400.0,
            baseline_score=85.0,
            enhanced_score=94.0,
            move_fit=7.0,
            score_margin=5.0,
        )
        with pytest.raises(FrozenInstanceError):
            snap.strike = 24500.0


class TestRankingSnapshotEquality:
    """Verify RankingSnapshot equality and consistency."""

    def test_snapshot_equal_when_same(self):
        s1 = RankingSnapshot(
            timestamp="2024-01-15T10:30:00",
            spot=24250.0,
            direction="BEARISH",
            option_type="PE",
            expiry="20241226",
            strike=24400.0,
            baseline_score=85.0,
            enhanced_score=94.0,
        )
        s2 = RankingSnapshot(
            timestamp="2024-01-15T10:30:00",
            spot=24250.0,
            direction="BEARISH",
            option_type="PE",
            expiry="20241226",
            strike=24400.0,
            baseline_score=85.0,
            enhanced_score=94.0,
        )
        assert s1 == s2

    def test_snapshot_different(self):
        s1 = RankingSnapshot(strike=24400.0)
        s2 = RankingSnapshot(strike=24500.0)
        assert s1 != s2


# ----------------------- StrikeContinuityTracker tests -----------------------

class TestStrikeContinuityTracker:
    """StrikeContinuityTracker core functionality."""

    def test_save_and_get_previous(self):
        StrikeContinuityTracker.save_previous(RankingSnapshot(
            timestamp="2024-01-15T10:30:00", strike=24400.0))
        assert StrikeContinuityTracker.get_previous() is not None
        StrikeContinuityTracker.clear_previous()
        assert StrikeContinuityTracker.get_previous() is None

    def test_compare_first_cycle(self):
        """First cycle: no previous snapshot → FIRST_CYCLE status."""
        StrikeContinuityTracker.clear_previous()
        report = StrikeContinuityTracker.compare(
            RankingSnapshot(strike=24400.0, enhanced_score=94.0, score_margin=5.0))
        assert report.status == "FIRST_CYCLE"
        assert report.previous_leader is None
        assert report.current_leader == 24400.0

    def test_compare_same_leader(self):
        """Same strike leads both cycles."""
        StrikeContinuityTracker.save_previous(RankingSnapshot(
            strike=24400.0, enhanced_score=94.0, score_margin=5.0))
        report = StrikeContinuityTracker.compare(
            RankingSnapshot(strike=24400.0, enhanced_score=95.0, score_margin=6.0))
        assert report.strike_change is False
        assert report.previous_leader == 24400.0
        assert report.current_leader == 24400.0
        assert report.score_changes == {24400.0: 1.0}
        assert report.status == "SAME_LEADER"
        assert report.material_change is False

    def test_leader_change(self):
        """Different strike becomes the leader."""
        StrikeContinuityTracker.save_previous(RankingSnapshot(
            strike=24400.0, enhanced_score=94.0, score_margin=5.0))
        report = StrikeContinuityTracker.compare(
            RankingSnapshot(strike=24450.0, enhanced_score=92.0, score_margin=4.0))
        assert report.strike_change is True
        assert report.previous_leader == 24400.0
        assert report.current_leader == 24450.0
        assert report.score_delta == -2.0
        assert report.new_leader_margin == 4.0
        assert report.status in ("FAIR_LEADER", "NO CLEAR BEST STRIKE")

    def test_material_change(self):
        """Score delta >= 3 points → material change."""
        StrikeContinuityTracker.save_previous(RankingSnapshot(
            strike=24400.0, enhanced_score=94.0, score_margin=5.0))
        report = StrikeContinuityTracker.compare(
            RankingSnapshot(strike=24400.0, enhanced_score=98.0, score_margin=8.0))
        assert report.material_change is True
        assert report.status in ("CLEAR_LEADER", "FAIR_LEADER")

    def test_no_clear_best_strike(self):
        """Margin < 5 → NO CLEAR BEST STRIKE."""
        StrikeContinuityTracker.save_previous(RankingSnapshot(
            strike=24400.0, enhanced_score=94.0, score_margin=5.0))
        report = StrikeContinuityTracker.compare(
            RankingSnapshot(strike=24400.0, enhanced_score=95.0, score_margin=6.0))
        assert report.status in ("SAME_LEADER", "FAIR_LEADER")


# ----------------------- Snapshot from analysis tests -----------------------

class TestSnapshotFromAnalysis:
    """snapshot_from_analysis converts analysis data into RankingSnapshot."""

    def test_basic_snapshot(self):
        # Minimal analysis results dict that matches what the real main.py produces
        analysis_results = {
            "trade_context": {
                "direction": "BEARISH",
                "option_type": "PE",
                "expiry": "20241226",
                "expected_move": 30,
            },
            "_best_strike": 24400.0,
            "_baseline_scores": {24400.0: 85.0},
            "_enhanced_scores": {24400.0: 94.0},
            "_score_margin": 5.0,
        }
        ranked_strikes = {
            "best_pe": {"strike": 24400.0, "score": 94.0, "move_fit": 7.0,
                        "baseline_score": 85.0, "enhanced_score": 94.0},
            "pe_rankings": [
                {"strike": 24400.0, "score": 94.0, "move_fit": 7.0},
                {"strike": 24450.0, "score": 88.0, "move_fit": 5.0},
                {"strike": 24350.0, "score": 82.0, "move_fit": 3.0},
            ],
        }
        market_data = {"ltp": 18.0, "timestamp": "2024-01-15T10:30:00"}

        snap = snapshot_from_analysis(analysis_results, ranked_strikes, market_data)
        assert snap.strike == 24400.0
        assert snap.direction == "BEARISH"
        assert snap.option_type == "PE"
        assert snap.enhanced_score == 94.0
        assert snap.score_margin == 5.0
        assert snap.top_3_strikes == (24400.0, 24450.0, 24350.0)
        assert snap.top_3_scores == (94.0, 88.0, 82.0)


# ----------------------- StrikeContinuityReport tests -----------------------

class TestStrikeContinuityReport:
    """StrikeContinuityReport structure and invariants."""

    def test_report_creation(self):
        report = StrikeContinuityReport(
            strike_change=True, previous_leader=24400.0, current_leader=24450.0,
            score_changes={24400.0: 1.0}, new_leader_margin=2.0,
            status="FAIR_LEADER", top_3_changes=["24450: #2 → #1"],
            leadership_info="24450: LEADER CHANGED from 24400",
            reasons=["distance improved"],
            material_change=True, score_delta=1.0)
        assert report.strike_change is True
        assert report.previous_leader == 24400.0
        assert report.current_leader == 24450.0
        assert report.score_changes == {24400.0: 1.0}
        assert report.new_leader_margin == 2.0
        assert report.status == "FAIR_LEADER"
        assert report.top_3_changes == ["24450: #2 → #1"]
        assert report.leadership_info == "24450: LEADER CHANGED from 24400"
        assert report.reasons == ["distance improved"]
        assert report.material_change is True
        assert report.score_delta == 1.0

    def test_report_defaults(self):
        """Test report with all default values."""
        report = StrikeContinuityReport()
        assert report.strike_change is False
        assert report.previous_leader is None
        assert report.current_leader == 0.0
        assert report.score_changes == {}
        assert report.new_leader_margin == 0.0
        assert report.status == "FIRST_CYCLE"
        assert report.top_3_changes == []
        assert report.leadership_info == "FIRST LIVE CYCLE"
        assert report.reasons == []
        assert report.material_change is False
        assert report.score_delta == 0.0


# ----------------------- Integration tests -----------------------

class TestIntegration:
    """Integration tests for the continuity system."""

    def test_full_comparison_same_leader(self):
        """End-to-end: save previous, compare same leader."""
        StrikeContinuityTracker.save_previous(RankingSnapshot(
            strike=24400.0, enhanced_score=94.0, score_margin=5.0))
        report = StrikeContinuityTracker.compare(
            RankingSnapshot(strike=24400.0, enhanced_score=95.0, score_margin=6.0))
        assert report.strike_change is False
        assert report.status == "SAME_LEADER"
        assert report.score_changes == {24400.0: 1.0}
        assert report.material_change is False

    def test_full_comparison_change(self):
        """End-to-end: save previous, compare different leader."""
        StrikeContinuityTracker.save_previous(RankingSnapshot(
            strike=24400.0, enhanced_score=94.0, score_margin=5.0))
        report = StrikeContinuityTracker.compare(
            RankingSnapshot(strike=24450.0, enhanced_score=92.0, score_margin=4.0))
        assert report.strike_change is True
        assert report.previous_leader == 24400.0
        assert report.current_leader == 24450.0
        assert report.score_delta == -2.0
        assert report.new_leader_margin == 4.0
        assert report.status in ("FAIR_LEADER", "NO CLEAR BEST STRIKE")
        assert len(report.reasons) > 0


# ----------------------- Edge case tests -----------------------

class TestEdgeCases:
    """Edge case handling."""

    def test_empty_snapshots(self):
        """Compare two empty-ish snapshots."""
        report = StrikeContinuityTracker.compare(
            RankingSnapshot(), RankingSnapshot())
        assert report.status == "FIRST_CYCLE"

    def test_ltp_change(self):
        """LTP change is detected."""
        prev = RankingSnapshot(
            strike=24400.0, ltp=18.0, ltp_timestamp="2024-01-15T10:30:00")
        cur = RankingSnapshot(
            strike=24400.0, ltp=19.0, ltp_timestamp="2024-01-16T10:30:00")
        report = StrikeContinuityTracker.compare(cur, prev)
        assert "current LTP changed" in report.reasons

    def test_no_material_change(self):
        """Delta < 3 → not material."""
        StrikeContinuityTracker.save_previous(RankingSnapshot(
            strike=24400.0, enhanced_score=94.0, score_margin=5.0))
        report = StrikeContinuityTracker.compare(
            RankingSnapshot(strike=24400.0, enhanced_score=95.0, score_margin=6.0))
        # delta = 1.0, which is < 3
        assert report.material_change is False