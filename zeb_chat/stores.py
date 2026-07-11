"""Small JSON-file backed stores for the ZebOS dashboard.

Data lives under ``<zeb_home>/chat/`` where ``zeb_home`` is resolved via
``zeb_constants.get_zeb_home()`` (guarded, falling back to ``~/.zeb``).

Design rules:
  * Fail-open — reads return ``[]`` / ``None`` on any error, never raise.
  * Atomic writes — write to a temp file then ``os.replace`` into place.
  * Key files are chmod 0600.
  * Raw API keys are never logged.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


def _zeb_home() -> Path:
    try:
        import zeb_constants

        return Path(zeb_constants.get_zeb_home())
    except Exception:
        return Path.home() / ".zeb"


def _chat_dir() -> Path:
    return _zeb_home() / "chat"


def _atomic_write(path: Path, data: str, mode: int | None = None) -> bool:
    """Atomically write ``data`` to ``path`` (tmp + replace). Fail-open."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                pass
        if mode is not None:
            try:
                os.chmod(tmp, mode)
            except Exception:
                pass
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False


def _read_json(path: Path, default):
    try:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _mask(key: str) -> str:
    key = str(key or "")
    if len(key) <= 8:
        return "•••"
    return key[:4] + "…" + key[-4:]


class ApiKeyStore:
    """Store of user-managed API keys under ``chat/api_keys.json``."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._path = (Path(base_dir) if base_dir else _chat_dir()) / "api_keys.json"

    def _load(self) -> list:
        data = _read_json(self._path, [])
        return data if isinstance(data, list) else []

    def add(self, key: str, label: str) -> dict:
        entry = {
            "id": uuid.uuid4().hex,
            "label": str(label or ""),
            "key": str(key or ""),
            "masked": _mask(key),
            "created_at": time.time(),
        }
        try:
            items = self._load()
            items.append(entry)
            _atomic_write(self._path, json.dumps(items, indent=2), mode=0o600)
        except Exception:
            pass
        return self._public(entry)

    @staticmethod
    def _public(entry: dict) -> dict:
        return {
            "id": entry.get("id"),
            "label": entry.get("label", ""),
            "masked": entry.get("masked", "•••"),
            "created_at": entry.get("created_at"),
        }

    def list(self) -> list:
        try:
            return [self._public(e) for e in self._load() if isinstance(e, dict)]
        except Exception:
            return []

    def delete(self, id: str) -> bool:
        try:
            items = self._load()
            remaining = [e for e in items if e.get("id") != id]
            if len(remaining) == len(items):
                return False
            return _atomic_write(
                self._path, json.dumps(remaining, indent=2), mode=0o600
            )
        except Exception:
            return False


class ChannelStore:
    """User-added messaging channels under ``chat/channels.json``.

    Each entry is a name + a token (e.g. a Telegram bot token). Tokens are
    masked on read, mirroring ``ApiKeyStore``.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._path = (Path(base_dir) if base_dir else _chat_dir()) / "channels.json"

    def _load(self) -> list:
        data = _read_json(self._path, [])
        return data if isinstance(data, list) else []

    def add(self, name: str, token: str, kind: str = "telegram") -> dict:
        entry = {
            "id": uuid.uuid4().hex,
            "name": str(name or ""),
            "kind": str(kind or "telegram"),
            "token": str(token or ""),
            "masked": _mask(token),
            "created_at": time.time(),
        }
        try:
            items = self._load()
            items.append(entry)
            _atomic_write(self._path, json.dumps(items, indent=2), mode=0o600)
        except Exception:
            pass
        return self._public(entry)

    @staticmethod
    def _public(entry: dict) -> dict:
        return {
            "id": entry.get("id"),
            "name": entry.get("name", ""),
            "kind": entry.get("kind", "telegram"),
            "masked": entry.get("masked", "•••"),
            "created_at": entry.get("created_at"),
        }

    def list(self) -> list:
        try:
            return [self._public(e) for e in self._load() if isinstance(e, dict)]
        except Exception:
            return []

    def delete(self, id: str) -> bool:
        try:
            items = self._load()
            remaining = [e for e in items if e.get("id") != id]
            if len(remaining) == len(items):
                return False
            return _atomic_write(
                self._path, json.dumps(remaining, indent=2), mode=0o600
            )
        except Exception:
            return False


class SessionStore:
    """Chat sessions, one JSON file per session under ``chat/sessions/``."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._dir = (Path(base_dir) if base_dir else _chat_dir()) / "sessions"

    def _path(self, sid: str) -> Path:
        return self._dir / f"{sid}.json"

    def create(self, title: str = "") -> dict:
        now = time.time()
        sid = uuid.uuid4().hex
        session = {
            "id": sid,
            "title": str(title or "") or "New chat",
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }
        try:
            _atomic_write(self._path(sid), json.dumps(session, indent=2))
        except Exception:
            pass
        return session

    def get(self, id: str) -> dict | None:
        data = _read_json(self._path(id), None)
        return data if isinstance(data, dict) else None

    def list(self) -> list:
        out = []
        try:
            if not self._dir.exists():
                return []
            for p in self._dir.glob("*.json"):
                data = _read_json(p, None)
                if not isinstance(data, dict):
                    continue
                out.append(
                    {
                        "id": data.get("id"),
                        "title": data.get("title", ""),
                        "message_count": len(data.get("messages", []) or []),
                        "updated_at": data.get("updated_at"),
                    }
                )
            out.sort(key=lambda s: s.get("updated_at") or 0, reverse=True)
        except Exception:
            return []
        return out

    def append(self, id: str, role: str, content: str) -> bool:
        try:
            session = self.get(id)
            if session is None:
                return False
            messages = session.get("messages")
            if not isinstance(messages, list):
                messages = []
            messages.append(
                {"role": str(role or ""), "content": str(content or ""), "ts": time.time()}
            )
            session["messages"] = messages
            session["updated_at"] = time.time()
            # Derive a title from the first user message if still default.
            if (not session.get("title")) or session.get("title") == "New chat":
                for m in messages:
                    if m.get("role") == "user" and m.get("content"):
                        snippet = str(m["content"]).strip().splitlines()[0][:60]
                        if snippet:
                            session["title"] = snippet
                        break
            return _atomic_write(self._path(id), json.dumps(session, indent=2))
        except Exception:
            return False

    def delete(self, id: str) -> bool:
        try:
            p = self._path(id)
            if not p.exists():
                return False
            p.unlink()
            return True
        except Exception:
            return False
