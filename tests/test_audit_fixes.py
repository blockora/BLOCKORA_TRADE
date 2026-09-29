"""Regression tests for production audit fixes.

Each test pins one audit fix so it cannot silently regress:
  1. jugaad fallback chain must never mark failed fetches as fresh (P0-3
     policy: a failed fetch is the opposite of fresh) and must never raise
     NameError from out-of-scope variables.
  2. store_decision failures must be logged, never silently swallowed —
     ai_decisions is the audit trail.
  3. v3 expiry policy comes from settings.market.expiry_policy (no hardcode).
  4. legacy config honours the documented DATABASE_PATH env override.
"""
import os
import sys
from datetime import timedelta
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.session import now_ist
from pipeline.data_sources import SyntheticSource


@pytest.fixture(scope="module")
def cfg():
    from core.config import Config
    return Config.load()


# --------------------------------------------------------------------------
# 1. jugaad fallback chain: failed fetch fails cleanly, never marks fresh
# --------------------------------------------------------------------------
def test_jugaad_fallback_failure_does_not_mark_fresh():
    """Broken pre-fix behavior: on failure it called freshness_guard.mark_fetch()
    (fabricating freshness) and raised NameError on out-of-scope market_data."""
    main = pytest.importorskip("main")  # needs requests etc.; skip if heavy deps absent
    bot = main.BlockoraTrade()

    class _Logger:
        def error(self, *a, **k):
            pass

        def warning(self, *a, **k):
            pass

    bot.logger = _Logger()

    class _Guard:
        def __init__(self):
            self.marked = 0

        def mark_fetch(self):
            self.marked += 1

    guard = _Guard()
    bot.freshness_guard = guard

    # Force the import inside _jugaad_fallback_chain to fail -> failure path.
    with mock.patch.dict(sys.modules, {"jugaad_data": None, "jugaad_data.nse": None}):
        # Old code raised NameError (market_data/strikes out of scope) before
        # even reaching the logger; the fix returns None cleanly instead.
        result = bot._jugaad_fallback_chain(24500.0, [24450, 24500, 24550])
    assert result is None
    assert guard.marked == 0, "a failed fetch must NEVER be marked as fresh (P0-3)"


# --------------------------------------------------------------------------
# 2. store_decision: failures are logged, not swallowed
# --------------------------------------------------------------------------
def test_store_decision_failure_is_logged_not_silent():
    dbm = pytest.importorskip("database.db_manager").DatabaseManager
    from core.config_manager import ConfigManager

    cfg = ConfigManager()

    class _Logger:
        def __init__(self):
            self.errors = []

        def error(self, msg, *a, **k):
            self.errors.append(str(msg))

        def info(self, *a, **k):
            pass

    log = _Logger()
    db = dbm(cfg, log)
    db.db_path = ":memory:"
    db.initialize()
    try:
        # Simulate a write failure by corrupting the connection cursor target:
        # drop the table out from under store_decision.
        db.connection.execute("DROP TABLE ai_decisions")
        db.connection.commit()
        db.store_decision({
            "date": "2026-09-29", "time": "10:00", "action": "NO_TRADE",
            "strike": 0, "option_type": "", "confidence": 0, "grade": "",
            "entry": 0, "stop_loss": 0, "target_1": 0, "target_2": 0,
            "target_3": 0, "risk": "", "holding_time": "",
            "reasons": [], "bias": "", "ai_score": 0,
        })
        assert log.errors, "store_decision failure must be logged, never silent"
        assert "store_decision" in log.errors[-1]
    finally:
        db.close()


# --------------------------------------------------------------------------
# 3. v3 expiry policy is configuration, not a hardcoded literal
# --------------------------------------------------------------------------
def test_expiry_policy_comes_from_settings_yaml():
    cfg = pytest.importorskip("core.config").Config.load()
    policy = cfg.get("settings.market.expiry_policy")
    assert policy, "settings.market.expiry_policy must be defined in settings.yaml"
    engine_src = (Path(__file__).resolve().parent.parent / "pipeline" / "engine.py").read_text()
    assert 'expiry = "NEXT_WEEKLY"' not in engine_src, \
        "engine must not hardcode the expiry literal"


