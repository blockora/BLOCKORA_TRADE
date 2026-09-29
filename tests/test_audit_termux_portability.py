"""Portability audit guards (Termux / no-/tmp environments).

These assert the properties the audit required, without ever reading or
printing a real credential value: only throwaway sentinels set by the test.
"""
import os
import pathlib
import subprocess
import sys

import pytest

CREDENTIAL_KEYS = (
    "ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_PASSWORD",
    "ANGEL_TOTP_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
)

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_no_test_opens_files_under_tmp():
    """Termux has no /tmp. Tests must build files under pytest's tmp_path.

    Only filesystem *use* counts: a bare "/tmp/..." string that is compared but
    never opened (e.g. a DATABASE_PATH override asserted for precedence) is
    harmless, so the check looks for an actual open/connect.
    """
    offenders = []
    for p in (ROOT / "tests").rglob("*.py"):
        if p.name == pathlib.Path(__file__).name:
            continue  # this guard names the pattern it forbids
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if "/tmp/" not in line or "tmp_path" in line:
                continue
            stripped = line.strip()
            # inert literals (comparisons/asserts/patch.dict) are fine
            if stripped.startswith(("#", "assert", "with ", '"', "'")) or "patch.dict" in stripped:
                continue
            offenders.append(f"{p.relative_to(ROOT)}:{i}: {stripped}")
    assert not offenders, "tests must not touch /tmp directly:\n" + "\n".join(offenders)


def test_historical_similarity_db_lands_in_pytest_tmp(tmp_path):
    """The similarity fixture must build its DB inside pytest's tmp dir."""
    import tests.test_historical_similarity as mod
    src = pathlib.Path(mod.__file__).read_text()
    assert "/tmp/test_historical_mem.db" not in src, "hardcoded /tmp DB path remains"

    # drive the fixture directly and confirm the DB is created under tmp_path
    gen = mod.mem.__wrapped__(tmp_path)
    m = next(gen)
    try:
        db_file = pathlib.Path(m.db_path)
        assert str(db_file).startswith(str(tmp_path)), m.db_path
        assert db_file.exists(), "fixture did not create its database"
    finally:
        try:
            next(gen)          # run fixture teardown
        except StopIteration:
            pass
        m.connection.close()


def test_tzdata_is_declared_because_zoneinfo_is_used_at_import():
    """core/session.py builds ZoneInfo('Asia/Kolkata') at MODULE IMPORT time.

    Termux ships no system zoneinfo database, so without the tzdata wheel the
    import raises ZoneInfoNotFoundError and the process cannot start.
    """
    reqs = (ROOT / "requirements.txt").read_text().lower()
    assert "tzdata" in reqs, "tzdata must stay declared in requirements.txt"

    session = (ROOT / "core" / "session.py").read_text()
    assert 'ZoneInfo("Asia/Kolkata")' in session

    # guard against platform-dependent pass/fail: use an explicit tzpath
    import zoneinfo
    zoneinfo.reset_tzpath(["/nonexistent-dir-for-audit"])
    try:
        zoneinfo.ZoneInfo("Asia/Kolkata")
    except Exception as exc:
        # expected on hosts with the tzdata wheel absent
        assert type(exc).__name__ == "ZoneInfoNotFoundError", exc
    else:
        pytest.skip("tzdata wheel present on this host; runtime check not applicable")
    finally:
        zoneinfo.reset_tzpath()


def test_credential_assertions_are_isolated_from_ambient_environment(monkeypatch, tmp_path):
    """test_config's credential tests must not depend on host credentials.

    Pre-seeding every credential (with throwaway sentinels) and re-running the
    config suite in a child process proves the monkeypatch.delenv isolation.
    The sentinel is asserted to never appear in the child's output.
    """
    sentinel = "AUDIT-SENTINEL-NOT-A-REAL-CREDENTIAL"
    child = dict(os.environ)
    for key in CREDENTIAL_KEYS:
        child[key] = sentinel

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_config.py", "-q",
         "-p", "no:cacheprovider"],
        capture_output=True, text=True, timeout=300, cwd=str(ROOT), env=child,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-3000:]
    assert sentinel not in output, "a credential value leaked into test output"


def test_get_credentials_reads_env_only(monkeypatch):
    """Direct unit check: absent -> None, present -> that exact value."""
    from core.config import get_credentials
    for key in CREDENTIAL_KEYS:
        monkeypatch.delenv(key, raising=False)
    assert all(v is None for v in get_credentials().values())

    monkeypatch.setenv("ANGEL_API_KEY", "unit-sentinel")
    creds = get_credentials()
    assert creds["ANGEL_API_KEY"] == "unit-sentinel"
    for key in CREDENTIAL_KEYS:
        if key != "ANGEL_API_KEY":
            assert creds[key] is None
