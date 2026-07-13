"""Process-local beacon of what Zeb's brain is doing right now.

The dashboard's brain visualization shows a live status label —
"Thinking", "Processing", "Learning", "Idle" — that must reflect *actual*
agent activity, not a decorative guess. This tiny module is the shared
truth for the background side of that signal: the autonomy scheduler and
the self-evolution / self-review engines call :func:`set` while they work,
and the dashboard reads :func:`get` through ``GET /api/brain/status``.

It's deliberately dependency-free and thread-safe: a single dict guarded by
a lock, with a TTL so a crashed/hung writer can never pin the label to a
stale "Learning" forever — a reader just sees ``idle`` again once the entry
ages out.

Chat-side activity ("Thinking" while a turn streams) is tracked client-side
in the React chat page; this module owns the autonomous/background half. The
UI merges the two, with the live chat turn taking precedence.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict

# Canonical statuses the brain pill understands. Anything else falls back to
# "processing" on read.
STATUSES = ("idle", "thinking", "processing", "learning")

_lock = threading.Lock()
_state: Dict[str, Any] = {"status": "idle", "detail": "", "ts": 0.0}

# How long a set() entry stays authoritative before we assume the writer is
# gone and report idle. Bots tick for seconds-to-minutes; 120s comfortably
# covers a single bot run without letting a stuck run linger.
_TTL_SECONDS = 120.0


def set(status: str, detail: str = "") -> None:
    """Record the current background activity. Never raises."""
    try:
        s = str(status or "").strip().lower()
        if s not in STATUSES:
            s = "processing"
        with _lock:
            _state["status"] = s
            _state["detail"] = str(detail or "")[:200]
            _state["ts"] = time.time()
    except Exception:
        # A telemetry beacon must never take down its caller.
        pass


def clear() -> None:
    """Return to idle immediately (e.g. when a scheduler tick finishes)."""
    with _lock:
        _state["status"] = "idle"
        _state["detail"] = ""
        _state["ts"] = time.time()


def get(ttl: float = _TTL_SECONDS) -> Dict[str, Any]:
    """Return the current activity, decayed to idle once the TTL lapses."""
    try:
        with _lock:
            status = _state["status"]
            detail = _state["detail"]
            ts = float(_state["ts"] or 0.0)
        age = time.time() - ts if ts else 1e9
        if status != "idle" and age > ttl:
            return {"status": "idle", "detail": "", "age": age}
        return {"status": status, "detail": detail, "age": age}
    except Exception:
        return {"status": "idle", "detail": "", "age": 1e9}
