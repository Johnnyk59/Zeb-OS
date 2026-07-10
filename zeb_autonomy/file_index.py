"""Fast SQLite-backed file index with rename history (features 4 + 8).

Zeb keeps a lightweight index of the files under a set of roots so it (and
its agent tools) can answer "where is X?" in milliseconds instead of walking
the tree every time. The index also remembers *renames*: when a file moves,
its old name/path stays findable and resolves to the file's current location
(feature 8) — so Johnny can search for what he called something last week and
still land on the right file today.

Everything is fail-open: any sqlite/OS error is logged and degraded to a safe
default ([] for queries, 0 for counts). Nothing here ever raises to a caller.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("zeb.autonomy.file_index")

# Directories we never descend into — build/vendor/cache noise that would
# bloat the index and slow refresh without adding anything findable.
_PRUNE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".cache",
}


class FileIndex:
    def __init__(self, zeb_home: Path, roots: "list[Path] | None" = None):
        self.zeb_home = Path(zeb_home)
        self.roots = [Path(r) for r in roots] if roots else [Path.cwd()]
        autonomy = self.zeb_home / "autonomy"
        try:
            autonomy.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.debug("file_index: could not create autonomy dir: %s", exc)
        self.db_path = autonomy / "file_index.db"
        self._init_db()

    # -- schema ------------------------------------------------------------
    def _connect(self) -> "sqlite3.Connection | None":
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as exc:
            log.debug("file_index: connect failed: %s", exc)
            return None

    def _init_db(self) -> None:
        conn = self._connect()
        if conn is None:
            return
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS files (
                        path TEXT PRIMARY KEY,
                        name TEXT,
                        ext TEXT,
                        size INTEGER,
                        mtime REAL,
                        indexed_at REAL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_files_name ON files(name)"
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rename_history (
                        old_path TEXT,
                        old_name TEXT,
                        new_path TEXT,
                        ts REAL
                    )
                    """
                )
        except sqlite3.Error as exc:
            log.debug("file_index: init_db failed: %s", exc)
        finally:
            conn.close()

    # -- refresh -----------------------------------------------------------
    def refresh(self) -> int:
        """Walk every root and upsert every file. Returns count indexed."""
        conn = self._connect()
        if conn is None:
            return 0
        count = 0
        now = time.time()
        try:
            with conn:
                for root in self.roots:
                    try:
                        root = Path(root)
                        if not root.exists():
                            continue
                        for dirpath, dirnames, filenames in os.walk(str(root)):
                            # Prune in place so os.walk skips them entirely.
                            dirnames[:] = [
                                d for d in dirnames if d not in _PRUNE_DIRS
                            ]
                            for fname in filenames:
                                fp = Path(dirpath) / fname
                                try:
                                    st = fp.stat()
                                except OSError:
                                    continue
                                conn.execute(
                                    """
                                    INSERT INTO files
                                        (path, name, ext, size, mtime, indexed_at)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                    ON CONFLICT(path) DO UPDATE SET
                                        name=excluded.name,
                                        ext=excluded.ext,
                                        size=excluded.size,
                                        mtime=excluded.mtime,
                                        indexed_at=excluded.indexed_at
                                    """,
                                    (
                                        str(fp),
                                        fname,
                                        fp.suffix.lower(),
                                        st.st_size,
                                        st.st_mtime,
                                        now,
                                    ),
                                )
                                count += 1
                    except OSError as exc:
                        log.debug("file_index: walk of %s failed: %s", root, exc)
        except sqlite3.Error as exc:
            log.debug("file_index: refresh failed: %s", exc)
            return 0
        finally:
            conn.close()
        return count

    def count(self) -> int:
        conn = self._connect()
        if conn is None:
            return 0
        try:
            cur = conn.execute("SELECT COUNT(*) AS c FROM files")
            row = cur.fetchone()
            return int(row["c"]) if row else 0
        except sqlite3.Error as exc:
            log.debug("file_index: count failed: %s", exc)
            return 0
        finally:
            conn.close()

    # -- find --------------------------------------------------------------
    def find(self, query: str, limit: int = 25) -> "list[dict[str, Any]]":
        """Case-insensitive search ranked by match quality.

        Rank order: exact name > name startswith > name substring > path
        substring. Rename history is also consulted so an OLD name/path
        resolves to the file's CURRENT path. Results are de-duplicated by
        current path.
        """
        q = (query or "").strip()
        if not q:
            return []
        conn = self._connect()
        if conn is None:
            return []
        ql = q.lower()
        try:
            rows = conn.execute(
                "SELECT path, name, size, mtime FROM files"
            ).fetchall()
        except sqlite3.Error as exc:
            log.debug("file_index: find query failed: %s", exc)
            conn.close()
            return []

        # rank: lower is better
        scored: dict[str, tuple[int, dict[str, Any]]] = {}

        def consider(path: str, name: str, size: Any, mtime: Any, rank: int) -> None:
            prev = scored.get(path)
            if prev is None or rank < prev[0]:
                scored[path] = (
                    rank,
                    {
                        "path": path,
                        "name": name,
                        "size": size,
                        "mtime": mtime,
                    },
                )

        for r in rows:
            name = r["name"] or ""
            path = r["path"] or ""
            nl = name.lower()
            pl = path.lower()
            if nl == ql:
                consider(path, name, r["size"], r["mtime"], 0)
            elif nl.startswith(ql):
                consider(path, name, r["size"], r["mtime"], 1)
            elif ql in nl:
                consider(path, name, r["size"], r["mtime"], 2)
            elif ql in pl:
                consider(path, name, r["size"], r["mtime"], 3)

        # Rename history: an old name/path hit resolves to the current file.
        try:
            hist = conn.execute(
                "SELECT old_path, old_name, new_path FROM rename_history"
            ).fetchall()
        except sqlite3.Error:
            hist = []
        for h in hist:
            old_name = (h["old_name"] or "").lower()
            old_path = (h["old_path"] or "").lower()
            new_path = h["new_path"] or ""
            if not new_path:
                continue
            matched = False
            rank = 4  # history matches rank below direct hits
            if old_name == ql:
                matched, rank = True, 4
            elif old_name.startswith(ql) or ql in old_name:
                matched, rank = True, 5
            elif ql in old_path:
                matched, rank = True, 6
            if not matched:
                continue
            # Resolve to the current row for new_path if we have one.
            try:
                cur = conn.execute(
                    "SELECT path, name, size, mtime FROM files WHERE path=?",
                    (new_path,),
                ).fetchone()
            except sqlite3.Error:
                cur = None
            if cur is not None:
                consider(cur["path"], cur["name"], cur["size"], cur["mtime"], rank)
            else:
                consider(new_path, Path(new_path).name, None, None, rank)

        conn.close()

        ordered = sorted(scored.values(), key=lambda t: (t[0], t[1]["name"]))
        return [d for _, d in ordered[: max(0, int(limit))]]

    # -- rename ------------------------------------------------------------
    def record_rename(self, old_path: str, new_path: str) -> bool:
        """Move the row for old_path to new_path and log the rename.

        The old name/path is preserved in rename_history so it stays
        findable. Returns True on success, False (fail-open) on error.
        """
        conn = self._connect()
        if conn is None:
            return False
        old_p = str(old_path)
        new_p = str(new_path)
        old_name = Path(old_p).name
        new_name = Path(new_p).name
        now = time.time()
        try:
            with conn:
                # Pull the existing row (if any) to carry size/mtime forward.
                row = conn.execute(
                    "SELECT size, mtime FROM files WHERE path=?", (old_p,)
                ).fetchone()
                size = row["size"] if row else None
                mtime = row["mtime"] if row else None
                # If the file exists on disk now, prefer fresh stat.
                try:
                    st = Path(new_p).stat()
                    size, mtime = st.st_size, st.st_mtime
                except OSError:
                    pass
                conn.execute("DELETE FROM files WHERE path=?", (old_p,))
                conn.execute(
                    """
                    INSERT INTO files (path, name, ext, size, mtime, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        name=excluded.name,
                        ext=excluded.ext,
                        size=excluded.size,
                        mtime=excluded.mtime,
                        indexed_at=excluded.indexed_at
                    """,
                    (
                        new_p,
                        new_name,
                        Path(new_p).suffix.lower(),
                        size,
                        mtime,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO rename_history (old_path, old_name, new_path, ts)
                    VALUES (?, ?, ?, ?)
                    """,
                    (old_p, old_name, new_p, now),
                )
            return True
        except sqlite3.Error as exc:
            log.debug("file_index: record_rename failed: %s", exc)
            return False
        finally:
            conn.close()
