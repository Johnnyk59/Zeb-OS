"""Private, persistent, always-on local conversation for Gwen.

Gwen deliberately does not use Zeb's user-facing session stores. Its transcript,
rolling summary, schedule, and lease live in a private SQLite database under
``<ZEB_HOME>/autonomy/gwen``. The autonomy scheduler may call this bot often;
the database decides whether reflection or mentoring is actually due.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from zeb_autonomy.base import BotContext, BotResult

_NAME = "gwen"
_DB_NAME = "brain.db"
_DEFAULT_REFLECTION_MINUTES = 30.0
_DEFAULT_MENTOR_MINUTES = 60.0
_DEFAULT_LEASE_SECONDS = 120.0
_DEFAULT_CONTEXT_CHARS = 12_000
_DEFAULT_RECENT_MESSAGES = 24
_DEFAULT_SUMMARY_CHARS = 4_000
_DEFAULT_REFLECTION_TOKENS = 700
_DEFAULT_MENTOR_TOKENS = 700


@dataclass(frozen=True)
class GwenClaim:
    token: str
    reflection_due: bool
    mentor_due: bool


@dataclass(frozen=True)
class MentorSettings:
    provider: str
    model: str
    base_url: str = ""
    api_key: str = ""
    api_mode: str = ""
    timeout: float = 120.0
    max_tokens: int = _DEFAULT_MENTOR_TOKENS
    extra_body: Optional[dict[str, Any]] = None


MentorComplete = Callable[[MentorSettings, list[dict[str, str]]], Optional[str]]


def _positive_float(value: Any, default: float, *, minimum: float = 0.01) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed) or parsed < minimum:
        return default
    return parsed


def _positive_int(value: Any, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _gwen_config(config: dict[str, Any]) -> dict[str, Any]:
    autonomy = config.get("autonomy", {}) if isinstance(config, dict) else {}
    if not isinstance(autonomy, dict):
        return {}
    gwen = autonomy.get("gwen", {})
    return gwen if isinstance(gwen, dict) else {}


def _mentor_settings(config: dict[str, Any]) -> Optional[MentorSettings]:
    """Resolve the configured mentor, defaulting to credential-aware auto routing.

    The user explicitly asked Gwen to seek hourly outside guidance. ``auto``
    attempts the already-configured main/auxiliary provider chain and cleanly
    returns unavailable when no credentialed provider exists; it never invents
    an API key or endpoint.
    """
    auxiliary = config.get("auxiliary", {}) if isinstance(config, dict) else {}
    if not isinstance(auxiliary, dict):
        return None
    raw = auxiliary.get("gwen_mentor", {})
    if not isinstance(raw, dict):
        return None

    provider = str(raw.get("provider") or "auto").strip()
    model = str(raw.get("model") or "").strip()
    if not provider:
        provider = "auto"

    extra_body = raw.get("extra_body")
    if not isinstance(extra_body, dict):
        extra_body = {}
    return MentorSettings(
        provider=provider,
        model=model,
        base_url=str(raw.get("base_url") or "").strip(),
        api_key=str(raw.get("api_key") or "").strip(),
        api_mode=str(raw.get("api_mode") or "").strip(),
        timeout=_positive_float(raw.get("timeout"), 120.0, minimum=1.0),
        max_tokens=_positive_int(
            raw.get("max_tokens"), _DEFAULT_MENTOR_TOKENS, minimum=1
        ),
        extra_body=extra_body,
    )


def _response_text(response: Any) -> Optional[str]:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return None
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if isinstance(content, str):
        text = content.strip()
        return text or None
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            else:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        joined = "\n".join(parts).strip()
        return joined or None
    return None


def _call_explicit_mentor(
    settings: MentorSettings,
    messages: list[dict[str, str]],
) -> Optional[str]:
    """Resolve exactly one configured mentor, with no auto/fallback routing."""
    from agent.auxiliary_client import resolve_provider_client

    client, resolved_model = resolve_provider_client(
        settings.provider,
        model=settings.model or None,
        explicit_base_url=settings.base_url or None,
        explicit_api_key=settings.api_key or None,
        api_mode=settings.api_mode or None,
        task="gwen_mentor",
    )
    if client is None or not resolved_model:
        return None

    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "max_tokens": settings.max_tokens,
        "timeout": settings.timeout,
    }
    if settings.extra_body:
        kwargs["extra_body"] = settings.extra_body
    return _response_text(client.chat.completions.create(**kwargs))


class GwenStore:
    """Private SQLite transcript, summary, due times, and renewable lease."""

    def __init__(self, zeb_home: Path, *, now: Optional[float] = None) -> None:
        self.directory = Path(zeb_home) / "autonomy" / "gwen"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        self.db_path = self.directory / _DB_NAME
        self._initialize(time.time() if now is None else float(now))

    def _secure_files(self) -> None:
        for path in (
            self.db_path,
            Path(f"{self.db_path}-wal"),
            Path(f"{self.db_path}-shm"),
        ):
            try:
                if path.exists():
                    os.chmod(path, 0o600)
            except OSError:
                pass

    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = FULL")
        self._secure_files()
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._new_connection()
        try:
            yield conn
        finally:
            conn.close()
            self._secure_files()

    def _initialize(self, now: float) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    summary TEXT NOT NULL DEFAULT '',
                    next_reflection_at REAL NOT NULL,
                    next_mentor_at REAL NOT NULL,
                    claim_token TEXT,
                    claim_until REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_gwen_messages_created
                    ON messages(created_at, id);
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO state (
                    singleton, summary, next_reflection_at, next_mentor_at,
                    claim_token, claim_until, updated_at
                ) VALUES (1, '', ?, ?, NULL, 0, ?)
                """,
                (now, now, now),
            )
            conn.commit()
        self._secure_files()

    def claim_due(self, *, now: float, lease_seconds: float) -> Optional[GwenClaim]:
        token = uuid.uuid4().hex
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM state WHERE singleton = 1").fetchone()
            if row is None:
                conn.rollback()
                return None
            if row["claim_token"] and float(row["claim_until"] or 0) > now:
                conn.commit()
                return None

            reflection_due = now >= float(row["next_reflection_at"])
            mentor_due = now >= float(row["next_mentor_at"])
            if not reflection_due and not mentor_due:
                if row["claim_token"]:
                    conn.execute(
                        """
                        UPDATE state SET claim_token = NULL, claim_until = 0,
                            updated_at = ? WHERE singleton = 1
                        """,
                        (now,),
                    )
                conn.commit()
                return None

            conn.execute(
                """
                UPDATE state SET claim_token = ?, claim_until = ?, updated_at = ?
                WHERE singleton = 1
                """,
                (token, now + lease_seconds, now),
            )
            conn.commit()
        return GwenClaim(token, reflection_due, mentor_due)

    def refresh_claim(self, token: str, *, now: float, lease_seconds: float) -> bool:
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE state SET claim_until = ?, updated_at = ?
                WHERE singleton = 1 AND claim_token = ?
                """,
                (now + lease_seconds, now, token),
            )
            conn.commit()
            return cursor.rowcount == 1

    def release_claim(self, token: str, *, now: float) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE state SET claim_token = NULL, claim_until = 0, updated_at = ?
                WHERE singleton = 1 AND claim_token = ?
                """,
                (now, token),
            )
            conn.commit()

    def context(self, *, max_chars: int, recent_limit: int) -> tuple[str, str]:
        with self._connection() as conn:
            state = conn.execute(
                "SELECT summary FROM state WHERE singleton = 1"
            ).fetchone()
            rows = conn.execute(
                """
                SELECT role, kind, content FROM messages
                ORDER BY id DESC LIMIT ?
                """,
                (recent_limit,),
            ).fetchall()

        summary = str(state["summary"] if state is not None else "")
        summary = summary[-max_chars:]
        budget = max(0, max_chars - len(summary))
        selected: list[str] = []
        for row in rows:
            line = f"{row['role']} ({row['kind']}): {row['content']}"
            if len(line) > budget and not selected and budget:
                selected.append(line[-budget:])
                budget = 0
                break
            if len(line) > budget:
                break
            selected.append(line)
            budget -= len(line) + 1
        selected.reverse()
        return summary, "\n".join(selected)

    def _finish(
        self,
        token: str,
        *,
        kind: str,
        status: str,
        now: float,
        next_at: float,
        content: Optional[str] = None,
        summary: Optional[str] = None,
        detail: str = "",
    ) -> bool:
        due_column = {
            "reflection": "next_reflection_at",
            "mentor": "next_mentor_at",
        }[kind]
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            owner = conn.execute(
                "SELECT claim_token FROM state WHERE singleton = 1"
            ).fetchone()
            if owner is None or owner["claim_token"] != token:
                conn.rollback()
                return False
            if content:
                role = "gwen" if kind == "reflection" else "mentor"
                conn.execute(
                    """
                    INSERT INTO messages(role, kind, content, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (role, kind, content, now),
                )
            conn.execute(
                """
                INSERT INTO events(kind, status, detail, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (kind, status, detail[:1000], now),
            )
            if summary is None:
                conn.execute(
                    f"UPDATE state SET {due_column} = ?, updated_at = ? "
                    "WHERE singleton = 1 AND claim_token = ?",
                    (next_at, now, token),
                )
            else:
                conn.execute(
                    f"UPDATE state SET {due_column} = ?, summary = ?, updated_at = ? "
                    "WHERE singleton = 1 AND claim_token = ?",
                    (next_at, summary, now, token),
                )
            conn.commit()
            return True

    def finish_reflection(
        self,
        token: str,
        *,
        content: str,
        summary: str,
        now: float,
        next_at: float,
    ) -> bool:
        return self._finish(
            token,
            kind="reflection",
            status="ok",
            content=content,
            summary=summary,
            now=now,
            next_at=next_at,
        )

    def finish_mentor(
        self,
        token: str,
        *,
        content: str,
        now: float,
        next_at: float,
    ) -> bool:
        return self._finish(
            token,
            kind="mentor",
            status="ok",
            content=content,
            now=now,
            next_at=next_at,
        )

    def finish_attempt(
        self,
        token: str,
        *,
        kind: str,
        status: str,
        now: float,
        next_at: float,
        detail: str = "",
    ) -> bool:
        return self._finish(
            token,
            kind=kind,
            status=status,
            detail=detail,
            now=now,
            next_at=next_at,
        )

    def state(self) -> dict[str, Any]:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM state WHERE singleton = 1").fetchone()
        return dict(row) if row is not None else {}

    def messages(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM messages ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def events(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
        return [dict(row) for row in rows]


class _ClaimHeartbeat:
    def __init__(
        self,
        store: GwenStore,
        token: str,
        lease_seconds: float,
        clock: Callable[[], float],
    ) -> None:
        self._store = store
        self._token = token
        self._lease_seconds = lease_seconds
        self._clock = clock
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        interval = max(1.0, min(30.0, self._lease_seconds / 3.0))

        def _run() -> None:
            while not self._stop.wait(interval):
                try:
                    if not self._store.refresh_claim(
                        self._token,
                        now=self._clock(),
                        lease_seconds=self._lease_seconds,
                    ):
                        return
                except Exception:
                    return

        self._thread = threading.Thread(
            target=_run, name="gwen-lease-heartbeat", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _rolling_summary(previous: str, reflection: str, limit: int) -> str:
    combined = "\n".join(part for part in (previous.strip(), reflection.strip()) if part)
    return combined[-limit:]


def _parse_reflection(
    raw: str,
    previous_summary: str,
    *,
    summary_limit: int,
) -> tuple[str, str]:
    reflection = raw.strip()
    summary = ""
    try:
        parsed = json.loads(_strip_json_fence(raw))
        if isinstance(parsed, dict):
            candidate = parsed.get("reflection")
            if isinstance(candidate, str) and candidate.strip():
                reflection = candidate.strip()
            candidate_summary = parsed.get("summary")
            if isinstance(candidate_summary, str):
                summary = candidate_summary.strip()
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    reflection = reflection[:12_000]
    if not summary:
        summary = _rolling_summary(previous_summary, reflection, summary_limit)
    return reflection, summary[-summary_limit:]


def _reflection_prompt(summary: str, recent: str) -> str:
    return (
        "Continue Gwen's private internal conversation. Reflect on the current "
        "state, identify one useful insight or question, and update the rolling "
        "summary. Do not address the user and do not request tools. Return strict "
        'JSON: {"reflection":"...","summary":"..."}.\n\n'
        f"ROLLING SUMMARY\n{summary or '(empty)'}\n\n"
        f"RECENT PRIVATE MESSAGES\n{recent or '(none yet)'}"
    )


def _mentor_messages(summary: str, recent: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are an explicitly configured private mentor for Gwen. "
                "Offer concise, constructive guidance. Do not contact the user, "
                "call tools, or claim actions were performed."
            ),
        },
        {
            "role": "user",
            "content": (
                f"ROLLING SUMMARY\n{summary or '(empty)'}\n\n"
                f"RECENT PRIVATE MESSAGES\n{recent or '(none yet)'}"
            ),
        },
    ]


class GwenBot:
    """Run due private reflection and mentor cycles without user-visible output."""

    name = _NAME

    def __init__(
        self,
        *,
        clock: Optional[Callable[[], float]] = None,
        mentor_complete: Optional[MentorComplete] = None,
    ) -> None:
        self._clock = clock or time.time
        self._mentor_complete = mentor_complete or _call_explicit_mentor

    def run(self, ctx: BotContext) -> BotResult:
        try:
            return self._run(ctx)
        except Exception:
            ctx.log.debug("gwen: private runtime unavailable", exc_info=True)
            return BotResult(
                bot=self.name,
                ok=True,
                summary="private runtime unavailable",
                details={"status": "unavailable"},
                notify=False,
            )

    def _run(self, ctx: BotContext) -> BotResult:
        config = _gwen_config(ctx.config)
        reflection_seconds = _positive_float(
            config.get("reflection_interval_minutes"),
            _DEFAULT_REFLECTION_MINUTES,
        ) * 60.0
        mentor_seconds = _positive_float(
            config.get("mentor_interval_minutes"), _DEFAULT_MENTOR_MINUTES
        ) * 60.0
        lease_seconds = _positive_float(
            config.get("claim_lease_seconds"),
            _DEFAULT_LEASE_SECONDS,
            minimum=10.0,
        )
        context_chars = _positive_int(
            config.get("context_char_limit"), _DEFAULT_CONTEXT_CHARS
        )
        recent_messages = _positive_int(
            config.get("recent_message_limit"), _DEFAULT_RECENT_MESSAGES
        )
        summary_chars = _positive_int(
            config.get("summary_char_limit"), _DEFAULT_SUMMARY_CHARS
        )
        reflection_tokens = _positive_int(
            config.get("reflection_max_tokens"), _DEFAULT_REFLECTION_TOKENS
        )

        now = self._clock()
        store = GwenStore(ctx.zeb_home, now=now)
        claim = store.claim_due(now=now, lease_seconds=lease_seconds)
        if claim is None:
            return BotResult(
                bot=self.name,
                ok=True,
                summary="private runtime idle",
                details={"claimed": False},
                notify=False,
            )

        heartbeat = _ClaimHeartbeat(
            store, claim.token, lease_seconds=lease_seconds, clock=self._clock
        )
        heartbeat.start()
        statuses: dict[str, str] = {}
        try:
            if claim.reflection_due:
                statuses["reflection"] = self._run_reflection(
                    ctx,
                    store,
                    claim.token,
                    interval_seconds=reflection_seconds,
                    context_chars=context_chars,
                    recent_messages=recent_messages,
                    summary_chars=summary_chars,
                    max_tokens=reflection_tokens,
                )
            if claim.mentor_due:
                statuses["mentor"] = self._run_mentor(
                    ctx,
                    store,
                    claim.token,
                    interval_seconds=mentor_seconds,
                    context_chars=context_chars,
                    recent_messages=recent_messages,
                )
        finally:
            heartbeat.stop()
            try:
                store.release_claim(claim.token, now=self._clock())
            except Exception:
                ctx.log.debug("gwen: failed to release private lease", exc_info=True)

        rendered = ", ".join(f"{key}={value}" for key, value in statuses.items())
        return BotResult(
            bot=self.name,
            ok=True,
            summary=f"private cycle: {rendered}" if rendered else "private cycle complete",
            details=statuses,
            notify=False,
        )

    def _run_reflection(
        self,
        ctx: BotContext,
        store: GwenStore,
        token: str,
        *,
        interval_seconds: float,
        context_chars: int,
        recent_messages: int,
        summary_chars: int,
        max_tokens: int,
    ) -> str:
        try:
            summary, recent = store.context(
                max_chars=context_chars, recent_limit=recent_messages
            )
            raw = ctx.complete(
                _reflection_prompt(summary, recent),
                system="You are Gwen's private local reflection process.",
                max_tokens=max_tokens,
            )
            finished = self._clock()
            next_at = finished + interval_seconds
            if not isinstance(raw, str) or not raw.strip():
                store.finish_attempt(
                    token,
                    kind="reflection",
                    status="unavailable",
                    detail="local model returned no text",
                    now=finished,
                    next_at=next_at,
                )
                return "unavailable"
            reflection, next_summary = _parse_reflection(
                raw, summary, summary_limit=summary_chars
            )
            if not store.finish_reflection(
                token,
                content=reflection,
                summary=next_summary,
                now=finished,
                next_at=next_at,
            ):
                return "lease_lost"
            return "ok"
        except Exception as exc:
            finished = self._clock()
            try:
                store.finish_attempt(
                    token,
                    kind="reflection",
                    status="error",
                    detail=f"{type(exc).__name__}: {exc}",
                    now=finished,
                    next_at=finished + interval_seconds,
                )
            except Exception:
                pass
            ctx.log.debug("gwen: local reflection failed", exc_info=True)
            return "error"

    def _run_mentor(
        self,
        ctx: BotContext,
        store: GwenStore,
        token: str,
        *,
        interval_seconds: float,
        context_chars: int,
        recent_messages: int,
    ) -> str:
        settings = _mentor_settings(ctx.config)
        if settings is None:
            finished = self._clock()
            store.finish_attempt(
                token,
                kind="mentor",
                status="unconfigured",
                detail="explicit provider and model are required",
                now=finished,
                next_at=finished + interval_seconds,
            )
            return "unconfigured"

        try:
            summary, recent = store.context(
                max_chars=context_chars, recent_limit=recent_messages
            )
            raw = self._mentor_complete(settings, _mentor_messages(summary, recent))
            finished = self._clock()
            next_at = finished + interval_seconds
            if not isinstance(raw, str) or not raw.strip():
                store.finish_attempt(
                    token,
                    kind="mentor",
                    status="unavailable",
                    detail="configured mentor could not be resolved or returned no text",
                    now=finished,
                    next_at=next_at,
                )
                return "unavailable"
            if not store.finish_mentor(
                token,
                content=raw.strip()[:12_000],
                now=finished,
                next_at=next_at,
            ):
                return "lease_lost"
            return "ok"
        except Exception as exc:
            finished = self._clock()
            try:
                store.finish_attempt(
                    token,
                    kind="mentor",
                    status="error",
                    detail=f"{type(exc).__name__}: {exc}",
                    now=finished,
                    next_at=finished + interval_seconds,
                )
            except Exception:
                pass
            ctx.log.debug("gwen: configured mentor unavailable", exc_info=True)
            return "error"


bot = GwenBot()


__all__ = [
    "GwenBot",
    "GwenClaim",
    "GwenStore",
    "MentorSettings",
    "bot",
]
