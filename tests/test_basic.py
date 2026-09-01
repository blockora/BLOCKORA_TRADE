"""Basic Tests for BLOCKORA_TRADE"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_config_manager():
    """Test configuration loading"""
    from core.config_manager import ConfigManager
    config = ConfigManager()
    assert config.get("application.name", "BLOCKORA_TRADE") == "BLOCKORA_TRADE"
    print("  \u2713 Config Manager test passed")


def test_confidence_engine():
    """Test confidence calculation"""
    from core.config_manager import ConfigManager
    from engines.confidence.confidence_engine import ConfidenceEngine

    config = ConfigManager()

    class MockLogger:
        def info(self, msg): pass
        def error(self, msg): pass
        def warning(self, msg): pass

    engine = ConfidenceEngine(config, MockLogger())
    results = {
        "market_structure": {"score": 85},
        "indicators": {"score": 80},
        "volume": {"score": 75},
        "oi_analysis": {"score": 70},
        "candlestick": {"score": 60},
        "smc": {"score": 50},
        "ict": {"score": 50},
        "wyckoff": {"score": 50},
    }
    confidence = engine.calculate(results)
    assert 0 <= confidence["score"] <= 100
    assert confidence["grade"] in ["REJECT", "WEAK", "GOOD", "EXCELLENT", "INSTITUTIONAL"]
    print(f"  \u2713 Confidence Engine test passed (Score: {confidence['score']}%, Grade: {confidence['grade']})")


def test_risk_engine():
    """Test risk evaluation"""
    from core.config_manager import ConfigManager
    from engines.risk.risk_engine import RiskEngine

    config = ConfigManager()

    class MockLogger:
        def info(self, msg): pass
        def error(self, msg): pass
        def warning(self, msg): pass

    engine = RiskEngine(config, MockLogger())
    results = {"volume": {"score": 80}, "trend": {"score": 75}}
    confidence = {"score": 85}
    risk = engine.evaluate(results, confidence)
    assert risk["level"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    print(f"  \u2713 Risk Engine test passed (Level: {risk['level']})")


if __name__ == "__main__":
    print("Running BLOCKORA_TRADE Tests...\n")
    test_config_manager()
    test_confidence_engine()
    test_risk_engine()
    print("\n  \u2713 All tests passed!")
