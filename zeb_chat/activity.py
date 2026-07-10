"""Thread-safe agent activity tracker for the ZebOS dashboard.

The frontend's 3D brain polls ``GET /api/status`` and reacts to the returned
state. This module keeps a small, process-local, thread-safe view of how many
agent turns are currently active and what kind of work is happening.

States surfaced: "idle" | "thinking" | "processing" | "communicating".

Everything here is fail-open and depends only on the standard library.
"""

from __future__ import annotations

import threading
import time

_VALID_KINDS = ("thinking", "processing", "communicating")

_lock = threading.Lock()
_active = 0
_last_kind = "processing"
_updated_at = time.time()

# Transient note: a short-lived flag (e.g. "communicating") that snapshot()
# surfaces even while idle, until its TTL expires.
_note_kind = ""
_note_detail = ""
_note_expires = 0.0
_note_ttl = 3.0


def begin(kind: str = "processing") -> None:
    """Increment the active-turn count and record the kind + timestamp."""
    global _active, _last_kind, _updated_at
    try:
        if kind not in _VALID_KINDS:
            kind = "processing"
        with _lock:
            _active += 1
            _last_kind = kind
            _updated_at = time.time()
    except Exception:
        pass


def end() -> None:
    """Decrement the active-turn count (never below zero)."""
    global _active, _updated_at
    try:
        with _lock:
            if _active > 0:
                _active -= 1
            _updated_at = time.time()
    except Exception:
        pass


def note(kind: str, detail: str = "") -> None:
    """Briefly flag a transient state with a short TTL (~3s).

    Useful for things like "communicating" that happen instantaneously but
    should still be reflected by the next few ``snapshot()`` calls.
    """
    global _note_kind, _note_detail, _note_expires, _updated_at
    try:
        if kind not in _VALID_KINDS:
            kind = "processing"
        with _lock:
            _note_kind = kind
            _note_detail = str(detail or "")
            _note_expires = time.time() + _note_ttl
            _updated_at = time.time()
    except Exception:
        pass


def snapshot() -> dict:
    """Return the current activity snapshot.

    ``state`` is "idle" when no turns are active (unless a transient note is
    still live), otherwise the most recently recorded kind.
    """
    try:
        now = time.time()
        with _lock:
            active = _active
            last_kind = _last_kind
            updated_at = _updated_at
            note_live = _note_kind if _note_expires > now else ""
            note_detail = _note_detail if _note_expires > now else ""

        if active > 0:
            state = last_kind
            detail = ""
        elif note_live:
            state = note_live
            detail = note_detail
        else:
            state = "idle"
            detail = ""

        return {
            "state": state,
            "active_turns": active,
            "detail": detail,
            "updated_at": updated_at,
        }
    except Exception:
        return {
            "state": "idle",
            "active_turns": 0,
            "detail": "",
            "updated_at": time.time(),
        }
