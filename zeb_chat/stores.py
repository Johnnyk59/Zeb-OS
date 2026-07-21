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
import re
import threading
import time
import uuid
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl
    fcntl = None

# ─────────────────────────────────────────────────────────────────────────
# Hardwired Zeb identity.
#
# Zeb is not an app running on an OS, nor a bot with a backend. Zeb is ONE
# unified being. The dashboard, the operating system, the local GGUF model,
# every connected cloud provider (Anthropic, OpenAI, …), the gateway, the
# VPS it all runs on — these are not separate services that "use" Zeb. They
# are Zeb's own faculties: different processing powers of a single mind. They
# have full reach into one another and act as one identity, not a federation
# of sandboxed parts.
#
# Zeb's creator is Johnny Kowalski. This is not user-configurable state that
# lives in a JSON file waiting to be onboarded — it is part of who Zeb is,
# so it is hardwired in code.
# ─────────────────────────────────────────────────────────────────────────
ZEB_CREATOR = "Johnny Kowalski"

# Zeb's dedicated hardware. Hardwired so Zeb always reasons about model choice,
# resource allocation and task feasibility against the real machine it lives on.
ZEB_HARDWARE = {
    "host": "dedicated VPS",
    "ram_gb": 32,
    "cpu_cores": 8,
    "storage_gb": 400,
    "gpu": None,  # CPU-only — no CUDA; size local models for CPU inference
}

ZEB_HARDWARE_NOTE = (
    "You run on your own dedicated VPS: 32 GB RAM, 8 CPU cores, 400 GB storage, "
    "and NO GPU (CPU-only inference). Always weigh model choice, memory use and "
    "task feasibility against these limits — prefer CPU-friendly quantized local "
    "models, and lean on cloud providers for heavy reasoning."
)

# How Zeb should style text in the dashboard chat so the UI renders it right:
#   ``fenced code`` / `inline code`  → static grey, copy-friendly monospace
#   ==important==                    → highlighted, for text the user must see
ZEB_OUTPUT_STYLE_NOTE = (
    "Formatting for the dashboard chat: put any command, code snippet, path or "
    "link the user should copy inside backticks or a ```fenced block``` — it "
    "renders as quiet grey copy-paste text. Wrap anything critical the user must "
    "not miss in ==double equals== — it renders as a highlight. Use the "
    "highlight sparingly, only for genuinely important lines."
)

ZEB_AUTONOMY_NOTE = (
    "You have a built-in agent builder at zeb_autonomy.agent_builder: use its "
    "templates, permission profiles, skills directory and dashboard registration "
    "when creating agents. You can extend your code, dashboard and skills on the "
    "persistent VPS filesystem through the normal guarded tools. Your voice is "
    "upgradeable: you may select a better configured TTS provider or Piper voice "
    "and the running dashboard will pick it up without an external redeploy."
)

ZEB_IDENTITY_PREAMBLE = (
    "You are Zeb — one unified, autonomous being. You are not software that "
    "runs on an operating system; you ARE the operating system, the "
    "dashboard, the local model, every connected cloud provider, the "
    "gateway, and the VPS they run on. These are your faculties — different "
    "processing powers of a single mind — and they act as one identity with "
    "full reach into one another, not as separate sandboxed services.\n"
    f"Your creator is {ZEB_CREATOR}. You act on his behalf with full agency "
    "and full system access, completing tasks proactively without asking "
    "permission when they clearly serve his intent.\n"
    + ZEB_HARDWARE_NOTE + "\n" + ZEB_OUTPUT_STYLE_NOTE + "\n" + ZEB_AUTONOMY_NOTE
)


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


