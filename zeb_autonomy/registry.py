"""Central wiring: build the AutonomyScheduler with every bot registered.

This is the one place that knows the full roster of autonomy bots and the
cadence each runs at (read from the ``autonomy`` config block). The gateway
calls :func:`start_autonomy` on boot and :func:`stop_autonomy` on shutdown —
the same lifecycle hooks the self-healing monitor uses.

Every bot is registered under its own guarded try/except: if one bot's
module fails to import (a partial checkout, a broken optional dependency),
the others still register and run. A missing bot degrades the subsystem, it
never prevents the scheduler from starting.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from zeb_autonomy.scheduler import AutonomyScheduler

logger = logging.getLogger(__name__)

_LOG = "[AUTONOMY]"


def _cfg(config: Any, *path: str, default: Any = None) -> Any:
    cur: Any = config or {}
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def build_scheduler(
    config: Optional[dict[str, Any]] = None,
    zeb_home: Optional[Path] = None,
) -> Optional[AutonomyScheduler]:
    """Construct a scheduler with all bots registered, or None if disabled."""
    if config is None:
        try:
            from zeb_cli.config import load_config

            config = load_config()
        except Exception:
            config = {}

    auto = _cfg(config, "autonomy", default={}) or {}
    if not auto.get("enabled", True):
        logger.info("%s disabled via config; scheduler not built", _LOG)
        return None

    sched = AutonomyScheduler(
        zeb_home=zeb_home,
        config=config,
        check_interval_s=float(auto.get("check_interval_seconds", 60) or 60),
    )

    def _try(register_fn, label: str) -> None:
        try:
            register_fn()
        except Exception as exc:
            logger.warning("%s failed to register %s: %s", _LOG, label, exc)

    # Feature 1 — autonomous decision engine (frequent).
    def _decision() -> None:
        from zeb_autonomy.decision import DecisionEngine

        mins = float(_cfg(config, "autonomy", "decision", "interval_minutes", default=15) or 15)
        sched.register(DecisionEngine(), interval_seconds=mins * 60)

    # Feature 3 — memory learning distillation.
    def _memory() -> None:
        from zeb_autonomy.memory_store import MemoryLearningBot

        hrs = float(_cfg(config, "autonomy", "memory_learning", "interval_hours", default=6) or 6)
        sched.register(MemoryLearningBot(), interval_seconds=hrs * 3600)

    # Feature 5 — state sync across instances.
    def _sync() -> None:
        from zeb_autonomy.state_sync import StateSyncBot

        mins = float(_cfg(config, "autonomy", "state_sync", "interval_minutes", default=30) or 30)
        sched.register(StateSyncBot(), interval_seconds=mins * 60)

    # Feature 6 — knowledge firehose (every 2h by default).
    def _knowledge() -> None:
        from zeb_autonomy.bots.knowledge_firehose import KnowledgeFirehoseBot

        hrs = float(_cfg(config, "autonomy", "knowledge", "interval_hours", default=2) or 2)
        sched.register(KnowledgeFirehoseBot(), interval_seconds=hrs * 3600)

    # Feature 7 — self-improvement loop (every 12h by default).
    def _improve() -> None:
        from zeb_autonomy.bots.self_improvement import SelfImprovementBot

        hrs = float(_cfg(config, "autonomy", "self_improvement", "interval_hours", default=12) or 12)
        sched.register(SelfImprovementBot(), interval_seconds=hrs * 3600)

    # Feature 9 — nightly file organizer (daily, at configured hour).
    def _organizer() -> None:
        from zeb_autonomy.bots.file_organizer import FileOrganizerBot

        hour = int(_cfg(config, "autonomy", "file_organizer", "daily_hour", default=3) or 3)
        sched.register(FileOrganizerBot(), daily_hour=max(0, min(23, hour)))

    # Self-evolution engine — the 24/7 custom-model development loop (data
    # harvest, response-cache speed-up, latency measurement, fine-tune
    # generations). Runs frequently so the model keeps improving.
    def _evolution() -> None:
        from zeb_autonomy.self_evolution import SelfEvolutionBot

        if not _cfg(config, "autonomy", "self_evolution", "enabled", default=True):
            return
        mins = float(
            _cfg(config, "autonomy", "self_evolution", "interval_minutes", default=30) or 30
        )
        sched.register(SelfEvolutionBot(), interval_seconds=mins * 60)

    # Always-on — hardwired keep-warm for the local model (never let it go cold)
    # plus idle self-tasking when the user is away. On by default; runs often.
    def _always_on() -> None:
        from zeb_autonomy.bots.always_on import AlwaysOnBot

        if not _cfg(config, "autonomy", "always_on", "enabled", default=True):
            return
        mins = float(
            _cfg(config, "autonomy", "always_on", "interval_minutes", default=5) or 5
        )
        idle = float(
            _cfg(config, "autonomy", "always_on", "idle_minutes", default=20) or 20
        )
        sched.register(AlwaysOnBot(idle_minutes=idle), interval_seconds=mins * 60)

    # Self-review engine — keeps the 6h/12h/24h reviews current.
    def _review() -> None:
        from zeb_autonomy.self_review import ReviewBot

        if not _cfg(config, "autonomy", "self_review", "enabled", default=True):
            return
        hrs = float(
            _cfg(config, "autonomy", "self_review", "interval_hours", default=2) or 2
        )
        sched.register(ReviewBot(), interval_seconds=hrs * 3600)

    # Gwen — private, restart-safe local reflection with an hourly
    # credential-aware mentor attempt. The bot's SQLite store owns the real
    # due times; this short scheduler tick only gives it a chance to claim work.
    def _gwen() -> None:
        from zeb_autonomy.bots.gwen import GwenBot

        if not _cfg(config, "autonomy", "gwen", "enabled", default=True):
            return
        mins = float(
            _cfg(config, "autonomy", "gwen", "scheduler_interval_minutes", default=5)
            or 5
        )
        sched.register(GwenBot(), interval_seconds=max(1.0, mins) * 60)

    _try(_decision, "decision_engine")
    _try(_memory, "memory_learning")
    _try(_sync, "state_sync")
    _try(_knowledge, "knowledge_firehose")
    _try(_improve, "self_improvement")
    _try(_organizer, "file_organizer")
    _try(_evolution, "self_evolution")
    _try(_always_on, "always_on")
    _try(_review, "self_review")
    _try(_gwen, "gwen")

    return sched


_scheduler: Optional[AutonomyScheduler] = None


def start_autonomy(
    config: Optional[dict[str, Any]] = None,
    zeb_home: Optional[Path] = None,
) -> Optional[AutonomyScheduler]:
    """Build (once) and start the autonomy scheduler. Idempotent."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    sched = build_scheduler(config, zeb_home)
    if sched is None:
        return None
    sched.start()
    _scheduler = sched
    return sched


def stop_autonomy(timeout: float = 2.0) -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.stop(timeout=timeout)
        _scheduler = None


def get_scheduler() -> Optional[AutonomyScheduler]:
    return _scheduler
