import json
import os
import sys
import tempfile

import pytest

from engines.learning.market_memory import MarketMemory


class TestMarketMemory:
    "Tests for the MarketMemory class."

    def setup_method(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.memory = MarketMemory(db_path=self.db_path)

    def teardown_method(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_store_and_retrieve_observation(self):
        observation = {
            "timestamp": "2024-01-15T10:30:00",
            "symbol": "NIFTY",
            "spot": 24250,
            "market_regime": "BEARISH",
            "direction": "BEARISH",
            "adx": 15,
            "rsi": 65,
            "macd": 2.5,
            "atr": 100,
            "vwap_relationship": "BELOW",
            "mtf_state": "BEARISH_ALIGNED",
            "expected_move": 30,
            "oi_context": "Strong",
            "volume_context": "High",
            "candidate_strikes": [24250, 24200, 24300],
            "option_type": "PE",
            "expiry": "20241226",
            "strike": 24250,
            "baseline_score": 85,
            "enhanced_score": 90,
            "score_margin": 5,
            "stability": "STABLE",
            "for_reasons": ["Near ATM", "Bearish structure"],
            "against_reasons": ["Premium high"],
            "ltp": 20,
            "ltp_timestamp": "2024-01-15T10:30:00",
            "data_quality": "DERIVED",
        }

        self.memory.store_observation(observation)
        results = self.memory.get_recent(limit=1)
        assert len(results) == 1

        result = results[0]
        assert result["symbol"] == "NIFTY"
        assert result["spot"] == 24250
        assert result["market_regime"] == "BEARISH"
        assert result["direction"] == "BEARISH"
        assert result["adx"] == 15
        assert result["rsi"] == 65
        assert result["macd"] == 2.5
        assert result["atr"] == 100
        assert result["vwap_relationship"] == "BELOW"
        assert result["mtf_state"] == "BEARISH_ALIGNED"
        assert result["expected_move"] == 30
        assert result["oi_context"] == "Strong"
        assert result["volume_context"] == "High"
        assert result["candidate_strikes"] == [24250, 24200, 24300]
        assert result["option_type"] == "PE"
        assert result["expiry"] == "20241226"
        assert result["strike"] == 24250
        assert result["baseline_score"] == 85
        assert result["enhanced_score"] == 90
        assert result["score_margin"] == 5
        assert result["stability"] == "STABLE"
        assert result["for_reasons"] == ["Near ATM", "Bearish structure"]
        assert result["against_reasons"] == ["Premium high"]
        assert result["ltp"] == 20
        assert result["data_quality"] == "DERIVED"

    def test_missing_fields_no_fake_values(self):
        observation = {"symbol": "NIFTY", "spot": 24250, "timestamp": "2024-01-15T10:30:00"}
        self.memory.store_observation(observation)
        results = self.memory.get_recent(limit=1)
        assert len(results) == 1
        result = results[0]
        assert result["symbol"] == "NIFTY"
        assert result["spot"] == 24250
        assert result["market_regime"] is None
        assert result["direction"] is None
        assert result["adx"] is None

    def test_store_multiple_observations(self):
        for i in range(5):
            observation = {"symbol": "NIFTY", "spot": 24250 + i * 10, "market_regime": "BEARISH", "direction": "BEARISH", "timestamp": "2024-01-15T10:30:00"}
            self.memory.store_observation(observation)

        count = self.memory.count()
        assert count == 5

    def test_get_recent(self):
        for i in range(3):
            observation = {"symbol": "NIFTY", "spot": 24250 + i * 10, "market_regime": "BEARISH", "direction": "BEARISH", "timestamp": "2024-01-15T10:30:00"}
            self.memory.store_observation(observation)

        recent = self.memory.get_recent(limit=2)
        assert len(recent) == 2
        assert recent[0]["spot"] == 24250
        assert recent[1]["spot"] == 24260

    def test_persistence_across_reopening(self):
        observation = {"symbol": "NIFTY", "spot": 24250, "market_regime": "BEARISH", "direction": "BEARISH", "timestamp": "2024-01-15T10:30:00"}
        self.memory.store_observation(observation)
        initial_count = self.memory.count()
        new_memory = MarketMemory(db_path=self.db_path)
        new_count = new_memory.count()
        assert initial_count == new_count

    def test_clear_for_test(self):
        observation = {"symbol": "NIFTY", "spot": 24250, "timestamp": "2024-01-15T10:30:00"}
        self.memory.store_observation(observation)
        assert self.memory.count() == 1
        self.memory.clear_for_test()
        assert self.memory.count() == 0

    def test_empty_store(self):
        results = self.memory.get_recent(limit=5)
        assert len(results) == 0
        assert self.memory.count() == 0