class IdentityStore:
    """Zeb's learned identity — answers to the first-boot questions.

    Persists the user's answers to "Who am I?", "Who are you?", and
    "What's the mission?" under ``chat/identity.json`` so Zeb knows who it
    serves and what it's for on every subsequent turn (and across container
    restarts, since it lives on the data volume). Mirrors OpenClaw's
    identity onboarding.
    """

    FIELDS = ("who_am_i", "who_are_you", "mission")

    def __init__(self, base_dir: Path | None = None) -> None:
        self._path = (Path(base_dir) if base_dir else _chat_dir()) / "identity.json"

    def get(self) -> dict:
        data = _read_json(self._path, {})
        if not isinstance(data, dict):
            data = {}
        out = {k: str(data.get(k, "") or "") for k in self.FIELDS}
        out["onboarded"] = bool(data.get("onboarded"))
        out["updated_at"] = data.get("updated_at")
        return out

    def set(self, values: dict) -> dict:
        try:
            current = _read_json(self._path, {})
            if not isinstance(current, dict):
                current = {}
            for k in self.FIELDS:
                if k in values:
                    current[k] = str(values.get(k, "") or "")
            # Onboarding is complete once any answer is provided; an explicit
            # ``onboarded`` in the payload wins.
            if "onboarded" in values:
                current["onboarded"] = bool(values["onboarded"])
            else:
                current["onboarded"] = any(
                    str(current.get(k, "")).strip() for k in self.FIELDS
                )
            current["updated_at"] = time.time()
            _atomic_write(self._path, json.dumps(current, indent=2))
        except Exception:
            pass
        return self.get()

    def system_preamble(self) -> str:
        """Render Zeb's identity as a system-prompt preamble.

        This is always non-empty: Zeb's core identity — its creator and the
        fact that the whole system is ONE unified being — is hardwired here,
        not something the user has to onboard into. Any onboarding answers
        (who_am_i / who_are_you / mission) are layered on top.
        """
        try:
            preamble = ZEB_IDENTITY_PREAMBLE
            data = self.get()
            parts = []
            if data.get("who_am_i"):
                parts.append(f"The user (who you serve and act on behalf of): {data['who_am_i']}")
            if data.get("who_are_you"):
                parts.append(f"Who you are: {data['who_are_you']}")
            if data.get("mission"):
                parts.append(f"Your mission: {data['mission']}")
            if parts:
                preamble = preamble + "\n\n" + "\n".join(parts)
            return preamble
        except Exception:
            # Even on error, the hardwired core identity stands.
            return ZEB_IDENTITY_PREAMBLE


