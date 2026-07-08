"""Notification bot (feature 10) — how Zeb reaches Johnny on its own.

Any autonomy component can call :meth:`Notifier.notify` when it decides
something warrants Johnny's attention. Every notification is:

1. **Persisted** to ``<zeb_home>/autonomy/notifications.jsonl`` (durable,
   survives restarts, readable by ``zeb`` / the dashboard / state sync).
2. **Rate-limited + deduped** so a chatty bot can't spam — the same
   message within the dedupe window is collapsed.
3. **Delivered best-effort** to whatever outbound channel exists in this
   process (the gateway's home-channel delivery, or the send-message
   tool). Delivery failure never loses the notification — it's already
   persisted, and the CLI/dashboard surface the backlog.

No external dependency: with no gateway and no channel configured, notify
still records durably to disk, which is the source of truth.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_LEVELS = ("info", "warning", "critical")


@dataclass
class Notification:
    message: str
    level: str = "info"
    source: str = "zeb"
    ts: float = field(default_factory=time.time)
    details: dict[str, Any] = field(default_factory=dict)


class Notifier:
    """Durable, deduped, best-effort notification sink."""

    def __init__(
        self,
        zeb_home: Path,
        *,
        dedupe_window_s: float = 3600.0,
        delivery_hook: Optional[Callable[[Notification], None]] = None,
    ):
        self._store = zeb_home / "autonomy" / "notifications.jsonl"
        self._store.parent.mkdir(parents=True, exist_ok=True)
        self._dedupe_window_s = dedupe_window_s
        self._delivery_hook = delivery_hook
        self._recent: dict[str, float] = {}
        self._lock = threading.Lock()

    def notify(
        self,
        message: str,
        level: str = "info",
        *,
        source: str = "zeb",
        **details: Any,
    ) -> bool:
        """Record + deliver a notification. Returns False if deduped/suppressed."""
        message = (message or "").strip()
        if not message:
            return False
        if level not in _LEVELS:
            level = "info"

        now = time.time()
        with self._lock:
            key = f"{source}:{level}:{message}"
            last = self._recent.get(key)
            if last is not None and (now - last) < self._dedupe_window_s:
                logger.debug("Notifier: deduped %r", message)
                return False
            self._recent[key] = now
            # Bound the dedupe map so it can't grow unbounded over a long run.
            if len(self._recent) > 512:
                cutoff = now - self._dedupe_window_s
                self._recent = {k: t for k, t in self._recent.items() if t >= cutoff}

            note = Notification(message=message, level=level, source=source, details=details)
            self._persist(note)

        # Deliver outside the lock — delivery can be slow/blocking.
        self._deliver(note)
        return True

    def _persist(self, note: Notification) -> None:
        try:
            with self._store.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(note), ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("Notifier: failed to persist notification: %s", exc)

    def _deliver(self, note: Notification) -> None:
        if self._delivery_hook is None:
            logger.info("[NOTIFY:%s] %s", note.level, note.message)
            return
        try:
            self._delivery_hook(note)
        except Exception as exc:
            # Already persisted — delivery is best-effort. Surface as a log.
            logger.warning(
                "Notifier: delivery failed (%s); notification persisted to %s",
                exc,
                self._store,
            )

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent persisted notifications (newest last)."""
        if not self._store.exists():
            return []
        try:
            lines = self._store.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


def default_gateway_delivery_hook() -> Optional[Callable[[Notification], None]]:
    """Build a delivery hook that pushes to the gateway home channel if one exists.

    Best-effort and import-guarded: returns None when no gateway delivery
    path is importable (e.g. pure-CLI context), in which case the Notifier
    falls back to durable-log-only. Never raises at build time.
    """
    try:
        from gateway.delivery import deliver_home_channel_message  # type: ignore
    except Exception:
        return None

    def _hook(note: Notification) -> None:
        prefix = {"info": "🤖", "warning": "⚠️", "critical": "🚨"}.get(note.level, "🤖")
        deliver_home_channel_message(f"{prefix} {note.message}")

    return _hook
