#!/usr/bin/env python3
"""BLOCKORA_TRADE v3 — run one decision cycle and print the recommendation.

Offline-first: uses the deterministic synthetic source (or --source csv later).
Live broker wiring is Phase 10; the pipeline logic is identical either way.

Usage:
    python3 run_cycle.py [--seed 42] [--regime bull|bear|range] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import Config
from core.models import Decision
from database.db import Database
from pipeline.data_sources import SyntheticSource
from pipeline.engine import DecisionEngine, MarketDataSource


def _circuit_stats(db: Database) -> dict:
    """Live circuit-breaker inputs for the engine, read from recorded history.

    trades_today        = RECOMMENDATION rows dated today (IST)
    consecutive_losses  = trailing LOSS outcomes (newest first)
    daily_loss_pct      = 0.0 — not computable until Phase 7 records exit
                          prices/capital; documented in docs/ROADMAP.md.
                          We never fabricate a PnL number here.
    """
    from core.session import now_ist
    today = now_ist().date().isoformat()
    rows = db.conn.execute(
        "SELECT COUNT(*) AS c FROM recommendations "
        "WHERE decision='RECOMMENDATION' AND decision_ts LIKE ?",
        (f"{today}%",)).fetchone()
    trades_today = int(rows["c"]) if rows else 0

    consec = 0
    out_rows = db.conn.execute(
        "SELECT o.outcome FROM outcomes o "
        "JOIN recommendations r ON r.id = o.recommendation_id "
        "ORDER BY o.id DESC LIMIT 20").fetchall()
    for row in out_rows:
        if row["outcome"] == "LOSS":
            consec += 1
        else:
            break
    return {"trades_today": trades_today,
            "consecutive_losses": consec,
            "daily_loss_pct": 0.0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--regime", choices=["bull", "bear", "range"], default="range")
    ap.add_argument("--at", type=str, default=None,
                    help="simulate IST time HH:MM (default: now)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = Config.load()

    now = None
    if args.at:
        from core.session import now_ist
        hh, mm = map(int, args.at.split(":"))
        base = now_ist()
        now = base.replace(hour=hh, minute=mm, second=0, microsecond=0)

    # Candle series must end at the decision snapshot (no future bars):
    # pass the simulated instant into the source so indicators only see
    # bars closed at or before the decision.
    src = SyntheticSource(seed=args.seed, regime=args.regime, as_of=now)

    # Open the append-only store FIRST so circuit breakers (2 trades/day,
    # 2 consecutive losses, 5% daily loss) read REAL recorded state instead
    # of hardcoded zeros.
    db_path = Path(cfg.get("settings.database.path", "database/blockora.db"))
    if not db_path.is_absolute():
        db_path = Path(__file__).resolve().parent / db_path
    db = Database(db_path)
    db.initialize()

    engine = DecisionEngine(cfg, MarketDataSource(src, src),
                            stats_provider=lambda: _circuit_stats(db))
    rec = engine.run_cycle(now=now)

    row = {
        "decision_ts": rec.decision_ts, "decision": rec.decision.value,
        "market_bias": rec.market_bias.value if rec.market_bias else None,
        "side": rec.side, "strike": rec.strike, "expiry": rec.expiry,
        "entry": rec.plan.entry if rec.plan else None,
        "stop_loss": rec.plan.stop_loss if rec.plan else None,
        "t1": rec.plan.t1 if rec.plan else None,
        "t2": rec.plan.t2 if rec.plan else None,
        "t3": rec.plan.t3 if rec.plan else None,
        "expected_hold_min": rec.plan.expected_hold_min if rec.plan else None,
        "model_score": rec.model_score,
        "calibrated_confidence": rec.calibrated_confidence,
        "calibrated_state": rec.calibrated_state,
        "trade_grade": rec.trade_grade,
        "key_reasons": rec.key_reasons,
        "rejected_alternatives": rec.rejected_alternatives,
        "no_trade_reason": rec.no_trade_reason,
        "diagnostics": rec.diagnostics,
        "pipeline_version": cfg.get("settings.application.pipeline_version", "3.0.0-phase1"),
        "weights_hash": cfg.weights_hash(),
        "created_ts": rec.decision_ts,
    }
    rec_id = db.insert_recommendation(row)
    db.close()

    if args.json:
        print(json.dumps({
            "id": rec_id, "decision": rec.decision.value,
            "side": rec.side, "strike": rec.strike,
            "model_score": rec.model_score,
            "calibrated_state": rec.calibrated_state,
            "no_trade_reason": rec.no_trade_reason,
        }, indent=2))
        return 0

    print("=" * 64)
    print(f"  BLOCKORA_TRADE v3 — cycle @ {rec.decision_ts}")
    print("=" * 64)
    if rec.decision == Decision.NO_TRADE:
        print(f"  DECISION: NO_TRADE")
        print(f"  reason:   {rec.no_trade_reason}")
        if rec.diagnostics.get("side_scores"):
            for side, info in rec.diagnostics["side_scores"].items():
                print(f"  {side}: score={info['score']} "
                      f"(top {info['top']}, {info['candidates']} candidates)")
    else:
        p = rec.plan
        print(f"  DECISION: RECOMMENDATION  [{rec.trade_grade}]")
        print(f"  {rec.side}  {int(rec.strike)} {rec.expiry}   bias={rec.market_bias.value}")
        print(f"  entry={p.entry}  SL={p.stop_loss}")
        print(f"  T1={p.t1}  T2={p.t2}  T3={p.t3}")
        print(f"  R:R={p.reward_risk}  hold<={p.expected_hold_min}min")
        print(f"  model_score={rec.model_score}  confidence={rec.calibrated_state}"
              + (f" ({rec.calibrated_confidence})" if rec.calibrated_confidence is not None else ""))
        print(f"  reasons: {'; '.join(rec.key_reasons)}")
        if rec.rejected_alternatives:
            print(f"  rejected: {'; '.join(rec.rejected_alternatives[:3])}")
    print("=" * 64)
    print(f"  stored: recommendations.id={rec_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