# --------------------------------------------------------------------------
# 4. legacy ConfigManager honours the documented DATABASE_PATH env var
# --------------------------------------------------------------------------
def test_database_path_env_override():
    cm = pytest.importorskip("core.config_manager").ConfigManager
    cfg = cm()
    with mock.patch.dict(os.environ, {"DATABASE_PATH": "/tmp/audit_test_blockora.db"}):
        assert cfg.get("database.path") == "/tmp/audit_test_blockora.db"
    assert cfg.get("database.path") != "/tmp/audit_test_blockora.db"


# --------------------------------------------------------------------------
# 6. no look-ahead: candle series never contains bars after the decision
# --------------------------------------------------------------------------
def test_synthetic_source_has_no_future_bars():
    """Bars must be session-anchored BACKWARD from the decision snapshot.
    (Pre-fix: bars started at today 09:15 and ran ~10h into the future.)"""
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo
    from pipeline.data_sources import SyntheticSource

    ist = ZoneInfo("Asia/Kolkata")
    dec = dt(2026, 9, 29, 10, 15, tzinfo=ist)          # Tuesday 10:15 IST
    src = SyntheticSource(seed=7, regime="bull", as_of=dec)
    bars = src.get_candles("NIFTY", "5m", 220)
    assert bars, "expected a candle series"
    future = [b for b in bars if dt.fromisoformat(b.bar_ts) > dec]
    assert not future, f"future bars leaked into the series: {future[:2]}"
    # bars must stay inside market sessions (Mon-Fri 09:15..15:30)
    for b in bars:
        t = dt.fromisoformat(b.bar_ts)
        assert t.weekday() < 5 and (9, 15) <= (t.hour, t.minute) < (15, 30), \
            f"bar outside market session: {b.bar_ts}"


def test_engine_drops_unclosed_bars_from_any_adapter(cfg):
    """Defense-in-depth: even an adapter returning an OPEN/future bar must
    not influence the decision (engine drops it structurally)."""
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo
    from pipeline import engine as engine_mod

    ist = ZoneInfo("Asia/Kolkata")
    dec = dt(2026, 9, 29, 10, 15, tzinfo=ist)
    src = SyntheticSource(seed=7, regime="bull", as_of=dec)
    # adversarial adapter: inject a bar stamped AFTER the decision
    orig = src.get_candles

    def poisoned(symbol, timeframe, count):
        bars = orig(symbol, timeframe, count)
        last = bars[-1]
        from core.models import Candle
        future_bar = Candle(symbol=last.symbol, timeframe=last.timeframe,
                            bar_ts="2026-09-29T10:20:00+05:30",
                            open=99999.0, high=99999.0, low=99999.0,
                            close=99999.0, volume=1, quality=last.quality)
        return bars + [future_bar]

    src.get_candles = poisoned
    kept = engine_mod._closed_bars_only(
        poisoned("NIFTY", "5m", 10), dec)
    assert all(dt.fromisoformat(b.bar_ts) <= dec for b in kept)
    assert not any(b.close == 99999.0 for b in kept), \
        "future bar with fabricated price must be dropped"


def test_relative_paths_anchor_to_project_root(tmp_path, monkeypatch):
    """Starting from a foreign CWD must never scatter the DB (pre-fix it did)."""
    monkeypatch.chdir(tmp_path)
    from core.config_manager import ConfigManager
    from database.db_manager import DatabaseManager

    cfg = ConfigManager()
    cfg.load()
    db = DatabaseManager(cfg, None)
    assert Path(db.db_path).is_absolute()
    assert Path(db.db_path).parent == Path(cfg.project_root) / "database"
    assert not (tmp_path / "database").exists(), \
        "no stray database may be created in the caller's CWD"


