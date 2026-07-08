"""Persistent interaction/learning store for the autonomy subsystem (feature 3).

A tiny SQLite-backed store that durably records what Zeb sees (interactions),
what Johnny asks for (requests), and what the local model distils from those
over time (learnings). Everything lives in a single file at
``<zeb_home>/autonomy/memory.db`` so it survives gateway restarts and is a
single unit to copy/merge across instances (feature 5, state_sync).

Design notes:
  * Every row has a *content-stable* TEXT primary key. Ids are uuid4 hex by
    default, but the point of a TEXT PK is that cross-instance merge can do
    ``INSERT OR IGNORE`` and dedupe by id without last-writer-wins games —
    re-merging the same database is a no-op.
  * stdlib + sqlite3 only. No third-party deps.
  * Fail-open where it matters: ``merge_from`` never raises out; the bot's
    ``run`` never raises. Constructor/record failures surface to callers of
    the store directly (they are programming/disk errors), but the *bot*
    wrapper swallows them.

The :class:`MemoryLearningBot` reads interactions newer than a persisted
marker and asks ``ctx.complete`` to distil up to three concise learnings,
recording each. If the local model is offline (``complete`` returns ``None``)
or there is nothing new, it is a clean no-op.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from zeb_autonomy.base import BotContext, BotResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions (
    id           TEXT PRIMARY KEY,
    session_id   TEXT,
    role         TEXT,
    content      TEXT,
    ts           REAL,
    metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS requests (
    id         TEXT PRIMARY KEY,
    session_id TEXT,
    request    TEXT,
    ts         REAL
);
CREATE TABLE IF NOT EXISTS learnings (
    id      TEXT PRIMARY KEY,
    topic   TEXT,
    insight TEXT,
    source  TEXT,
    ts      REAL
);
CREATE INDEX IF NOT EXISTS ix_interactions_ts ON interactions(ts);
CREATE INDEX IF NOT EXISTS ix_interactions_session ON interactions(session_id);
"""


def _new_id() -> str:
    return uuid.uuid4().hex


