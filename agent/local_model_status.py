"""In-memory activity + download tracking for the local GGUF backbone.

The dashboard's "Local Model Status" panel needs to answer, live: which
model is active, is it loaded, how much has it downloaded, and what has it
been *doing* recently. None of that is worth a database — it's ephemeral,
process-local telemetry — so this module keeps it in a small ring buffer
plus a couple of counters, all guarded by one lock and entirely fail-open.

``agent/llama_cpp_adapter.py`` (load / unload / ping) and
``agent/local_model_manager.py`` (resolve / download) push events here; the
``/api/localmodel`` endpoint reads :func:`snapshot`. Nothing here imports
the heavy model stack, so it's safe to import from anywhere (including the
web layer) without dragging llama.cpp in.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Optional

# Keep the last N events only — this is a live activity feed, not an audit
# log. 200 lines is plenty for the panel and stays trivially cheap.
_MAX_EVENTS = 200

_lock = threading.Lock()
_events: Deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)

# Download progress for the one-time weight fetch. total_bytes may be 0 when
# the server doesn't report a content-length; active flips false on
# completion or failure.
_dl_active = False
_dl_downloaded = 0
_dl_total = 0
_dl_file = ""
_dl_started_at = 0.0
_dl_finished_at = 0.0


def record(event: str, detail: str = "", level: str = "info") -> None:
    """Append a timestamped activity line. Never raises."""
    try:
        with _lock:
            _events.append(
                {
                    "ts": time.time(),
                    "level": level if level in ("info", "warn", "error") else "info",
                    "event": str(event or ""),
                    "detail": str(detail or ""),
                }
            )
    except Exception:
        pass


def download_started(file: str = "", total_bytes: int = 0) -> None:
    global _dl_active, _dl_downloaded, _dl_total, _dl_file, _dl_started_at, _dl_finished_at
    try:
        with _lock:
            _dl_active = True
            _dl_downloaded = 0
            _dl_total = int(total_bytes or 0)
            _dl_file = str(file or "")
            _dl_started_at = time.time()
            _dl_finished_at = 0.0
        record("download.start", f"{file} ({_human(total_bytes)})" if total_bytes else file)
    except Exception:
        pass


def download_progress(downloaded_bytes: int, total_bytes: Optional[int] = None) -> None:
    global _dl_downloaded, _dl_total
    try:
        with _lock:
            _dl_downloaded = int(downloaded_bytes or 0)
            if total_bytes:
                _dl_total = int(total_bytes)
    except Exception:
        pass


def download_finished(ok: bool = True, detail: str = "") -> None:
    global _dl_active, _dl_finished_at, _dl_downloaded
    try:
        with _lock:
            _dl_active = False
            _dl_finished_at = time.time()
            if ok and _dl_total:
                _dl_downloaded = _dl_total
        record(
            "download.finish" if ok else "download.error",
            detail,
            level="info" if ok else "error",
        )
    except Exception:
        pass


def _human(n: int | float) -> str:
    try:
        n = float(n or 0)
    except Exception:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def snapshot() -> dict[str, Any]:
    """Return the current events + download state. Always safe to call."""
    try:
        with _lock:
            events = list(_events)
            active = _dl_active
            downloaded = _dl_downloaded
            total = _dl_total
            file = _dl_file
            started = _dl_started_at
            finished = _dl_finished_at
        pct = 0.0
        if total > 0:
            pct = max(0.0, min(100.0, (downloaded / total) * 100.0))
        elif finished and not active:
            pct = 100.0
        rate = 0.0
        if active and started:
            elapsed = max(0.001, time.time() - started)
            rate = downloaded / elapsed  # bytes/sec
        return {
            "events": events,
            "download": {
                "active": active,
                "downloaded_bytes": downloaded,
                "total_bytes": total,
                "percent": round(pct, 1),
                "file": file,
                "rate_bps": rate,
                "human_downloaded": _human(downloaded),
                "human_total": _human(total) if total else "",
                "human_rate": _human(rate) + "/s" if rate else "",
            },
        }
    except Exception:
        return {"events": [], "download": {"active": False, "downloaded_bytes": 0,
                                           "total_bytes": 0, "percent": 0.0}}
