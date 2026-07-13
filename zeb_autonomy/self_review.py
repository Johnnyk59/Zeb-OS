"""Self-review engine — Zeb writes periodic accounts of its own work.

Backs the three "Six / Twelve / Twenty-Four Hour Review" buttons in the
dashboard's Local Model panel. Each review is a first-person, local-model-
written summary of everything Zeb actually did in the window — chats it had,
autonomy bots that ran, knowledge it ingested, files it organized, and how
its self-evolution engine progressed — assembled from real on-disk activity,
not invented.

Reviews are generated on demand (the buttons) *and* refreshed automatically
by :class:`ReviewBot` on a cadence, so they stay current without anyone
clicking. Each window persists to ``<zeb_home>/autonomy/reviews/`` as both
Markdown (for reading) and an ``index.json`` (generation timestamps), so the
history survives restarts.

Everything here is fail-open: if the local model is offline or there's no
activity, a review still writes — it just says "a quiet window", and the
caller never sees an exception.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# window key -> hours. These are the three buttons in the UI.
WINDOWS: dict[str, int] = {"6h": 6, "12h": 12, "24h": 24}

_MAX_MATERIAL_CHARS = 14000

# Track which windows are mid-generation so the UI can show a spinner and a
# second click doesn't kick a duplicate run. Guarded because the web endpoint
# and the ReviewBot can both reach here from different threads.
_gen_lock = threading.Lock()
_generating: set[str] = set()


def reviews_dir(zeb_home: Path) -> Path:
    d = zeb_home / "autonomy" / "reviews"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(zeb_home: Path) -> Path:
    return reviews_dir(zeb_home) / "index.json"


def _md_path(zeb_home: Path, window: str) -> Path:
    return reviews_dir(zeb_home) / f"review_{window}.md"


def _load_index(zeb_home: Path) -> dict[str, Any]:
    try:
        return json.loads(_index_path(zeb_home).read_text("utf-8"))
    except Exception:
        return {}


def _save_index(zeb_home: Path, index: dict[str, Any]) -> None:
    try:
        p = _index_path(zeb_home)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(index, indent=2), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


# ── activity gathering ───────────────────────────────────────────────────


def _within(mtime: float, cutoff: float) -> bool:
    return mtime >= cutoff


def _gather_sessions(zeb_home: Path, cutoff: float) -> list[str]:
    """Recent chat turns from session transcripts touched within the window."""
    out: list[str] = []
    sessions = zeb_home / "sessions"
    if not sessions.is_dir():
        return out
    files = [
        p
        for p in sessions.rglob("*")
        if p.is_file() and p.suffix in (".json", ".jsonl")
    ]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    total = 0
    for path in files:
        try:
            if not _within(path.stat().st_mtime, cutoff):
                continue
            raw = path.read_text("utf-8", errors="replace")
        except OSError:
            continue
        snippet = raw.strip()
        if snippet:
            chunk = snippet[:2000]
            out.append(f"[chat {path.stem}] {chunk}")
            total += len(chunk)
        if total >= _MAX_MATERIAL_CHARS // 2:
            break
    return out


def _gather_autonomy(zeb_home: Path, cutoff: float) -> list[str]:
    """Recent autonomy artifacts: schedule cadence, persona notes, knowledge."""
    out: list[str] = []
    auto = zeb_home / "autonomy"
    if not auto.is_dir():
        return out

    # Schedule state → which bots ran and when.
    try:
        state = json.loads((auto / "schedule_state.json").read_text("utf-8"))
        ran = [
            f"{name} (last run {_ago(ts)})"
            for name, ts in sorted(state.items(), key=lambda kv: -float(kv[1] or 0))
            if float(ts or 0) >= cutoff
        ]
        if ran:
            out.append("[autonomy bots that ran] " + ", ".join(ran))
    except Exception:
        pass

    # Persona reflections, knowledge digests, evolution notes — any markdown or
    # text artifact freshly written in the window.
    for sub in ("persona", "knowledge", "evolution"):
        d = auto / sub
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*"), key=lambda p: -_safe_mtime(p)):
            try:
                if not path.is_file() or path.suffix not in (".md", ".txt", ".json"):
                    continue
                if not _within(path.stat().st_mtime, cutoff):
                    continue
                text = path.read_text("utf-8", errors="replace").strip()
                if text:
                    out.append(f"[{sub}/{path.name}] {text[:1500]}")
            except OSError:
                continue
    return out


def _gather_local_model_events(cutoff: float) -> list[str]:
    """Recent backbone activity from the local-model status ring buffer."""
    try:
        from agent import local_model_status

        snap = local_model_status.snapshot()
        events = snap.get("events", []) or []
        rows = [
            f"{e.get('event', '')}: {e.get('detail', '')}"
            for e in events
            if float(e.get("ts", 0) or 0) >= cutoff
        ]
        if rows:
            return ["[local model] " + "; ".join(rows[-20:])]
    except Exception:
        pass
    return []


def _safe_mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _ago(ts: Any) -> str:
    try:
        secs = time.time() - float(ts)
    except (TypeError, ValueError):
        return "recently"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{secs / 3600:.1f}h ago"
    return f"{secs / 86400:.1f}d ago"


def _collect_material(zeb_home: Path, hours: int) -> str:
    cutoff = time.time() - hours * 3600
    parts: list[str] = []
    parts += _gather_autonomy(zeb_home, cutoff)
    parts += _gather_local_model_events(cutoff)
    parts += _gather_sessions(zeb_home, cutoff)
    return "\n\n".join(parts)[:_MAX_MATERIAL_CHARS]


# ── generation ───────────────────────────────────────────────────────────


def _fallback_markdown(window: str, hours: int, material: str) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    if material.strip():
        body = (
            "The local model was offline, so here is the raw activity log for "
            f"the last {hours} hours instead of a written summary:\n\n"
            "```\n" + material[:4000] + "\n```"
        )
    else:
        body = f"A quiet window — no recorded activity in the last {hours} hours."
    return (
        f"# {hours}-Hour Review\n\n_Generated {ts}_\n\n{body}\n"
    )


def _complete_fn(config: Optional[dict[str, Any]]) -> Callable[..., Optional[str]]:
    from zeb_autonomy import local_llm

    def _c(prompt: str, *, system: str = "", max_tokens: int = 700) -> Optional[str]:
        return local_llm.complete(
            prompt, system=system, max_tokens=max_tokens, config=config
        )

    return _c


def generate_review(
    window: str,
    *,
    config: Optional[dict[str, Any]] = None,
    zeb_home: Optional[Path] = None,
    complete: Optional[Callable[..., Optional[str]]] = None,
) -> dict[str, Any]:
    """Generate, persist and return one review window. Never raises."""
    window = str(window or "").strip().lower()
    if window not in WINDOWS:
        window = "24h"
    hours = WINDOWS[window]

    if zeb_home is None:
        from zeb_constants import get_zeb_home

        zeb_home = get_zeb_home()
    if config is None:
        try:
            from zeb_cli.config import load_config

            config = load_config()
        except Exception:
            config = {}

    with _gen_lock:
        _generating.add(window)
    try:
        material = _collect_material(zeb_home, hours)
        markdown = None
        cfn = complete or _complete_fn(config)
        if material.strip():
            prompt = (
                f"You are Zeb, an autonomous AI assistant. Write a first-person "
                f"review of everything you accomplished in the last {hours} hours, "
                f"based ONLY on the activity log below. Be concrete and specific: "
                f"name the tasks, chats, knowledge learned, files handled, and how "
                f"your own capabilities evolved. Use Markdown with a short intro "
                f"paragraph then '## Highlights', '## Learning & Evolution', and "
                f"'## What's Next' sections. If the log is thin, say so honestly "
                f"and keep it brief.\n\n"
                f"--- ACTIVITY LOG (last {hours}h) ---\n{material}\n--- END ---"
            )
            try:
                text = cfn(
                    prompt,
                    system="You are Zeb, reviewing your own recent work honestly.",
                    max_tokens=800,
                )
                if text and str(text).strip():
                    ts = datetime.now(timezone.utc).isoformat()
                    markdown = (
                        f"# {hours}-Hour Review\n\n_Generated {ts}_\n\n"
                        f"{str(text).strip()}\n"
                    )
            except Exception:
                markdown = None
        if not markdown:
            markdown = _fallback_markdown(window, hours, material)

        generated_at = time.time()
        try:
            _md_path(zeb_home, window).write_text(markdown, encoding="utf-8")
            index = _load_index(zeb_home)
            index[window] = {"generated_at": generated_at, "hours": hours}
            _save_index(zeb_home, index)
        except OSError:
            pass

        return {
            "window": window,
            "window_hours": hours,
            "markdown": markdown,
            "generated_at": generated_at,
            "generating": False,
            "stale": False,
        }
    finally:
        with _gen_lock:
            _generating.discard(window)


def kick_review(
    window: str,
    *,
    config: Optional[dict[str, Any]] = None,
    zeb_home: Optional[Path] = None,
) -> dict[str, Any]:
    """Start a review generation in the background; return an immediate snapshot.

    De-duplicates: a second kick for a window already generating is a no-op.
    The caller (dashboard) polls :func:`load_reviews` to see the finished text.
    """
    window = str(window or "").strip().lower()
    if window not in WINDOWS:
        window = "24h"
    if zeb_home is None:
        from zeb_constants import get_zeb_home

        zeb_home = get_zeb_home()

    with _gen_lock:
        already = window in _generating
        if not already:
            _generating.add(window)  # reserve immediately so the UI shows a spinner

    if not already:

        def _run() -> None:
            try:
                generate_review(window, config=config, zeb_home=zeb_home)
            finally:
                with _gen_lock:
                    _generating.discard(window)

        threading.Thread(target=_run, name=f"review-{window}", daemon=True).start()

    snapshot = next(
        (r for r in load_reviews(zeb_home) if r["window"] == window),
        {
            "window": window,
            "window_hours": WINDOWS[window],
            "markdown": "",
            "generated_at": None,
            "stale": True,
        },
    )
    snapshot = dict(snapshot)
    snapshot["generating"] = True
    return snapshot


def load_reviews(zeb_home: Optional[Path] = None) -> list[dict[str, Any]]:
    """Return the three persisted review windows (whatever is on disk)."""
    if zeb_home is None:
        from zeb_constants import get_zeb_home

        zeb_home = get_zeb_home()
    index = _load_index(zeb_home)
    now = time.time()
    out: list[dict[str, Any]] = []
    with _gen_lock:
        generating = set(_generating)
    for window, hours in WINDOWS.items():
        meta = index.get(window) or {}
        generated_at = meta.get("generated_at")
        try:
            markdown = _md_path(zeb_home, window).read_text("utf-8")
        except OSError:
            markdown = ""
        # A review is "stale" once it's older than its own window.
        stale = bool(
            generated_at and (now - float(generated_at)) > hours * 3600
        )
        out.append(
            {
                "window": window,
                "window_hours": hours,
                "markdown": markdown,
                "generated_at": generated_at,
                "generating": window in generating,
                "stale": stale or not markdown,
            }
        )
    return out


# ── autonomy bot ─────────────────────────────────────────────────────────


class ReviewBot:
    """Keeps the 6h/12h/24h reviews current by regenerating stale windows."""

    name = "self_review"

    def run(self, ctx: Any) -> Any:
        from zeb_autonomy.base import BotResult

        try:
            refreshed: list[str] = []
            reviews = load_reviews(ctx.zeb_home)
            for r in reviews:
                # Refresh a window when it's missing or older than a third of
                # its span — so a 6h review is at most ~2h stale, etc.
                gen = r.get("generated_at")
                hours = r.get("window_hours", 24)
                due = (
                    not r.get("markdown")
                    or gen is None
                    or (time.time() - float(gen)) > (hours * 3600) / 3
                )
                if due:
                    generate_review(
                        r["window"],
                        config=ctx.config,
                        zeb_home=ctx.zeb_home,
                        complete=ctx.complete,
                    )
                    refreshed.append(r["window"])
            summary = (
                f"refreshed reviews: {', '.join(refreshed)}"
                if refreshed
                else "all reviews current"
            )
            return BotResult(bot=self.name, ok=True, summary=summary)
        except Exception as exc:  # never raise
            ctx.log.debug("self_review: %s", exc, exc_info=True)
            return BotResult.failed(self.name, f"error: {exc}")


bot = ReviewBot()
