"""Shared contract for autonomy bots.

Every bot implements the :class:`Bot` protocol — a ``name`` and a
``run(ctx) -> BotResult``. The scheduler builds one :class:`BotContext`
(wiring the local-model completion helper and the notifier) and passes it
to each due bot. Bots depend only on this module, so they are trivially
unit-testable with a hand-built ``BotContext`` whose ``complete`` and
``notify`` are fakes — no LLM, no gateway, no network required in tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, runtime_checkable

# (prompt, system, max_tokens) -> completion text, or None if the local
# backbone is unavailable (offline / no model / not installed).
CompleteFn = Callable[..., Optional[str]]

# (message, level) -> None. level is one of "info" | "warning" | "critical".
NotifyFn = Callable[..., None]


@dataclass
class BotResult:
    """Outcome of a single bot run.

    ``notify=True`` asks the scheduler to route ``notify_message`` (or
    ``summary``) through the notifier so it reaches Johnny — this is how a
    background bot escalates something it decided is worth attention
    (feature 10). ``ok=False`` marks a failed run for the health/decision
    layer without raising.
    """

    bot: str
    ok: bool = True
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    notify: bool = False
    notify_message: str = ""
    notify_level: str = "info"

    @classmethod
    def failed(cls, bot: str, summary: str, **details: Any) -> "BotResult":
        return cls(bot=bot, ok=False, summary=summary, details=details)


@dataclass
class BotContext:
    """Everything a bot needs, injected by the scheduler.

    Bots MUST NOT reach for globals, the gateway, or provider clients
    directly — they use ``complete`` (local-model reasoning) and ``notify``
    (surface to Johnny). This keeps them dependency-free and testable.
    """

    config: dict[str, Any]
    zeb_home: Path
    log: logging.Logger
    complete: CompleteFn
    notify: NotifyFn

    def autonomy_dir(self, *parts: str) -> Path:
        """Return (and create) a subdirectory under ``<zeb_home>/autonomy/``."""
        d = self.zeb_home / "autonomy"
        for p in parts:
            d = d / p
        d.mkdir(parents=True, exist_ok=True)
        return d


@runtime_checkable
class Bot(Protocol):
    name: str

    def run(self, ctx: BotContext) -> BotResult: ...