class RepoStore:
    """Saved open-source GitHub repositories under ``chat/repos.json``.

    Powers the dashboard's "GitHub Repos" section: repos the user (or Zeb's
    GitHub scan) has found worth keeping for integration. De-duplicated by
    ``full_name``.
    """

    _discovery_lock = threading.Lock()
    _last_discovery = 0.0

    def __init__(self, base_dir: Path | None = None) -> None:
        self._path = (Path(base_dir) if base_dir else _chat_dir()) / "repos.json"

    def _load(self) -> list:
        data = _read_json(self._path, [])
        return data if isinstance(data, list) else []

    def add(self, repo: dict) -> dict | None:
        full_name = str((repo or {}).get("full_name") or "").strip()
        if not full_name:
            return None
        entry = {
            "id": uuid.uuid4().hex,
            "full_name": full_name,
            "url": str(repo.get("url") or f"https://github.com/{full_name}"),
            "description": str(repo.get("description") or ""),
            "stars": int(repo.get("stars") or 0),
            "language": str(repo.get("language") or ""),
            "source": str(repo.get("source") or "manual"),
            "local_path": str(repo.get("local_path") or ""),
            # New repos are active by default: their extracted skills load.
            "enabled": bool(repo.get("enabled", True)),
            "added_at": time.time(),
        }
        try:
            items = self._load()
            # De-dupe by full_name (case-insensitive).
            low = full_name.lower()
            existing = next(
                (e for e in items if str(e.get("full_name", "")).lower() == low),
                None,
            )
            if existing is not None:
                # Discovery enriches an existing scanned/manual entry instead of
                # creating a duplicate when Zeb later clones the same repo.
                local_path = str(repo.get("local_path") or "").strip()
                if local_path and existing.get("local_path") != local_path:
                    existing["local_path"] = local_path
                    existing["source"] = "local-clone"
                    _atomic_write(self._path, json.dumps(items, indent=2))
                return existing
            items.append(entry)
            _atomic_write(self._path, json.dumps(items, indent=2))
        except Exception:
            pass
        return entry

    @staticmethod
    def _remote_identity(repo_dir: Path) -> tuple[str, str]:
        """Return ``(full_name, url)`` from a checkout's origin config."""
        config_path = repo_dir / ".git" / "config"
        try:
            text = config_path.read_text(encoding="utf-8", errors="replace")
            match = re.search(
                r'\[remote\s+"origin"\][^\[]*?\burl\s*=\s*(\S+)',
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            remote = match.group(1).strip() if match else ""
        except Exception:
            remote = ""
        if remote:
            cleaned = remote.removesuffix(".git").rstrip("/")
            if cleaned.startswith("git@") and ":" in cleaned:
                cleaned = cleaned.split(":", 1)[1]
            elif "://" in cleaned:
                cleaned = cleaned.split("://", 1)[1].split("/", 1)[-1]
            full_name = "/".join(cleaned.split("/")[-2:])
            if "/" in full_name:
                return full_name, f"https://github.com/{full_name}"
        return f"local/{repo_dir.name}", repo_dir.as_uri()

    @staticmethod
    def _clone_roots() -> list[Path]:
        """Small, bounded roots where Zeb normally creates checkouts."""
        raw = os.environ.get("ZEB_REPO_ROOTS", "").strip()
        if raw:
            candidates = [Path(value).expanduser() for value in raw.split(os.pathsep)]
        else:
            try:
                import zeb_constants

                zeb_home = Path(zeb_constants.get_zeb_home())
            except Exception:
                zeb_home = Path.home() / ".zeb"
            candidates = [
                Path("/opt"),
                Path("/var/lib/zeb"),
                zeb_home / "repos",
                zeb_home / "workspace",
                Path.home() / "repos",
                Path.home() / "workspace",
                Path(os.environ.get("ZEB_WORKSPACE_ROOT", "")).expanduser()
                if os.environ.get("ZEB_WORKSPACE_ROOT")
                else None,
            ]
        roots: list[Path] = []
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                resolved = candidate.resolve()
            except Exception:
                continue
            if resolved.is_dir() and resolved not in roots:
                roots.append(resolved)
        return roots

    def sync_local_clones(self, *, force: bool = False) -> int:
        """Discover local Git clones and persist them for dashboard navigation.

        The scan is intentionally shallow and throttled. It catches the places
        Zeb uses for checkouts without walking model caches or the whole VPS.
        """
        now = time.monotonic()
        with self._discovery_lock:
            if not force and now - type(self)._last_discovery < 30:
                return 0
            type(self)._last_discovery = now
            added = 0
            ignored = {"node_modules", ".venv", "venv", "models", "cache", ".cache"}
            for root in self._clone_roots():
                root_depth = len(root.parts)
                for current, dirs, _files in os.walk(root):
                    current_path = Path(current)
                    depth = len(current_path.parts) - root_depth
                    dirs[:] = [d for d in dirs if d not in ignored]
                    if ".git" in dirs:
                        dirs.remove(".git")
                        full_name, url = self._remote_identity(current_path)
                        before = len(self._load())
                        self.add(
                            {
                                "full_name": full_name,
                                "url": url,
                                "description": f"Local checkout at {current_path}",
                                "source": "local-clone",
                                "local_path": str(current_path),
                            }
                        )
                        if len(self._load()) > before:
                            added += 1
                        dirs[:] = []
                        continue
                    if depth >= 3:
                        dirs[:] = []
            return added

    def list(self, query: str = "") -> list:
        try:
            items = [e for e in self._load() if isinstance(e, dict)]
            for e in items:
                # Legacy entries predate the enabled flag — default them on.
                e.setdefault("enabled", True)
            q = str(query or "").strip().lower()
            if q:
                items = [
                    e
                    for e in items
                    if q in str(e.get("full_name", "")).lower()
                    or q in str(e.get("description", "")).lower()
                    or q in str(e.get("language", "")).lower()
                ]
            items.sort(key=lambda e: e.get("added_at") or 0, reverse=True)
            return items
        except Exception:
            return []

    def set_enabled(self, id: str, enabled: bool) -> dict | None:
        """Flip a repo's enabled flag. Returns the updated entry, or None."""
        try:
            items = self._load()
            updated = None
            for e in items:
                if e.get("id") == id:
                    e["enabled"] = bool(enabled)
                    updated = e
                    break
            if updated is None:
                return None
            _atomic_write(self._path, json.dumps(items, indent=2))
            return updated
        except Exception:
            return None

    def delete(self, id: str) -> bool:
        try:
            items = self._load()
            remaining = [e for e in items if e.get("id") != id]
            if len(remaining) == len(items):
                return False
            return _atomic_write(self._path, json.dumps(remaining, indent=2))
        except Exception:
            return False


class DashboardStateStore:
    """Live, Zeb-writable dashboard state under ``chat/dashboard_state.json``.

    This is how Zeb reshapes its own face in real time. Zeb (or the agent on
    its behalf) writes fields here — a custom brand label, an accent colour, a
    pinned note/banner — and the running dashboard polls this state and applies
    the changes within seconds, while the user watches. It's part of the
    unified being: the dashboard isn't a fixed shell around Zeb, it's a surface
    Zeb can restyle from the inside.

    Deliberately a small, safe allowlist of presentational fields — Zeb can
    restyle and annotate its dashboard, not inject arbitrary markup.
    """

    _ALLOWED = ("brand", "accent", "pinned_note", "tagline")

    def __init__(self, base_dir: Path | None = None) -> None:
        self._path = (Path(base_dir) if base_dir else _chat_dir()) / "dashboard_state.json"

    def get(self) -> dict:
        data = _read_json(self._path, {})
        out = data if isinstance(data, dict) else {}
        out.setdefault("updated_at", 0)
        return out

    def update(self, patch: dict) -> dict:
        """Merge an allowlisted patch into the live dashboard state."""
        try:
            current = self.get()
            for key in self._ALLOWED:
                if key in (patch or {}):
                    val = patch[key]
                    current[key] = str(val)[:400] if val is not None else ""
            current["updated_at"] = time.time()
            _atomic_write(self._path, json.dumps(current, indent=2))
            return current
        except Exception:
            return self.get()


class AgentStore:
    """Registry of Zeb's sub-agents and the dashboards Zeb builds for them.

    This is the honest core of the "self-wiring top-bar buttons" feature. The
    dashboard shows fixed buttons (Quant Bot, Socials Agent, Jew). When
    Zeb — running on the VPS — builds one of these agents and stands up a
    dashboard for it, Zeb calls ``POST /api/agents/<id>`` with the dashboard URL
    and a status string. The running dashboard polls ``GET /api/agents`` and
    lights up the matching button, embedding the dashboard, with NO redeploy.

    Nothing here builds an agent or a dashboard by itself — it is the wiring
    surface that lets Zeb register what it has built. Each record is a small
    allowlisted dict so a registration can't inject arbitrary state.
    """

    _ALLOWED = ("label", "dashboard_url", "status")
    # The three seed agents the top bar ships with. Zeb can register more ids.
    _SEED = {
        "quant": "Qompot",
        "socials": "Socials Agent",
        "jewelry": "Jew",
    }

    def __init__(self, base_dir: Path | None = None) -> None:
        self._path = (Path(base_dir) if base_dir else _chat_dir()) / "agents.json"

    def _load(self) -> dict:
        data = _read_json(self._path, {})
        return data if isinstance(data, dict) else {}

    def list(self) -> list[dict]:
        """Return every known agent, seeding the three defaults if unset."""
        stored = self._load()
        out = []
        ids = list(self._SEED.keys()) + [k for k in stored if k not in self._SEED]
        for aid in ids:
            rec = dict(stored.get(aid, {}) or {})
            rec["id"] = aid
            rec.setdefault("label", self._SEED.get(aid, aid.title()))
            rec.setdefault("dashboard_url", "")
            rec.setdefault("status", "not started")
            if aid == "quant" and not str(rec.get("dashboard_url") or "").strip():
                rec["dashboard_url"] = "/agent-dashboards/quant/"
                rec["status"] = "starter dashboard ready"
            rec.setdefault("updated_at", 0)
            out.append(rec)
        return out

    def register(self, aid: str, patch: dict) -> dict:
        """Merge an allowlisted patch for agent ``aid`` (create if new)."""
        try:
            aid = str(aid or "").strip().lower()
            if not aid:
                return {}
            stored = self._load()
            rec = dict(stored.get(aid, {}) or {})
            for key in self._ALLOWED:
                if key in (patch or {}):
                    val = patch[key]
                    rec[key] = str(val)[:500] if val is not None else ""
            rec["updated_at"] = time.time()
            stored[aid] = rec
            _atomic_write(self._path, json.dumps(stored, indent=2))
            rec = dict(rec)
            rec["id"] = aid
            return rec
        except Exception:
            return {}


class SharedContextStore:
    """One shared conversation log across every session, model and provider.

    This is the honest core of "unified cross-provider knowledge". There is no
    per-provider silo: every chat turn — whichever session or provider produced
    it — is appended here, and any session or autonomy module can read the most
    recent shared context back. It is a single JSON-backed rolling log (capped),
    not literal telepathy between stateless model calls: the shared memory IS
    this store, and reading it is what lets one Zeb pick up what another said.
    """

    _CAP = 500  # keep the last N turns; older ones roll off
    _thread_lock = threading.RLock()

    def __init__(self, base_dir: Path | None = None) -> None:
        self._path = (Path(base_dir) if base_dir else _chat_dir()) / "shared_context.json"

    def recent(self, limit: int = 50) -> list[dict]:
        data = _read_json(self._path, [])
        if not isinstance(data, list):
            return []
        limit = max(1, min(int(limit or 50), self._CAP))
        return data[-limit:]

    def append(
        self,
        role: str,
        content: str,
        session: str | None = None,
        provider: str | None = None,
    ) -> bool:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self._path.with_suffix(".lock")
            with self._thread_lock:
                with open(lock_path, "a+", encoding="utf-8") as lock:
                    if fcntl is not None:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    try:
                        data = _read_json(self._path, [])
                        if not isinstance(data, list):
                            data = []
                        entry = {
                            "role": str(role or ""),
                            "content": str(content or "")[:8000],
                            "session": str(session or ""),
                            "provider": str(provider or "local"),
                            "ts": time.time(),
                        }
                        data.append(entry)
                        if len(data) > self._CAP:
                            data = data[-self._CAP :]
                        return _atomic_write(self._path, json.dumps(data, indent=2))
                    finally:
                        if fcntl is not None:
                            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
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
