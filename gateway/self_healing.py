"""Background self-diagnosis and auto-repair for the always-on gateway.

ZebOS is meant to run 24/7 with no one watching it. This module is the
periodic health checker that makes that survivable: it runs a small set of
cheap, independent checks on a timer and repairs what it safely can without
human intervention — unloading a wedged local model so it reloads clean,
flagging a malformed state.db for the repair path that already exists in
``zeb_state.py``, warning before disk exhaustion takes the process down.

Design mirrors ``gateway/memory_monitor.py`` on purpose (same reviewers,
same operational habits): a daemon thread, a stop event, a single
grep-friendly log prefix (``[SELF-HEAL]``) so `agent.log`/`gateway.log` can
be scanned for a time series, and every check fails OPEN — an exception
inside one check is caught and reported as its own "unknown" result rather
than ever taking down the monitor thread or the gateway itself. A checker
that can crash the process it's supposed to be protecting is worse than no
checker at all.

Each check is also exposed standalone (``run_health_checks``) so ``zeb
doctor`` can run the exact same checks on demand, not just on the
background timer — one implementation, two call sites.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_LOG_PREFIX = "[SELF-HEAL]"

_monitor_thread: Optional[threading.Thread] = None
_stop_event: Optional[threading.Event] = None
_lock = threading.Lock()

# Disk space thresholds for the zeb_home filesystem. Warn early enough that
# an operator (or a future auto-cleanup check) has time to react before the
# gateway can no longer write session state or logs at all.
_DISK_WARN_BYTES = 500 * 1024 * 1024   # 500MB
_DISK_CRITICAL_BYTES = 100 * 1024 * 1024  # 100MB


@dataclass
class HealthCheckResult:
    component: str
    status: str  # "ok" | "degraded" | "critical"
    message: str
    repaired: bool = False


def _safe_check(name: str, fn: Callable[[], HealthCheckResult]) -> HealthCheckResult:
    try:
        return fn()
    except Exception as exc:
        logger.warning("%s check %r raised: %s", _LOG_PREFIX, name, exc, exc_info=True)
        return HealthCheckResult(name, "degraded", f"check failed to run: {exc}")


def _check_local_model(config: dict[str, Any]) -> HealthCheckResult:
    """If the local backbone is loaded, confirm it still answers.

    A model that's loaded but wedged (GPU driver hiccup, corrupted KV
    cache after an OOM-adjacent state) is worse than one that's simply not
    loaded yet — every future request against it will hang or error. The
    repair is blunt but safe: unload it. The next request transparently
    reloads a fresh instance (agent/llama_cpp_adapter.py:_load_model).
    """
    from agent.llama_cpp_adapter import is_model_loaded, unload_model

    if not is_model_loaded():
        return HealthCheckResult("local_model", "ok", "not loaded (lazy — nothing to check)")

    # Run the ping on a worker thread with a hard timeout: a wedged
    # llama.cpp call blocks forever with no client-side way to cancel it,
    # so we can't just call .ping() inline and trust it to return.
    result: dict[str, Any] = {}

    def _do_ping():
        from agent.llama_cpp_adapter import _loaded_model_path
        from agent.llama_cpp_adapter import LlamaCppClient

        try:
            client = LlamaCppClient(model_path=_loaded_model_path)
            result["ok"] = client.ping()
        except Exception as exc:
            result["error"] = str(exc)

    t = threading.Thread(target=_do_ping, daemon=True)
    t.start()
    t.join(timeout=30.0)

    if t.is_alive():
        unload_model()
        return HealthCheckResult(
            "local_model", "critical",
            "ping timed out after 30s — model appears wedged; unloaded for reload",
            repaired=True,
        )
    if result.get("ok"):
        return HealthCheckResult("local_model", "ok", "loaded and responsive")

    unload_model()
    return HealthCheckResult(
        "local_model", "degraded",
        f"ping failed ({result.get('error', 'unknown error')}); unloaded for reload",
        repaired=True,
    )


def _check_disk_space(config: dict[str, Any]) -> HealthCheckResult:
    from zeb_constants import get_zeb_home

    home = get_zeb_home()
    home.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(home)
    if usage.free < _DISK_CRITICAL_BYTES:
        return HealthCheckResult(
            "disk_space", "critical",
            f"only {usage.free // (1024*1024)}MB free at {home} — "
            f"writes (sessions, logs, model cache) may start failing",
        )
    if usage.free < _DISK_WARN_BYTES:
        return HealthCheckResult(
            "disk_space", "degraded",
            f"{usage.free // (1024*1024)}MB free at {home} — getting low",
        )
    return HealthCheckResult("disk_space", "ok", f"{usage.free // (1024*1024)}MB free")


def _check_state_db(config: dict[str, Any]) -> HealthCheckResult:
    """Confirm state.db is openable; hand off to the existing repair path if not.

    ``zeb_state.py`` already auto-repairs malformed-schema errors the
    moment they're hit mid-session (``repair_state_db_schema`` +
    ``_claim_repair_attempt``). This check exists for the gap that leaves:
    a DB that's malformed but simply hasn't been touched by a live session
    yet (fresh boot, idle gateway) sits broken until something happens to
    open it. A cheap ``SELECT 1`` here catches that gap on the health
    timer instead of waiting for a user-facing failure.
    """
    import sqlite3

    from zeb_constants import get_zeb_home

    db_path = get_zeb_home() / "state.db"
    if not db_path.exists():
        return HealthCheckResult("state_db", "ok", "not created yet (fresh install)")

    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return HealthCheckResult("state_db", "ok", "readable")
    except Exception as exc:
        try:
            from zeb_state import is_malformed_db_error, repair_state_db_schema

            if is_malformed_db_error(exc):
                repair_result = repair_state_db_schema(db_path, backup=True)
                return HealthCheckResult(
                    "state_db", "critical",
                    f"malformed schema detected and repaired: {repair_result}",
                    repaired=True,
                )
        except Exception as repair_exc:
            return HealthCheckResult(
                "state_db", "critical",
                f"malformed and repair attempt failed: {repair_exc}",
            )
        return HealthCheckResult("state_db", "degraded", f"unexpected error: {exc}")


def _check_config_yaml(config: dict[str, Any]) -> HealthCheckResult:
    """Confirm config.yaml still parses as YAML.

    Doesn't attempt to auto-fix a corrupted config — silently rewriting a
    user's config risks losing settings they'd want back. It backs up the
    broken file (so the next `zeb setup` / manual edit has something to
    diff against) and reports it; the existing config-loading fallback
    (``zeb_cli/config.py``) already degrades to defaults at read time, so
    the process stays up either way.
    """
    import yaml

    from zeb_constants import get_zeb_home

    config_path = get_zeb_home() / "config.yaml"
    if not config_path.exists():
        return HealthCheckResult("config_yaml", "ok", "not created yet (using defaults)")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            yaml.safe_load(f)
        return HealthCheckResult("config_yaml", "ok", "parses cleanly")
    except yaml.YAMLError as exc:
        import time as _time

        backup_path = config_path.with_name(
            f"config.yaml.corrupt-backup-{int(_time.time())}"
        )
        try:
            shutil.copy2(config_path, backup_path)
            backed_up = f"; backed up to {backup_path.name}"
        except Exception:
            backed_up = " (backup failed)"
        return HealthCheckResult(
            "config_yaml", "critical",
            f"invalid YAML ({exc}){backed_up} — falling back to defaults until fixed",
        )


_CHECKS: tuple[tuple[str, Callable[[dict[str, Any]], HealthCheckResult]], ...] = (
    ("local_model", _check_local_model),
    ("disk_space", _check_disk_space),
    ("state_db", _check_state_db),
    ("config_yaml", _check_config_yaml),
)


def run_health_checks(config: Optional[dict[str, Any]] = None) -> list[HealthCheckResult]:
    """Run every registered check and return their results.

    Safe to call directly (no threading) — this is what both the
    background monitor loop and ``zeb doctor`` call.
    """
    if config is None:
        try:
            from zeb_cli.config import load_config

            config = load_config()
        except Exception:
            config = {}
    return [_safe_check(name, lambda fn=fn: fn(config)) for name, fn in _CHECKS]


def _log_results(results: list[HealthCheckResult]) -> None:
    for r in results:
        line = f"{_LOG_PREFIX} {r.component}={r.status}"
        if r.repaired:
            line += " REPAIRED"
        line += f": {r.message}"
        if r.status == "critical":
            logger.error(line)
        elif r.status == "degraded":
            logger.warning(line)
        else:
            logger.debug(line)


def _monitor_loop(stop_event: threading.Event, interval: float) -> None:
    # Stagger the first check slightly so it doesn't compete with the
    # gateway's own startup work for CPU/IO.
    stop_event.wait(min(30.0, interval))
    while not stop_event.is_set():
        try:
            _log_results(run_health_checks())
        except Exception:
            logger.warning("%s monitor tick failed", _LOG_PREFIX, exc_info=True)
        stop_event.wait(interval)


def start_self_healing_monitor(interval_seconds: float = 600.0) -> bool:
    """Start the background self-healing thread. Returns True if (now) running.

    Idempotent — calling this again while already running is a no-op that
    returns True, same contract as ``start_memory_monitoring``.
    """
    global _monitor_thread, _stop_event
    with _lock:
        if _monitor_thread is not None and _monitor_thread.is_alive():
            return True
        _stop_event = threading.Event()
        _monitor_thread = threading.Thread(
            target=_monitor_loop,
            args=(_stop_event, max(60.0, interval_seconds)),
            name="zeb-self-healing",
            daemon=True,
        )
        _monitor_thread.start()
        logger.info(
            "%s monitor started (interval=%.0fs)", _LOG_PREFIX, max(60.0, interval_seconds)
        )
        return True


def stop_self_healing_monitor(timeout: float = 2.0) -> None:
    global _monitor_thread, _stop_event
    with _lock:
        if _stop_event is not None:
            _stop_event.set()
        if _monitor_thread is not None:
            _monitor_thread.join(timeout=timeout)
        _monitor_thread = None
        _stop_event = None
