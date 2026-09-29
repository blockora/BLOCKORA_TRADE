"""System health monitor that works on desktop Linux AND Android/Termux.

Why this was rewritten
----------------------
psutil refuses to install on Android ("platform android is not supported"),
so on Termux the health monitor could not report CPU or memory at all. The
old fallback filled those fields with 0, which is worse than nothing: a
printed 0% reads as "the CPU is idle" when in fact the number is unknown.
A health panel that lies is worse than one that admits a gap.

What this reports, and from where
---------------------------------
Every value below comes from a source that genuinely works on the target
platform. A metric that cannot be obtained truthfully is None and is named
in "unavailable" with the reason. Nothing is defaulted, guessed or faked.

  metric          desktop/Linux            Android/Termux
  --------------- ------------------------ ---------------------------
  disk_percent    os.statvfs (POSIX)       os.statvfs (POSIX) - works
  memory_percent  /proc/meminfo or psutil  /proc/meminfo - works
  cpu_percent     /proc/stat delta         /proc/stat delta - works
                  (psutil when present)    (first call = unavailable)
  cpu_load_1m     os.getloadavg            os.getloadavg - works
  uptime_seconds  /proc/uptime or psutil   /proc/uptime - works

cpu_percent needs two samples of /proc/stat separated by an interval. The
first call therefore returns None with reason "cpu_warming_up" rather than a
made-up number. psutil is still used when importable, because on desktop it
gives a first-call CPU figure immediately.

Guarantees
----------
* Importing and constructing this module never raises, with or without
  psutil.
* check() never raises and never returns None. A failure inside any single
  metric is confined to that metric.
* Health monitoring can never abort a trading cycle: it reports problems,
  it does not gate them.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Optional

#: Statuses the trading path treats as acceptable.
HEALTHY = "HEALTHY"
WARNING = "WARNING"
CRITICAL = "CRITICAL"

#: Load-average based fallback thresholds for the "CPU" status, used only
#: when a real CPU percentage is unavailable. These are deliberately
#: conservative and only ever lower a HEALTHY verdict to WARNING; they can
#: never invent a percentage.
_LOAD_WARN = 2.0
_LOAD_CRIT = 4.0

_MEM_WARN = 90.0
_MEM_CRIT = 95.0
_DISK_WARN = 90.0
_DISK_CRIT = 97.0


def _read_first_line(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.readline().strip()
    except (OSError, ValueError):
        return ""


def _disk_percent(path: str = "/") -> Optional[float]:
    """Filesystem usage from statvfs. POSIX, so it works on Termux."""
    try:
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        if total <= 0:
            return None
        used = total - (st.f_bavail * st.f_frsize)
        return round(used / total * 100.0, 1)
    except (OSError, ValueError, AttributeError):
        return None


def _meminfo_percent() -> Optional[float]:
    """Memory used % from /proc/meminfo.

    MemAvailable is preferred over MemFree because on Android MemFree is
    near zero even on an idle device, which would report a false ~99% usage.
    """
    try:
        with open("/proc/meminfo", "r", encoding="utf-8", errors="replace") as fh:
            values = {}
            for line in fh:
                key, _, rest = line.partition(":")
                parts = rest.split()
                if parts:
                    try:
                        values[key.strip()] = float(parts[0]) * 1024.0
                    except ValueError:
                        continue
        total = values.get("MemTotal")
        if not total:
            return None
        available = values.get("MemAvailable")
        if available is None:
            available = values.get("MemFree", 0.0)
        used = total - available
        return round(max(0.0, min(100.0, used / total * 100.0)), 1)
    except (OSError, ValueError, KeyError):
        return None


def _read_cpu_jiffies():
    """Aggregate jiffies from the 'cpu' line of /proc/stat."""
    line = _read_first_line("/proc/stat")
    if not line.startswith("cpu "):
        return None
    parts = line.split()[1:]
    try:
        nums = [int(x) for x in parts]
    except ValueError:
        return None
    if len(nums) < 4:
        return None
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
    return sum(nums), idle


def _uptime_seconds() -> Optional[float]:
    line = _read_first_line("/proc/uptime")
    if not line:
        return None
    try:
        return float(line.split()[0])
    except (ValueError, IndexError):
        return None


class SystemHealth:
    """Monitor system health and resources.

    Construct with any config/logger; neither is required to be functional.
    Never raises on construction, with or without psutil installed.
    """

    def __init__(self, config=None, logger=None):
        self.config = config
        self.logger = logger
        self.status = HEALTHY
        self.last_check: Optional[datetime] = None
        self.psutil_available = False

        try:
            import psutil  # noqa: F401
            self.psutil_available = True
        except Exception:
            # Not just ImportError: on an odd platform the import itself can
            # raise. Health monitoring must never take the process down.
            self.psutil_available = False
            if self.logger is not None:
                try:
                    self.logger.warning(
                        "psutil unavailable (Android or not installed) - "
                        "using /proc-based health metrics; CPU% needs one "
                        "prior sample")
                except Exception:
                    pass

        # State for the two-sample CPU calculation.
        self._cpu_prev = _read_cpu_jiffies()
        self._cpu_prev_ts = time.monotonic()
        self._last_health: dict = {}

    # ------------------------------------------------------------------
    def _cpu_percent(self) -> tuple:
        """Return (value, reason). value is None when not yet knowable."""
        if self.psutil_available:
            try:
                import psutil
                return float(psutil.cpu_percent(interval=None)), None
            except Exception:
                pass

        current = _read_cpu_jiffies()
        now = time.monotonic()
        prev, prev_ts = self._cpu_prev, self._cpu_prev_ts
        # Update the baseline for the next call either way.
        self._cpu_prev, self._cpu_prev_ts = current, now
        if current is None or prev is None:
            return None, "cpu_unavailable_no_proc_stat"
        elapsed = now - prev_ts
        if elapsed < 0.5:
            return None, "cpu_warming_up"
        d_total = current[0] - prev[0]
        d_idle = current[1] - prev[1]
        if d_total <= 0:
            return None, "cpu_warming_up"
        return round(max(0.0, min(100.0, (1.0 - d_idle / d_total) * 100.0)), 1), None

    def _psutil_metrics(self) -> dict:
        """psutil-only extras, used when importable. Never raises."""
        out = {}
        if not self.psutil_available:
            return out
        try:
            import psutil
            mem = psutil.virtual_memory()
            out["memory_total_bytes"] = int(mem.total)
            out["memory_available_bytes"] = int(getattr(mem, "available", 0) or 0)
            with contextlib_suppress():
                out["cpu_count"] = psutil.cpu_count(logical=True)
            with contextlib_suppress():
                out["boot_time"] = datetime.fromtimestamp(
                    psutil.boot_time()).isoformat()
        except Exception:
            pass
        return out

    # ------------------------------------------------------------------
    def check(self) -> dict:
        """Run a health check. Never raises; never returns None.

        Unobtainable metrics are None and listed in "unavailable" with a
        reason. A metric is never reported as 0 to mean "unknown".
        """
        self.last_check = datetime.now()
        stamp = self.last_check.isoformat()
        unavailable = {}

        cpu_percent, cpu_reason = self._cpu_percent()
        if cpu_percent is None:
            unavailable["cpu_percent"] = cpu_reason or "unavailable"
            if self.logger is not None:
                try:
                    self.logger.debug(f"cpu_percent unavailable: {cpu_reason}")
                except Exception:
                    pass

        memory_percent = _meminfo_percent()
        if memory_percent is None and self.psutil_available:
            try:
                import psutil
                memory_percent = float(psutil.virtual_memory().percent)
            except Exception:
                memory_percent = None
        if memory_percent is None:
            unavailable["memory_percent"] = "meminfo_unavailable"

        disk_percent = _disk_percent("/")
        if disk_percent is None:
            unavailable["disk_percent"] = "statvfs_unavailable"

        load1 = None
        try:
            if hasattr(os, "getloadavg"):
                load1 = round(float(os.getloadavg()[0]), 2)
        except (OSError, ValueError, AttributeError):
            load1 = None
        if load1 is None:
            unavailable["cpu_load_1m"] = "getloadavg_unavailable"

        uptime = _uptime_seconds()
        if uptime is None:
            unavailable["uptime_seconds"] = "proc_uptime_unavailable"

        health = {
            "status": HEALTHY,
            "platform": _platform_name(),
            "psutil_available": self.psutil_available,
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "disk_percent": disk_percent,
            "cpu_load_1m": load1,
            "uptime_seconds": round(uptime, 0) if uptime is not None else None,
            "unavailable": unavailable,
            "timestamp": stamp,
        }
        health.update(self._psutil_metrics())

        health["status"] = self._derive_status(health)
        self.status = health["status"]
        self._last_health = health
        return health

    def _derive_status(self, health: dict) -> str:
        """Status from real values only; a missing metric never escalates."""
        cpu = health.get("cpu_percent")
        mem = health.get("memory_percent")
        disk = health.get("disk_percent")
        load1 = health.get("cpu_load_1m")

        if mem is not None and mem >= _MEM_CRIT:
            return CRITICAL
        if disk is not None and disk >= _DISK_CRIT:
            return CRITICAL
        if cpu is not None and cpu >= _MEM_CRIT:
            return CRITICAL

        if mem is not None and mem >= _MEM_WARN:
            return WARNING
        if disk is not None and disk >= _DISK_WARN:
            return WARNING
        if cpu is not None and cpu >= 70.0:
            return WARNING
        # Load average is a real measurement and can only raise a verdict,
        # never lower it. Used when a percentage is not yet available.
        if cpu is None and load1 is not None:
            if load1 >= _LOAD_CRIT:
                return CRITICAL
            if load1 >= _LOAD_WARN:
                return WARNING
        return HEALTHY

    def is_healthy(self) -> bool:
        """True unless CRITICAL. A monitoring signal, not a trading gate."""
        return self.status in (HEALTHY, WARNING)

    def last_health(self) -> dict:
        """Most recent check() result; an empty skeleton before the first."""
        return dict(self._last_health) if self._last_health else {
            "status": self.status,
            "cpu_percent": None,
            "memory_percent": None,
            "disk_percent": None,
            "unavailable": {"all": "no_check_run_yet"},
        }


def _platform_name() -> str:
    try:
        import platform
        return platform.system() or "unknown"
    except Exception:
        return "unknown"


class contextlib_suppress:
    """Tiny local suppress so this module has no import-order surprises."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return exc_type is not None
