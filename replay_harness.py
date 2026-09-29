"""Historical Replay Verification Harness (restored).

Loads recorded shadow-mode entries and outcomes from shadow_data/*.jsonl
and provides deterministic, contract-identity-safe evaluation helpers.

Design rules (kept from the original harness):
- Chronological ordering of entries.
- Outcome lookup strictly by contract identity (underlying, expiry, strike,
  option_type). Never a different contract's outcome.
- Missing data -> OUTCOME_UNAVAILABLE. No fabricated values.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
ENTRIES_PATH = ROOT / "shadow_data" / "entries.jsonl"
OUTCOMES_PATH = ROOT / "shadow_data" / "outcomes.jsonl"

STATUS_AVAILABLE = "AVAILABLE"
STATUS_UNAVAILABLE = "OUTCOME_UNAVAILABLE"


def load_entries(path: Path | str | None = None) -> list[dict[str, Any]]:
    p = Path(path) if path else ENTRIES_PATH
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    out.sort(key=lambda e: str(e.get("timestamp", "")))
    return out


def load_outcomes(path: Path | str | None = None) -> list[dict[str, Any]]:
    p = Path(path) if path else OUTCOMES_PATH
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    out.sort(key=lambda o: str(o.get("timestamp", "")))
    return out


def make_contract_id(underlying: str, expiry: str, strike: float, option_type: str) -> tuple:
    return (str(underlying), str(expiry), float(strike), str(option_type))


def same_contract(a: tuple, b: tuple) -> bool:
    return a == b


def evaluate_outcome_checkpoints(
    ltp: float | None, outcome_record: dict[str, Any] | None
) -> dict[str, Any]:
    """Evaluate a live LTP against a recorded outcome's checkpoints.

    Missing record or missing LTP -> OUTCOME_UNAVAILABLE (never guessed).
    """
    if not outcome_record or ltp is None:
        return {"status": STATUS_UNAVAILABLE, "hit": None}
    t1 = outcome_record.get("t1")
    sl = outcome_record.get("stop_loss") or outcome_record.get("sl")
    if t1 is None or sl is None:
        return {"status": STATUS_UNAVAILABLE, "hit": None}
    hit = "T1" if ltp >= t1 else ("SL" if ltp <= sl else None)
    return {"status": STATUS_AVAILABLE, "hit": hit}


def find_outcome_for_outcome_id(
    contract_id: tuple, outcomes: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the outcome record for exactly this contract, else None."""
    for o in outcomes:
        oid = make_contract_id(
            o.get("underlying", "NIFTY"),
            o.get("expiry", ""),
            o.get("strike", 0.0),
            o.get("option_type", ""),
        )
        if same_contract(oid, contract_id):
            return o
    return None


class ReplayHarness:
    """Convenience wrapper: loads shadow entries/outcomes once."""

    def __init__(self, entries_path: Path | str | None = None,
                 outcomes_path: Path | str | None = None) -> None:
        self.entries = load_entries(entries_path)
        self.outcomes = load_outcomes(outcomes_path)