class MemoryStore:
    """SQLite-backed interaction/request/learning store.

    One :class:`MemoryStore` owns one ``memory.db``. Connections are opened
    per call (short-lived) so the store is safe to use from the scheduler
    thread and from tests without juggling a shared connection.
    """

    def __init__(self, zeb_home: Path):
        self.zeb_home = Path(zeb_home)
        self.db_path = self.zeb_home / "autonomy" / "memory.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── low level ────────────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ── writes ───────────────────────────────────────────────────────────
    def record_interaction(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
        ts: Optional[float] = None,
    ) -> str:
        rid = _new_id()
        row_ts = time.time() if ts is None else float(ts)
        meta = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO interactions"
                " (id, session_id, role, content, ts, metadata_json)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (rid, session_id, role, content, row_ts, meta),
            )
        return rid

    def record_request(
        self, session_id: str, request: str, ts: Optional[float] = None
    ) -> str:
        rid = _new_id()
        row_ts = time.time() if ts is None else float(ts)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO requests (id, session_id, request, ts)"
                " VALUES (?, ?, ?, ?)",
                (rid, session_id, request, row_ts),
            )
        return rid

    def record_learning(
        self, topic: str, insight: str, source: str, ts: Optional[float] = None
    ) -> str:
        rid = _new_id()
        row_ts = time.time() if ts is None else float(ts)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO learnings (id, topic, insight, source, ts)"
                " VALUES (?, ?, ?, ?, ?)",
                (rid, topic, insight, source, row_ts),
            )
        return rid

    # ── reads ────────────────────────────────────────────────────────────
    def recent_interactions(
        self, limit: int = 50, session_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM interactions"
        params: list[Any] = []
        if session_id is not None:
            sql += " WHERE session_id = ?"
            params.append(session_id)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._interaction_row(r) for r in rows]

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        like = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM interactions WHERE content LIKE ?"
                " ORDER BY ts DESC, id DESC LIMIT ?",
                (like, int(limit)),
            ).fetchall()
        return [self._interaction_row(r) for r in rows]

    def learnings(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM learnings ORDER BY ts DESC, id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        with self._connect() as conn:
            for table in ("interactions", "requests", "learnings"):
                out[table] = int(
                    conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
        return out

    @staticmethod
    def _interaction_row(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        try:
            d["metadata"] = json.loads(d.get("metadata_json") or "{}")
        except (ValueError, TypeError):
            d["metadata"] = {}
        return d

    # ── cross-instance merge (feature 5) ──────────────────────────────────
    def merge_from(self, other_db_path: Path) -> dict[str, int]:
        """Merge rows from another ``memory.db`` into this one.

        ATTACHes the other database and ``INSERT OR IGNORE``s rows from all
        three tables. Because ids are content-stable TEXT keys, duplicates are
        dropped and re-merging the same database adds nothing. Returns the
        number of rows actually inserted per table. Fail-open: on any error
        returns zero counts rather than raising.
        """
        counts = {"interactions": 0, "requests": 0, "learnings": 0}
        other = Path(other_db_path)
        if not other.exists():
            return counts
        conn = None
        try:
            # Autocommit (isolation_level=None): ATTACH cannot run inside an
            # open transaction, which sqlite3's default implicit BEGIN starts.
            conn = sqlite3.connect(str(self.db_path), isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("ATTACH DATABASE ? AS other", (str(other),))
            try:
                for table, cols in (
                    ("interactions",
                     "id, session_id, role, content, ts, metadata_json"),
                    ("requests", "id, session_id, request, ts"),
                    ("learnings", "id, topic, insight, source, ts"),
                ):
                    before = conn.execute(
                        f"SELECT COUNT(*) FROM main.{table}"
                    ).fetchone()[0]
                    conn.execute(
                        f"INSERT OR IGNORE INTO main.{table} ({cols})"
                        f" SELECT {cols} FROM other.{table}"
                    )
                    after = conn.execute(
                        f"SELECT COUNT(*) FROM main.{table}"
                    ).fetchone()[0]
                    counts[table] = int(after - before)
            finally:
                conn.execute("DETACH DATABASE other")
        except sqlite3.Error:
            return {"interactions": 0, "requests": 0, "learnings": 0}
        finally:
            if conn is not None:
                conn.close()
        return counts


# ── learning bot ──────────────────────────────────────────────────────────
_MARKER_NAME = "memory_learning_marker.json"

_SYSTEM = (
    "You are Zeb's reflection loop. Read recent interactions and distil at "
    "most three concise, durable learnings that would help future responses. "
    "Output one learning per line in the form 'topic: insight'. No preamble."
)


def _read_marker(path: Path) -> float:
    try:
        return float(json.loads(path.read_text("utf-8")).get("last_ts", 0.0))
    except Exception:
        return 0.0


def _write_marker(path: Path, last_ts: float) -> None:
    try:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"last_ts": last_ts}), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _parse_learnings(text: str) -> list[tuple[str, str]]:
    """Lenient parse: one insight per line, ``topic: insight`` if a colon is
    present, otherwise a generic topic. Blank/decorative lines are skipped."""
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*0123456789.) ").strip()
        if not line:
            continue
        if ":" in line:
            topic, insight = line.split(":", 1)
            topic, insight = topic.strip(), insight.strip()
            if not insight:
                topic, insight = "general", topic
        else:
            topic, insight = "general", line
        if insight:
            out.append((topic[:120] or "general", insight))
        if len(out) >= 3:
            break
    return out


class MemoryLearningBot:
    """Distil learnings from new interactions using the local model.

    Reads interactions newer than a persisted ts marker; if there are any and
    ``ctx.complete`` yields text, asks the model for up to three learnings and
    records them (``source='memory_learning'``). No new interactions or an
    offline model → clean no-op. Never raises out of ``run``.
    """

    name = "memory_learning"

    def run(self, ctx: BotContext) -> BotResult:
        try:
            store = MemoryStore(ctx.zeb_home)
            marker_path = ctx.autonomy_dir() / _MARKER_NAME
            last_ts = _read_marker(marker_path)

            recent = store.recent_interactions(limit=200)
            fresh = [r for r in recent if float(r.get("ts") or 0.0) > last_ts]
            if not fresh:
                return BotResult(bot=self.name, ok=True, summary="nothing to learn")

            # Oldest-first for a coherent narrative in the prompt.
            fresh.sort(key=lambda r: float(r.get("ts") or 0.0))
            max_ts = max(float(r.get("ts") or 0.0) for r in fresh)

            transcript = "\n".join(
                f"[{r.get('role')}] {r.get('content')}" for r in fresh
            )[:6000]
            completion = ctx.complete(
                "Recent interactions:\n" + transcript,
                system=_SYSTEM,
                max_tokens=512,
            )
            if not completion:
                # Model offline; do not advance marker so we retry later.
                return BotResult(bot=self.name, ok=True, summary="nothing to learn")

            learnings = _parse_learnings(completion)
            for topic, insight in learnings:
                store.record_learning(topic, insight, source="memory_learning")

            _write_marker(marker_path, max_ts)
            return BotResult(
                bot=self.name,
                ok=True,
                summary=f"recorded {len(learnings)} learning(s) from "
                f"{len(fresh)} interaction(s)",
                details={
                    "learnings": len(learnings),
                    "interactions_seen": len(fresh),
                },
            )
        except Exception as exc:  # fail-open — never wedge the scheduler
            return BotResult.failed(self.name, f"raised: {exc}")
