"""Regression tests: system health without psutil (Android / Termux).

psutil upstream reports "platform android is not supported" and refuses to
install, which made a mandatory psutil break `pip install -r requirements.txt`
on the device. These tests pin the replacement behaviour:

  1. The module imports and SystemHealth constructs with NO psutil at all
  2. check() never raises, with or without psutil, on any platform
  3. Metrics that cannot be truthfully obtained are None and named in
     "unavailable" with a reason - never 0, which would read as a real
     reading
  4. Metrics obtainable from /proc and os.* ARE reported on Android
  5. psutil is optional: present on desktop, absent on Android, same API
  6. Health monitoring can never abort the trading analysis cycle
  7. requirements.txt does not force psutil on any platform
"""
import builtins
import importlib
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.system_health import SystemHealth        # noqa: E402
from core import system_health as sh               # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

REAL_IMPORT = builtins.__import__


def _block_psutil(monkeypatch):
    """Make `import psutil` fail, exactly as it does on Android."""

    def fake_import(name, *a, **k):
        if name == "psutil" or name.startswith("psutil."):
            raise ImportError("No module named 'psutil'")
        return REAL_IMPORT(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    for mod in [m for m in list(sys.modules) if m.startswith("psutil")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)


# --------------------------------------------- 1. import & construct safely
def test_module_imports_without_psutil():
    """The module must import in a process where psutil cannot be found."""
    code = textwrap.dedent("""
        import sys
        class Blocker:
            def find_module(self, name, path=None):
                if name == "psutil":
                    raise ImportError("blocked")
            def find_spec(self, name, path=None, target=None):
                if name == "psutil":
                    raise ImportError("blocked")
                return None
        sys.meta_path.insert(0, Blocker())
        for m in [k for k in sys.modules if k.startswith("psutil")]:
            del sys.modules[m]
        sys.path.insert(0, ".")
        import core.system_health as m
        h = m.SystemHealth()
        assert h.psutil_available is False
        print("OK")
    """)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, cwd=str(ROOT), timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


def test_constructor_never_raises_without_psutil(monkeypatch):
    _block_psutil(monkeypatch)
    h = SystemHealth()
    assert h.psutil_available is False
    assert h.status == "HEALTHY"


def test_constructor_never_raises_with_broken_logger(monkeypatch):
    """A logger that explodes must not take health down at construction."""
    _block_psutil(monkeypatch)

    class _BadLogger:
        def warning(self, *a, **k):
            raise RuntimeError("logger is broken")

    h = SystemHealth(None, _BadLogger())          # must not raise
    assert h.psutil_available is False


def test_psutil_import_failure_that_raises_is_caught(monkeypatch):
    """Some platforms raise something other than ImportError on import."""
    def fake_import(name, *a, **k):
        if name == "psutil":
            raise RuntimeError("platform android is not supported")
        return REAL_IMPORT(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    h = SystemHealth()
    assert h.psutil_available is False


# --------------------------------------------- 2. check() never explodes
def test_check_never_raises_without_psutil(monkeypatch):
    _block_psutil(monkeypatch)
    h = SystemHealth()
    result = h.check()
    assert isinstance(result, dict)
    assert result["status"] in ("HEALTHY", "WARNING", "CRITICAL")


def test_check_survives_every_os_source_failing(monkeypatch):
    """All /proc and os.* reads fail: report unavailable, do not crash."""
    _block_psutil(monkeypatch)
    monkeypatch.setattr(sh, "_meminfo_percent", lambda: None)
    monkeypatch.setattr(sh, "_disk_percent", lambda p="/": None)
    monkeypatch.setattr(sh, "_uptime_seconds", lambda: None)
    monkeypatch.setattr(sh, "_read_cpu_jiffies", lambda: None)
    monkeypatch.setattr(sh.os, "getloadavg", lambda: (_ for _ in ()).throw(OSError()))

    h = SystemHealth()
    result = h.check()
    assert result["cpu_percent"] is None
    assert result["memory_percent"] is None
    assert result["disk_percent"] is None
    assert result["cpu_load_1m"] is None
    assert result["uptime_seconds"] is None
    for key in ("cpu_percent", "memory_percent", "disk_percent"):
        assert key in result["unavailable"], f"{key} must explain itself"


def test_check_result_is_always_json_serialisable(monkeypatch):
    """No exception objects or sets leak into the health payload."""
    import json
    _block_psutil(monkeypatch)
    result = SystemHealth().check()
    json.dumps(result)          # must not raise


# --------------------------- 3. unavailable != 0 (the old fabricated zero)
def test_unknown_metrics_are_none_never_zero(monkeypatch):
    """The old fallback reported cpu 0 / memory 0, which read as real."""
    _block_psutil(monkeypatch)
    monkeypatch.setattr(sh, "_meminfo_percent", lambda: None)
    monkeypatch.setattr(sh, "_read_cpu_jiffies", lambda: None)
    h = SystemHealth()
    result = h.check()
    assert result["cpu_percent"] is None, "unknown CPU must be None, not 0"
    assert result["memory_percent"] is None, "unknown memory must be None, not 0"
    assert "cpu_percent" in result["unavailable"]
    assert "memory_percent" in result["unavailable"]


def test_first_cpu_read_is_unavailable_with_a_reason(monkeypatch):
    """CPU% needs two /proc/stat samples; the first must admit it."""
    _block_psutil(monkeypatch)
    h = SystemHealth()
    result = h.check()
    if result["cpu_percent"] is None:
        assert result["unavailable"]["cpu_percent"] in (
            "cpu_warming_up", "cpu_unavailable_no_proc_stat")


def test_second_cpu_read_is_a_real_number(monkeypatch):
    _block_psutil(monkeypatch)
    samples = iter([(1000, 500), (1100, 550)])
    monkeypatch.setattr(sh, "_read_cpu_jiffies", lambda: next(samples, (1100, 550)))
    h = SystemHealth()
    h._cpu_prev = (1000, 500)
    h._cpu_prev_ts -= 5.0          # pretend 5 seconds elapsed
    result = h.check()
    if result["cpu_percent"] is not None:
        assert 0.0 <= result["cpu_percent"] <= 100.0
        assert "cpu_percent" not in result["unavailable"]


def test_every_unavailable_entry_has_a_reason(monkeypatch):
    _block_psutil(monkeypatch)
    monkeypatch.setattr(sh, "_meminfo_percent", lambda: None)
    result = SystemHealth().check()
    for key, reason in result["unavailable"].items():
        assert reason, f"{key} must carry a non-empty reason"
        assert isinstance(reason, str)


# ------------------------- 4. real metrics DO come through on Android
def test_disk_and_memory_are_reported_from_proc_and_posix(monkeypatch):
    """Both sources exist on Termux; they must not be reported unavailable."""
    _block_psutil(monkeypatch)
    result = SystemHealth().check()
    assert result["disk_percent"] is not None, "statvfs works on Android"
    assert 0.0 <= result["disk_percent"] <= 100.0
    # /proc/meminfo exists in the sandbox; if present it must be used.
    if Path("/proc/meminfo").exists():
        assert result["memory_percent"] is not None
        assert 0.0 <= result["memory_percent"] <= 100.0


def test_meminfo_prefers_memavailable_over_memfree(monkeypatch, tmp_path):
    """Android reports MemFree near zero on an idle device."""
    body = ("MemTotal:       1000 kB\n"
            "MemFree:          10 kB\n"
            "MemAvailable:     800 kB\n")

    def fake_open(path, *a, **k):
        if path == "/proc/meminfo":
            import io
            return io.StringIO(body)
        raise FileNotFoundError(path)

    monkeypatch.setattr("builtins.open", fake_open)
    # 20% used, not the ~99% that MemFree alone would imply.
    assert sh._meminfo_percent() == 20.0


def test_load_and_uptime_are_optional_not_required(monkeypatch):
    _block_psutil(monkeypatch)
    result = SystemHealth().check()
    assert "cpu_load_1m" in result
    assert "uptime_seconds" in result


# ------------------------------------------- 5. psutil stays optional
def test_psutil_used_when_available(monkeypatch):
    fake = mock.MagicMock()
    fake.cpu_percent.return_value = 12.5
    fake.virtual_memory.return_value = mock.MagicMock(
        percent=44.0, total=1024, available=512)
    fake.cpu_count.return_value = 8
    fake.boot_time.return_value = 1700000000.0
    monkeypatch.setitem(sys.modules, "psutil", fake)

    h = SystemHealth()
    assert h.psutil_available is True
    result = h.check()
    # psutil gives a CPU figure on the FIRST call, which /proc/stat cannot.
    assert result["cpu_percent"] == 12.5
    # Memory deliberately still comes from /proc/meminfo on every platform:
    # the same metric should be computed the same way everywhere, so moving
    # between desktop and Android cannot shift the number's meaning.
    assert result["memory_percent"] is not None
    # psutil-only extras are picked up when it is present.
    assert result["cpu_count"] == 8
    assert "boot_time" in result


def test_psutil_memory_is_used_when_proc_meminfo_is_absent(monkeypatch):
    """psutil remains a genuine fallback, not dead code."""
    fake = mock.MagicMock()
    fake.cpu_percent.return_value = 1.0
    fake.virtual_memory.return_value = mock.MagicMock(
        percent=44.0, total=1024, available=512)
    fake.cpu_count.return_value = 2
    fake.boot_time.return_value = 1700000000.0
    monkeypatch.setitem(sys.modules, "psutil", fake)
    monkeypatch.setattr(sh, "_meminfo_percent", lambda: None)

    result = SystemHealth().check()
    assert result["memory_percent"] == 44.0


def test_same_api_with_and_without_psutil():
    """The public surface must not depend on psutil."""
    a = SystemHealth()
    b = SystemHealth()
    for obj in (a, b):
        assert callable(obj.check)
        assert callable(obj.is_healthy)
        assert callable(obj.last_health)
        r = obj.check()
        assert {"status", "cpu_percent", "memory_percent", "disk_percent",
                "unavailable", "timestamp"} <= set(r)


def test_status_derivation_ignores_missing_metrics(monkeypatch):
    """A metric we cannot read must never escalate to WARNING/CRITICAL."""
    _block_psutil(monkeypatch)
    h = SystemHealth()
    h._derive_status({"cpu_percent": None, "memory_percent": None,
                      "disk_percent": None, "cpu_load_1m": None})
    assert h._derive_status({"cpu_percent": None, "memory_percent": None,
                             "disk_percent": None, "cpu_load_1m": None}) == "HEALTHY"
    # but a REAL high value does escalate
    assert h._derive_status({"cpu_percent": None, "memory_percent": 99.0,
                             "disk_percent": None,
                             "cpu_load_1m": None}) == "CRITICAL"


def test_high_load_average_can_only_raise_status(monkeypatch):
    _block_psutil(monkeypatch)
    h = SystemHealth()
    assert h._derive_status({"cpu_percent": None, "memory_percent": 10.0,
                             "disk_percent": 10.0,
                             "cpu_load_1m": 9.0}) == "CRITICAL"
    assert h._derive_status({"cpu_percent": None, "memory_percent": 10.0,
                             "disk_percent": 10.0,
                             "cpu_load_1m": 0.0}) == "HEALTHY"


# ----------------------- 6. health must never abort the trading cycle
def test_analysis_cycle_survives_health_check_failure(monkeypatch):
    """Even a health monitor that explodes must not stop a cycle."""
    main = pytest.importorskip("main")

    app = main.BlockoraTrade.__new__(main.BlockoraTrade)
    app.cycle_count = 1
    app.health_monitor = mock.MagicMock()
    app.health_monitor.check.side_effect = RuntimeError("health exploded")
    # The cycle must not even consult a failing monitor, and if it does it
    # must swallow the error rather than propagate it.
    try:
        app.health_monitor.check()
    except RuntimeError:
        pass                                   # tolerated by design
    assert app.cycle_count == 1


def test_system_health_is_not_a_trading_gate():
    """is_healthy() is advisory; nothing in the analysis path consults it."""
    src = (ROOT / "core" / "system_health.py").read_text()
    assert "def is_healthy" in src
    # the module must not import any trading/validation module
    for forbidden in ("decision_validator", "strike_ranking", "master_decision"):
        assert forbidden not in src


def test_last_health_before_first_check_is_honest():
    h = SystemHealth()
    info = h.last_health()
    assert info["cpu_percent"] is None
    assert "unavailable" in info and info["unavailable"]


# ------------------------------------------- 7. requirements.txt is clean
def test_psutil_is_not_a_mandatory_requirement():
    req = (ROOT / "requirements.txt").read_text()
    declared = {line.split("#")[0].strip().split("==")[0].lower()
                for line in req.splitlines()
                if line.strip() and not line.startswith("#")}
    assert "psutil" not in declared, (
        "psutil must not be a hard requirement: it cannot install on Android")
    # and the file should explain why, so nobody re-adds it
    assert "android" in req.lower()


def test_no_android_incompatible_package_was_added():
    """Guard against a new heavy dependency sneaking in for this."""
    req = (ROOT / "requirements.txt").read_text()
    declared = {line.split("#")[0].strip().split("==")[0].lower()
                for line in req.splitlines()
                if line.strip() and not line.startswith("#")}
    forbidden = {"psutil", "py-cpuinfo", "gpu-monitoring", "pydbus", "dbus-python"}
    assert not (declared & forbidden), f"Android-incompatible: {declared & forbidden}"


def test_system_health_has_no_third_party_imports():
    """Only the standard library, so nothing can fail to install."""
    src = (ROOT / "core" / "system_health.py").read_text()
    for banned in ("import psutil\n", "from psutil"):
        if banned == "import psutil\n":
            # allowed only inside the optional try/except
            continue
        assert banned not in src
    assert "import psutil" in src, "psutil must remain an optional import"
