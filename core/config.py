"""BLOCKORA_TRADE v3 — configuration loading.

Loads YAML configs from config/ and exposes dot-key access. Credentials are
never stored in YAML; they are read from environment variables only.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


class Config:
    """Holds settings, weights and filters; provides dot-key access and hashing."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self.hashes: dict[str, str] = {}

    @classmethod
    def load(cls, config_dir: Path | str | None = None) -> "Config":
        cfg = cls()
        base = Path(config_dir) if config_dir else CONFIG_DIR
        for name in ("settings", "weights", "filters"):
            path = base / f"{name}.yaml"
            with open(path, "r", encoding="utf-8") as fh:
                cfg._data[name] = yaml.safe_load(fh) or {}
            cfg.hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        return cfg

    # -- access -------------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        parts = dotted.split(".")
        node: Any = self._data
        for p in parts:
            if not isinstance(node, dict) or p not in node:
                return default
            node = node[p]
        return node

    @property
    def settings(self) -> dict[str, Any]:
        return self._data["settings"]

    @property
    def weights(self) -> dict[str, Any]:
        return self._data["weights"]

    @property
    def filters(self) -> dict[str, Any]:
        return self._data["filters"]

    def weights_hash(self) -> str:
        return self.hashes["weights"]

    def filters_hash(self) -> str:
        return self.hashes["filters"]


def get_credentials() -> dict[str, str | None]:
    """Broker/Telegram credentials come from env only (never hardcoded, never YAML)."""
    keys = (
        "ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_PASSWORD", "ANGEL_TOTP_SECRET",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    )
    return {k: os.environ.get(k) for k in keys}
