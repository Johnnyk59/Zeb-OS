"""AutonomyScheduler — the always-on background runner for Zeb's bots.

A single daemon thread wakes on a short cadence and runs any bot that's
"due" per its schedule (interval-based, e.g. the 2h knowledge firehose and
12h self-improvement loop, or daily-hour, e.g. the nightly file organizer).
Last-run timestamps persist to ``<zeb_home>/autonomy/schedule_state.json``
so cadence survives gateway restarts — a 2-hour job doesn't re-fire just
because the process bounced.

Lifecycle mirrors ``gateway/memory_monitor.py`` / ``gateway/self_healing.py``
(daemon thread + stop event + idempotent start/stop), and it's started and
stopped from the same gateway hooks, so autonomy comes up with the gateway
and drains cleanly with it. Every bot run is fail-open: an exception is
caught, logged, recorded as a failed ``BotResult``, and the scheduler keeps
going — one misbehaving bot can never wedge the loop or the gateway.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from zeb_autonomy.base import Bot, BotContext, BotResult
from zeb_autonomy.notifier import Notifier, default_gateway_delivery_hook

logger = logging.getLogger(__name__)

_LOG_PREFIX = "[AUTONOMY]"


@dataclass
class Job:
    """A registered bot plus its schedule.

    Exactly one of ``interval_seconds`` (>0) or ``daily_hour`` (0-23) drives
    cadence. ``daily_hour`` gives "once per day, on/after that local hour"
    scheduling for the nightly organizer; interval drives the 2h/12h loops.
    """

    name: str
    bot: Bot
    interval_seconds: float = 0.0
    daily_hour: Optional[int] = None
    enabled: bool = True

    def is_due(self, last_run: float, now: float) -> bool:
        if not self.enabled:
            return False
        if self.daily_hour is not None:
            now_dt = datetime.fromtimestamp(now)
            if now_dt.hour < self.daily_hour:
                return False
            if last_run <= 0:
                return True
            last_dt = datetime.fromtimestamp(last_run)
            return last_dt.date() < now_dt.date()
        if self.interval_seconds <= 0:
            return False
        return (now - last_run) >= self.interval_seconds


class AutonomyScheduler:
    def __init__(
        self,
        *,
        zeb_home: Optional[Path] = None,
        config: Optional[dict[str, Any]] = None,
        notifier: Optional[Notifier] = None,
        check_interval_s: float = 60.0,
    ):
        if zeb_home is None:
            from zeb_constants import get_zeb_home

            zeb_home = get_zeb_home()
        self.zeb_home = zeb_home
        self._config = config
        self.check_interval_s = max(5.0, check_interval_s)
        self._jobs: dict[str, Job] = {}
        self._state_path = zeb_home / "autonomy" / "schedule_state.json"
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_run = self._load_state()
        self.notifier = notifier or Notifier(
            zeb_home, delivery_hook=default_gateway_delivery_hook()
        )
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ── registration ────────────────────────────────────────────────────
    def register(
        self,
        bot: Bot,
        *,
        interval_seconds: float = 0.0,
        daily_hour: Optional[int] = None,
        enabled: bool = True,
    ) -> None:
        self._jobs[bot.name] = Job(
            name=bot.name,
            bot=bot,
            interval_seconds=interval_seconds,
            daily_hour=daily_hour,
            enabled=enabled,
        )
        logger.info(
            "%s registered bot %r (interval=%ss daily_hour=%s enabled=%s)",
            _LOG_PREFIX, bot.name, interval_seconds or "-", daily_hour, enabled,
        )

    # ── state persistence ────────────────────────────────────────────────
    def _load_state(self) -> dict[str, float]:
        try:
            return {
                k: float(v)
                for k, v in json.loads(self._state_path.read_text("utf-8")).items()
            }
        except Exception:
            return {}

    def _save_state(self) -> None:
        try:
            tmp = self._state_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._last_run), encoding="utf-8")
            tmp.replace(self._state_path)
        except OSError as exc:
            logger.warning("%s failed to persist schedule state: %s", _LOG_PREFIX, exc)

    # ── context ──────────────────────────────────────────────────────────
    def _build_context(self) -> BotContext:
        from zeb_autonomy import local_llm

        cfg = self._config
        if cfg is None:
            try:
                from zeb_cli.config import load_config

                cfg = load_config()
            except Exception:
                cfg = {}

        def _complete(prompt: str, *, system: str = "", max_tokens: int = 512, **kw: Any):
            return local_llm.complete(
                prompt, system=system, max_tokens=max_tokens, config=cfg, **kw
            )

        def _notify(message: str, level: str = "info", **details: Any) -> None:
            self.notifier.notify(message, level, source="autonomy", **details)

        return BotContext(
            config=cfg, zeb_home=self.zeb_home, log=logger,
            complete=_complete, notify=_notify,
        )

    # ── running ──────────────────────────────────────────────────────────
    def run_due(self, *, force: Optional[str] = None) -> list[BotResult]:
        """Run every due bot once (or just ``force`` regardless of schedule).

        Returns the results. Used by the loop, and callable directly by the
        decision engine / CLI / tests for on-demand execution.
        """
        now = time.time()
        ctx = self._build_context()
        results: list[BotResult] = []
        for name, job in list(self._jobs.items()):
            if force is not None and name != force:
                continue
            if force is None and not job.is_due(self._last_run.get(name, 0.0), now):
                continue
            results.append(self._run_one(job, ctx))
            self._last_run[name] = time.time()
            self._save_state()
        return results

    def _run_one(self, job: Job, ctx: BotContext) -> BotResult:
        started = time.time()
        try:
            result = job.bot.run(ctx)
        except Exception as exc:
            logger.warning("%s bot %r raised: %s", _LOG_PREFIX, job.name, exc, exc_info=True)
            result = BotResult.failed(job.name, f"raised: {exc}")
        elapsed = time.time() - started
        level = "info" if result.ok else "warning"
        logger.log(
            logging.INFO if result.ok else logging.WARNING,
            "%s ran %r ok=%s in %.1fs: %s",
            _LOG_PREFIX, job.name, result.ok, elapsed, result.summary,
        )
        if result.notify:
            self.notifier.notify(
                result.notify_message or result.summary,
                result.notify_level,
                source=job.name,
            )
        return result

    def _loop(self) -> None:
        # Stagger the first tick so autonomy doesn't fight gateway startup.
        self._stop.wait(min(30.0, self.check_interval_s))
        while not self._stop.is_set():
            try:
                self.run_due()
            except Exception:
                logger.warning("%s scheduler tick failed", _LOG_PREFIX, exc_info=True)
            self._stop.wait(self.check_interval_s)

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, name="zeb-autonomy", daemon=True
            )
            self._thread.start()
            logger.info(
                "%s scheduler started (%d bots, check every %.0fs)",
                _LOG_PREFIX, len(self._jobs), self.check_interval_s,
            )
            return True

    def stop(self, timeout: float = 2.0) -> None:
        with self._lock:
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=timeout)
            self._thread = None
