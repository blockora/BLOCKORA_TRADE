"""BLOCKORA_TRADE v3 — data source protocols.

Live adapters (Angel One in Phase 2) implement these; tests use deterministic
fakes. Adapters must never fabricate values: missing fields stay None.
"""
from __future__ import annotations

from typing import Protocol

from core.models import Candle, OptionQuote, UnderlyingTick


class BrokerSource(Protocol):
    """Underlying index/futures quotes and historical candles."""

    def get_underlying_tick(self, symbol: str) -> UnderlyingTick: ...

    def get_candles(self, symbol: str, timeframe: str, count: int) -> list[Candle]: ...

    def is_healthy(self) -> bool: ...


class ChainSource(Protocol):
    """Option chain quotes for the tradable expiry."""

    def get_chain(self, expiry: str, strikes: list[float]) -> list[OptionQuote]: ...

    def is_healthy(self) -> bool: ...