def test_run_cycle_cli_from_foreign_cwd(tmp_path, monkeypatch):
    """The documented entrypoint must work from any directory and write to
    the project database, not the CWD."""
    import subprocess
    monkeypatch.chdir(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "run_cycle.py"),
         "--seed", "2", "--regime", "bull", "--at", "10:45", "--json"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert '"decision"' in proc.stdout
    assert not (tmp_path / "database").exists(), \
        "stray DB in foreign CWD — path anchoring regression"


# --------------------------------------------------------------------------
# 7. circuit breakers + dedup window are LIVE, not hardcoded zeros
# --------------------------------------------------------------------------
def _mk_engine(stats=None):
    from core.config import Config
    from pipeline.engine import DecisionEngine, MarketDataSource
    cfg = Config.load()
    # deterministic in-session decision time (weekday 10:30 IST) so F1 never
    # preempts the circuit-breaker assertions below
    base = now_ist()
    day = base
    while day.weekday() >= 5:
        day += timedelta(days=1)
    dec = day.replace(hour=10, minute=30, second=0, microsecond=0)
    src = SyntheticSource(seed=42, regime="bull", as_of=dec)
    eng = DecisionEngine(cfg, MarketDataSource(src, src), stats_provider=stats)
    return eng, dec


def test_circuit_breaker_trades_per_day_fires():
    eng, dec = _mk_engine(lambda: {"trades_today": 2, "consecutive_losses": 0,
                                   "daily_loss_pct": 0.0})
    rec = eng.run_cycle(now=dec)
    assert rec.decision.value == "NO_TRADE"
    assert "CB_trades" in rec.no_trade_reason or "F14_daily_cap" in rec.no_trade_reason


def test_circuit_breaker_consecutive_losses_fires():
    eng, dec = _mk_engine(lambda: {"trades_today": 0, "consecutive_losses": 2,
                                   "daily_loss_pct": 0.0})
    rec = eng.run_cycle(now=dec)
    assert rec.decision.value == "NO_TRADE"
    assert "CB_losses" in rec.no_trade_reason


def test_stats_provider_failure_fails_closed():
    """A broken stats source must NOT silently PASS the trades/day cap."""
    def boom():
        raise RuntimeError("db unavailable")
    eng, dec = _mk_engine(boom)
    rec = eng.run_cycle(now=dec)
    assert rec.decision.value == "NO_TRADE"
    assert "CB_trades" in rec.no_trade_reason or "F14_daily_cap" in rec.no_trade_reason


def test_dedup_window_expires_old_keys():
    """filters.yaml dedup.window_min was dead config before the fix — keys
    lived forever. They must expire after the configured window."""
    from datetime import timedelta
    from core.session import now_ist
    eng, _ = _mk_engine()
    window_min = float(eng.cfg.get("filters.dedup.window_min", 30))
    eng._recent_keys["OLD"] = now_ist() - timedelta(minutes=window_min + 1)
    eng._recent_keys["NEW"] = now_ist() - timedelta(minutes=1)
    eng._prune_dedup_keys(now_ist())
    assert "OLD" not in eng._recent_keys
    assert "NEW" in eng._recent_keys


def test_daily_loss_pct_is_never_fabricated():
    """daily_loss_pct must stay 0.0 (honest unknown) until Phase 7 records
    exit prices — a fabricated PnL number would corrupt the breaker."""
    import inspect
    from run_cycle import _circuit_stats
    src = inspect.getsource(_circuit_stats)
    assert 'daily_loss_pct": 0.0' in src


# --------------------------------------------------------------------------
# 8. documented freshness overrides are actually honored
# --------------------------------------------------------------------------
def test_freshness_guard_reads_config_overrides():
    """settings.json freshness.spot/chain_max_age_seconds were documented
    but never read (constructor ignored config). Now they apply; invalid
    values fall back to the safe 60s defaults."""
    from data.data_freshness_guard import DataFreshnessGuard

    class Cfg:
        def get(self, key, default=None):
            return {"freshness.spot_max_age_seconds": 15,
                    "freshness.chain_max_age_seconds": 20}.get(key, default)

    g = DataFreshnessGuard(config=Cfg())
    assert g.SPOT_MAX_SEC == 15 and g.CHAIN_MAX_SEC == 20

    class BadCfg:
        def get(self, key, default=None):
            return "not-a-number"

    g2 = DataFreshnessGuard(config=BadCfg())
    assert g2.SPOT_MAX_SEC == 60 and g2.CHAIN_MAX_SEC == 60, \
        "invalid config must fall back to safe defaults, not disable the guard"


