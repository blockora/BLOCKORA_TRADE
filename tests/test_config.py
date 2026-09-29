"""Tests: configuration loading, hashing, dot-key access."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import Config


@pytest.fixture(scope="module")
def cfg():
    return Config.load()


def test_config_loads_all_three_files(cfg):
    assert cfg.settings["application"]["name"] == "BLOCKORA_TRADE"
    assert cfg.weights["version"] == 1
    assert cfg.filters["version"] == 1


def test_dot_key_access(cfg):
    assert cfg.get("settings.market.symbol") == "NIFTY"
    assert cfg.get("side_gate.min_side_score", None) is None  # not a top-level file
    assert cfg.get("weights.side_gate.min_side_score") == 55.0
    assert cfg.get("filters.liquidity.max_spread_pct") == 3.0
    assert cfg.get("nonexistent.key.deep", "fallback") == "fallback"


def test_weights_sum_to_100(cfg):
    total = sum(f["weight"] for f in cfg.weights["families"].values())
    assert total == 100


def test_hashes_are_stable_and_different(cfg):
    assert len(cfg.weights_hash()) == 16
    assert cfg.weights_hash() != cfg.filters_hash()


def test_every_family_declares_group_and_components(cfg):
    for name, fam in cfg.weights["families"].items():
        assert fam["group"], f"family {name} missing group"
        assert fam["components"], f"family {name} missing components"


def test_groups_cover_all_families(cfg):
    groups = set(cfg.weights["groups"].keys())
    for fam in cfg.weights["families"].values():
        assert fam["group"] in groups


def test_filter_catalogue_matches_docs(cfg):
    f = cfg.filters
    assert f["session"]["market_open"] == "09:15"
    assert f["liquidity"]["max_spread_pct"] == 3.0
    assert f["risk"]["min_rr"] == 1.5
    assert f["calibration_gate"]["enabled"] is False  # dormant until Phase 8


def test_credentials_come_from_env_only(monkeypatch):
    from core.config import get_credentials
    monkeypatch.setenv("ANGEL_API_KEY", "test-key")
    creds = get_credentials()
    assert creds["ANGEL_API_KEY"] == "test-key"
    assert creds["TELEGRAM_BOT_TOKEN"] is None
    # credentials must never appear in the YAML configs
    import yaml
    for name in ("settings", "weights", "filters"):
        raw = (Path(__file__).resolve().parent.parent / "config" / f"{name}.yaml").read_text()
        assert "ANGEL_API_KEY" not in raw