def test_freshness_guard_fails_closed_on_stale_and_missing():
    """Phase 5 forced-failure battery: no failed fetch may become fresh."""
    import time as _time
    import datetime as _dt
    from data.data_freshness_guard import DataFreshnessGuard

    g = DataFreshnessGuard()
    now_iso = _dt.datetime.now().isoformat()
    healthy = {"ltp": 24500,
               "candles": [[now_iso, 24500, 24510, 24490, 24500, 100]]}
    chain = {"timestamp": now_iso}
    g._fetch_time = _time.time()
    ok, _ = g.check(healthy, chain, force_market=True)
    assert ok, "healthy data must pass"

    cases = [
        ({}, {}, "timeout/empty"),
        ({**healthy, "ltp": 0}, chain, "missing price"),
        ({**healthy, "ltp": 99999}, chain, "implausible price"),
        (healthy, {"timestamp": ""}, "missing ts"),
        (healthy, {"timestamp": "garbage"}, "invalid ts"),
        (healthy, {"timestamp": "2026-09-28T10:00:00"}, "stale ts"),
        ({**healthy, "candles": []}, chain, "no candles"),
    ]
    for md, oc, label in cases:
        fresh, reasons = g.check(md, oc, force_market=True)
        assert not fresh, f"{label} must fail closed (got fresh=True)"
        assert reasons, f"{label} must explain why"


# --------------------------------------------------------------------------
# 10. main.py is_market_open must honor documented market_hours config
# --------------------------------------------------------------------------
def test_market_hours_read_from_config():
    """settings.json market_hours.open/close were documented but main.py
    hardcoded the session window. The method must read config (with a safe
    fallback if the value is malformed)."""
    src = (Path(__file__).resolve().parent.parent / "main.py").read_text()
    method = src.split("def is_market_open", 1)[1].split("\n    def ", 1)[0]
    assert 'config.get("market_hours.open"' in method
    assert 'config.get("market_hours.close"' in method
    assert "except (TypeError, ValueError)" in method, \
        "malformed market_hours must fall back to the safe default session"


# --------------------------------------------------------------------------
# 9. clean-install dependency completeness (smartapi's undeclared logzero)
# --------------------------------------------------------------------------
def test_requirements_declare_smartapi_transitive_imports():
    """smartapi-python 1.5.5 imports logzero at module level but does NOT
    declare it in its package metadata — pip check passes while the broker
    import crashes. requirements.txt must declare it explicitly (found via
    clean-venv production-entrypoint test)."""
    req = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text()
    declared = {line.split("#")[0].strip().split("==")[0].lower()
                for line in req.splitlines() if line.strip() and not line.startswith("#")}
    for needed in ("logzero", "pytest", "smartapi-python"):
        assert needed in declared, f"{needed} missing from requirements.txt"
    # psutil is deliberately NOT required. Upstream psutil refuses to install
    # on Android ("platform android is not supported"), so a mandatory psutil
    # broke `pip install -r requirements.txt` on Termux. system_health now
    # reads /proc and os.* instead and treats psutil as a desktop-only extra.
    assert "psutil" not in declared, (
        "psutil must stay out of requirements.txt or Android installs fail")


# --------------------------------------------------------------------------
# 5. repo hygiene: runtime dirs are ignored
# --------------------------------------------------------------------------
def test_gitignore_covers_runtime_dirs():
    gi = (Path(__file__).resolve().parent.parent / ".gitignore").read_text()
    for entry in ("logs/", "backup/", "cache/", "shadow_data/", ".pytest_cache/"):
        assert entry in gi, f".gitignore must exclude {entry}"
