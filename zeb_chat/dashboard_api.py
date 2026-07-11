"""Dashboard data endpoints for ZebOS, exposed as an ``APIRouter``.

``zeb_chat.server`` mounts this via ``include_router(router)``. Every endpoint
requires the shared API key (Bearer or ``X-API-Key``) and is fail-open: real
work is wrapped in try/except and returns a JSON error object with an empty
payload rather than a 500. Authentication failures still return 401.

Heavy ZebOS modules are imported lazily inside handlers so that importing this
module stays cheap.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger("zeb_chat")

router = APIRouter()


def require_key(request: Request) -> None:
    """Validate the shared API key. Raises HTTPException(401) on mismatch."""
    from zeb_chat.api_key import verify_key

    expected = getattr(request.app.state, "api_key", None)
    auth = request.headers.get("authorization", "")
    candidate = ""
    if auth.lower().startswith("bearer "):
        candidate = auth[7:].strip()
    if not candidate:
        candidate = request.headers.get("x-api-key", "").strip()
    if not verify_key(candidate, expected):
        raise HTTPException(status_code=401, detail="invalid or missing API key")


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------
@router.get("/api/status")
def status(request: Request):
    require_key(request)
    try:
        from zeb_chat import activity

        return activity.snapshot()
    except Exception as exc:  # pragma: no cover - fail-open
        return {"state": "idle", "active_turns": 0, "detail": "", "error": str(exc)}


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------
@router.get("/api/sessions")
def list_sessions(request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import SessionStore

        return {"sessions": SessionStore().list()}
    except Exception as exc:
        return {"sessions": [], "error": str(exc)}


@router.post("/api/sessions")
async def create_session(request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import SessionStore

        body = await _json_body(request)
        return SessionStore().create(title=str(body.get("title", "") or ""))
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/api/sessions/{sid}")
def get_session(sid: str, request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import SessionStore

        session = SessionStore().get(sid)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return session
    except HTTPException:
        raise
    except Exception as exc:
        return {"error": str(exc)}


@router.post("/api/sessions/{sid}/messages")
async def append_message(sid: str, request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import SessionStore

        body = await _json_body(request)
        ok = SessionStore().append(
            sid, str(body.get("role", "") or ""), str(body.get("content", "") or "")
        )
        return {"ok": bool(ok)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.delete("/api/sessions/{sid}")
def delete_session(sid: str, request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import SessionStore

        return {"ok": bool(SessionStore().delete(sid))}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------------
# Files (full workspace access)
# --------------------------------------------------------------------------
@router.get("/api/files")
def list_files(request: Request, path: str | None = None):
    require_key(request)
    try:
        target = os.path.abspath(path or os.getcwd())
        entries = []
        try:
            names = os.listdir(target)
        except Exception as exc:
            return {"path": target, "parent": os.path.dirname(target), "entries": [], "error": str(exc)}
        for name in names[:5000]:
            full = os.path.join(target, name)
            try:
                is_dir = os.path.isdir(full)
                size = os.path.getsize(full) if not is_dir else 0
            except Exception:
                is_dir = False
                size = 0
            entries.append({"name": name, "path": full, "is_dir": is_dir, "size": size})
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        entries = entries[:1000]
        return {"path": target, "parent": os.path.dirname(target), "entries": entries}
    except Exception as exc:
        return {"path": path or "", "parent": "", "entries": [], "error": str(exc)}


@router.get("/api/files/read")
def read_file(request: Request, path: str | None = None):
    require_key(request)
    try:
        if not path:
            return {"path": "", "content": "", "truncated": False, "error": "path required"}
        target = os.path.abspath(path)
        with open(target, "rb") as fh:
            raw = fh.read(200_000 + 1)
        if b"\x00" in raw:
            return {"path": target, "binary": True, "content": "", "truncated": False}
        truncated = len(raw) > 200_000
        raw = raw[:200_000]
        content = raw.decode("utf-8", errors="replace")
        return {"path": target, "content": content, "truncated": truncated}
    except Exception as exc:
        return {"path": path or "", "content": "", "truncated": False, "error": str(exc)}


@router.post("/api/files/write")
async def write_file(request: Request):
    require_key(request)
    try:
        body = await _json_body(request)
        path = str(body.get("path", "") or "")
        content = body.get("content", "")
        if not path:
            raise HTTPException(status_code=400, detail="path required")
        if not isinstance(content, str):
            raise HTTPException(status_code=400, detail="content must be a string")
        target = os.path.abspath(path)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
        return {"ok": True, "path": target}
    except HTTPException:
        raise
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
@router.get("/api/models")
def models(request: Request):
    """List the local backbone (always, as the priority default) + connected remotes.

    Philosophy: Zeb runs on its local GGUF backbone out of the box with no
    keys. That local model is ALWAYS present and is the default/priority
    option in the chat selector. Any API providers the user has actually
    connected are listed after it as optional, faster backups the user can
    pick per-request — they are never the default and never used unless
    explicitly selected.
    """
    require_key(request)
    cfg = {}
    try:
        from zeb_cli import config as _cfg

        cfg = _cfg.load_config() or {}
    except Exception:
        cfg = {}

    # The always-on local backbone, first and default.
    local_name = "Zeb Local"
    try:
        from agent.local_model_manager import local_model_display_name

        local_name = "Zeb Local · " + local_model_display_name(cfg)
    except Exception:
        pass
    available: list[dict] = [
        {
            "id": "local",
            "name": local_name,
            "provider": "local-model",
            "connected": True,
            "local": True,
            "priority": True,
        }
    ]

    # Connected remote providers (optional, user-selectable backups).
    connected = False
    try:
        connected_ids = _connected_provider_ids()
        # local-model is always in that set; the "real remote connected"
        # signal is anything beyond it.
        remotes = sorted(pid for pid in connected_ids if pid != "local-model")
        connected = bool(remotes)
        for pid in remotes:
            available.append(
                {
                    "id": pid,
                    "name": pid,
                    "provider": pid,
                    "connected": True,
                    "local": False,
                    "priority": False,
                }
            )
    except Exception:
        connected = False

    return {
        "current": "local",
        "default": "local",
        "available": available,
        "connected": connected,
    }


# --------------------------------------------------------------------------
# Cron
# --------------------------------------------------------------------------
@router.get("/api/cron")
def cron_jobs(request: Request):
    require_key(request)
    try:
        from cron import jobs as _jobs

        raw = _jobs.list_jobs(include_disabled=True) or []
        trimmed = []
        for j in raw:
            if not isinstance(j, dict):
                continue
            trimmed.append(
                {
                    "id": j.get("id"),
                    "name": j.get("name") or j.get("prompt"),
                    "prompt": j.get("prompt"),
                    "schedule": j.get("schedule_display") or j.get("schedule"),
                    "enabled": j.get("enabled", True),
                }
            )
        return {"jobs": trimmed}
    except Exception as exc:
        return {"jobs": [], "error": str(exc)}


# --------------------------------------------------------------------------
# Skills
# --------------------------------------------------------------------------
@router.get("/api/skills")
def skills(request: Request):
    """List skills grouped into stacks.

    Each skill carries a ``stack`` label; the dashboard renders one collapsible
    stack per label. Skills without a category fall under a default
    ``Core Skills`` stack. A ``stacks`` summary (ordered, with counts) is also
    returned so the client doesn't have to re-derive grouping.
    """
    require_key(request)
    try:
        from tools import skills_tool

        raw = skills_tool._find_all_skills(skip_disabled=True) or []
        out = []
        order: list[str] = []
        counts: dict[str, int] = {}
        for s in raw:
            if not isinstance(s, dict):
                continue
            category = str(s.get("category", "") or "").strip()
            stack = category or "Core Skills"
            out.append(
                {
                    "name": s.get("name"),
                    "description": s.get("description", ""),
                    "category": category,
                    "stack": stack,
                }
            )
            if stack not in counts:
                counts[stack] = 0
                order.append(stack)
            counts[stack] += 1
        # "Core Skills" always leads the list when present.
        if "Core Skills" in order:
            order.remove("Core Skills")
            order.insert(0, "Core Skills")
        stacks = [{"name": name, "count": counts[name]} for name in order]
        return {"skills": out, "stacks": stacks}
    except Exception as exc:
        return {"skills": [], "stacks": [], "error": str(exc)}


def _connected_provider_ids() -> set:
    """Provider directory-ids that are actually connected (have credentials).

    The local GGUF backbone is always-on, so it is always considered
    connected. Everything else must have a real key / active-provider signal.
    """
    ids = {"local-model"}
    try:
        from zeb_cli.auth import get_active_provider

        ap = get_active_provider()
        if ap:
            ids.add(str(ap).strip().lower())
    except Exception:
        pass
    try:
        from zeb_cli.auth import PROVIDER_REGISTRY, get_env_value

        for pid, pconf in PROVIDER_REGISTRY.items():
            for env_var in getattr(pconf, "api_key_env_vars", []) or []:
                if env_var == "CLAUDE_CODE_OAUTH_TOKEN":
                    continue
                if get_env_value(env_var):
                    ids.add(str(pid).strip().lower())
                    break
    except Exception:
        pass
    return ids


# --------------------------------------------------------------------------
# Plugins
# --------------------------------------------------------------------------
@router.get("/api/plugins")
def plugins(request: Request):
    """List installed/active plugins.

    Feature plugins (``plugins/<name>/``) are all shown. Model-provider
    plugins (``plugins/model-providers/<name>/``) are filtered to only those
    that are actually connected — the dashboard should never list ~30 unused
    provider plugins.
    """
    require_key(request)
    out = []
    try:
        import glob as _glob

        import yaml as _yaml

        connected = _connected_provider_ids()
        patterns = ["plugins/*/plugin.yaml", "plugins/model-providers/*/plugin.yaml"]
        seen = set()
        for pattern in patterns:
            is_provider = "model-providers" in pattern
            for manifest in _glob.glob(pattern):
                if manifest in seen:
                    continue
                seen.add(manifest)
                dir_id = os.path.basename(os.path.dirname(manifest)).strip().lower()
                if is_provider and dir_id not in connected:
                    continue  # drop unconnected provider plugins
                try:
                    with open(manifest, "r", encoding="utf-8") as fh:
                        data = _yaml.safe_load(fh) or {}
                except Exception:
                    data = {}
                if not isinstance(data, dict):
                    data = {}
                out.append(
                    {
                        "name": data.get("name") or os.path.basename(os.path.dirname(manifest)),
                        "kind": data.get("kind", ""),
                        "description": data.get("description", ""),
                    }
                )
    except Exception as exc:
        return {"plugins": [], "error": str(exc)}
    return {"plugins": out}


# --------------------------------------------------------------------------
# Zeb Diagnose — offline health check + self-repair (zero AI dependency)
# --------------------------------------------------------------------------
def _run_diagnostics() -> dict:
    """Run the self-healing health checks and shape them for the dashboard.

    Uses ``gateway.self_healing.run_health_checks`` — the exact same checks
    the background monitor and ``zeb doctor`` run. They are pure-Python
    (disk, sqlite, YAML, local-model liveness) and several *self-repair* when
    run (unloading a wedged model, repairing a malformed state.db), so this
    works with no AI provider and no network at all.
    """
    try:
        from gateway.self_healing import run_health_checks

        results = run_health_checks()
        checks = [
            {
                "component": r.component,
                "status": r.status,
                "message": r.message,
                "repaired": bool(r.repaired),
            }
            for r in results
        ]
        counts = {"ok": 0, "degraded": 0, "critical": 0, "repaired": 0}
        for c in checks:
            counts[c["status"]] = counts.get(c["status"], 0) + 1
            if c["repaired"]:
                counts["repaired"] += 1
        overall = (
            "critical"
            if counts["critical"]
            else ("degraded" if counts["degraded"] else "ok")
        )
        return {
            "checks": checks,
            "summary": counts,
            "overall": overall,
            "offline": True,
        }
    except Exception as exc:
        return {
            "checks": [],
            "summary": {},
            "overall": "unknown",
            "offline": True,
            "error": str(exc),
        }


@router.get("/api/diagnose")
def diagnose(request: Request):
    require_key(request)
    return _run_diagnostics()


@router.post("/api/diagnose/repair")
def diagnose_repair(request: Request):
    """Trigger self-healing. Running the checks *is* the repair (they fix what
    they safely can in place), so this returns the post-repair state."""
    require_key(request)
    return _run_diagnostics()


# --------------------------------------------------------------------------
# Local Model Status — live identity + CPU/RAM/bandwidth/activity
# --------------------------------------------------------------------------
@router.get("/api/localmodel")
def local_model(request: Request):
    """Report everything the Local Model Status panel shows, live.

    Model identity + whether weights are on disk / loaded, plus real-time
    CPU and RAM (via psutil), download bandwidth, and a rolling activity
    log. Entirely fail-open — every block degrades independently so a
    missing psutil or an unimportable model stack still returns a useful
    partial snapshot.
    """
    require_key(request)
    out: dict = {
        "name": "",
        "provider": "local-model",
        "loaded": False,
        "ready": False,
        "path": "",
        "size_bytes": 0,
        "ctx": 0,
        "cpu_percent": 0.0,
        "process_cpu_percent": 0.0,
        "ram": {},
        "net": {},
        "download": {},
        "events": [],
        "active": False,
    }

    try:
        from zeb_cli.config import load_config

        cfg = load_config() or {}
    except Exception:
        cfg = {}

    try:
        from agent.local_model_manager import (
            DEFAULT_LOCAL_MODEL_CTX,
            get_local_model_path,
            local_model_display_name,
        )

        out["name"] = local_model_display_name(cfg)
        p = get_local_model_path(cfg)
        if p is not None:
            out["ready"] = True
            out["path"] = str(p)
            try:
                out["size_bytes"] = p.stat().st_size
            except Exception:
                pass
        lm = cfg.get("local_model") if isinstance(cfg.get("local_model"), dict) else {}
        out["ctx"] = int((lm or {}).get("ctx") or DEFAULT_LOCAL_MODEL_CTX)
    except Exception:
        pass

    try:
        from agent.llama_cpp_adapter import is_model_loaded, loaded_model_path

        out["loaded"] = bool(is_model_loaded())
        lp = loaded_model_path()
        if lp and not out["path"]:
            out["path"] = lp
    except Exception:
        pass

    try:
        import psutil

        vm = psutil.virtual_memory()
        out["ram"] = {
            "process_mb": round(psutil.Process().memory_info().rss / 1048576, 1),
            "system_used_mb": round(vm.used / 1048576, 1),
            "system_total_mb": round(vm.total / 1048576, 1),
            "percent": vm.percent,
        }
        # interval=None => non-blocking, measured since the previous call in
        # this long-lived process; the panel polls, so values stay live.
        out["cpu_percent"] = psutil.cpu_percent(interval=None)
        try:
            out["process_cpu_percent"] = psutil.Process().cpu_percent(interval=None)
        except Exception:
            pass
        nio = psutil.net_io_counters()
        out["net"] = {"bytes_sent": nio.bytes_sent, "bytes_recv": nio.bytes_recv}
    except Exception:
        pass

    try:
        from agent import local_model_status

        snap = local_model_status.snapshot()
        out["events"] = snap.get("events", [])
        out["download"] = snap.get("download", {})
    except Exception:
        pass

    out["active"] = bool(out["loaded"] or (out.get("download") or {}).get("active"))
    return out


# --------------------------------------------------------------------------
# Voice — optional offline neural TTS (Piper) with browser fallback
# --------------------------------------------------------------------------
@router.get("/api/voice/status")
def voice_status(request: Request):
    require_key(request)
    try:
        from zeb_chat.voice_agent import status as _voice_status

        return _voice_status()
    except Exception as exc:
        return {"engine": "browser", "offline": True, "detail": str(exc)}


@router.post("/api/voice/speak")
async def voice_speak(request: Request):
    """Synthesize speech with Piper and return WAV audio.

    Returns 204 (no content) when server-side voice isn't available, which
    is the client's signal to fall back to the browser's own speech engine.
    """
    require_key(request)
    body = await _json_body(request)
    text = str(body.get("text", "") or "")
    if not text.strip():
        raise HTTPException(status_code=400, detail="text required")
    audio = None
    try:
        from zeb_chat.voice_agent import synthesize

        audio = synthesize(text)
    except Exception:
        audio = None
    if not audio:
        return Response(status_code=204)
    return Response(content=audio, media_type="audio/wav")


# --------------------------------------------------------------------------
# Identity — first-boot onboarding ("Who am I / Who are you / Mission")
# --------------------------------------------------------------------------
@router.get("/api/identity")
def get_identity(request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import IdentityStore

        return IdentityStore().get()
    except Exception as exc:
        return {
            "who_am_i": "",
            "who_are_you": "",
            "mission": "",
            "onboarded": False,
            "error": str(exc),
        }


@router.post("/api/identity")
async def set_identity(request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import IdentityStore

        body = await _json_body(request)
        return IdentityStore().set(body)
    except Exception as exc:
        return {"onboarded": False, "error": str(exc)}


# --------------------------------------------------------------------------
# GitHub Repos — saved open-source repos + search + scan
# --------------------------------------------------------------------------
@router.get("/api/repos")
def list_repos(request: Request, q: str | None = None):
    require_key(request)
    try:
        from zeb_chat.stores import RepoStore

        return {"repos": RepoStore().list(query=q or "")}
    except Exception as exc:
        return {"repos": [], "error": str(exc)}


@router.post("/api/repos")
async def add_repo(request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import RepoStore

        body = await _json_body(request)
        # Accept either a full repo dict or just a full_name.
        if not body.get("full_name") and body.get("name"):
            body["full_name"] = body["name"]
        if not str(body.get("full_name") or "").strip():
            raise HTTPException(status_code=400, detail="full_name required")
        added = RepoStore().add(body)
        if added is None:
            raise HTTPException(status_code=400, detail="invalid repo")
        return added
    except HTTPException:
        raise
    except Exception as exc:
        return {"error": str(exc)}


@router.delete("/api/repos/{rid}")
def delete_repo(rid: str, request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import RepoStore

        return {"ok": bool(RepoStore().delete(rid))}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/api/repos/scan")
async def scan_repos(request: Request):
    """Describe a need → search GitHub → save matching open-source repos.

    Saves every result into the RepoStore (de-duped) so the found repos show
    up in the saved list immediately, ready for integration.
    """
    require_key(request)
    body = await _json_body(request)
    query = str(body.get("query", "") or body.get("q", "") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    try:
        from zeb_chat.github_scan import scan

        result = scan(query, limit=int(body.get("limit") or 10))
    except Exception as exc:
        return {"results": [], "added": [], "error": str(exc)}

    added = []
    try:
        from zeb_chat.stores import RepoStore

        store = RepoStore()
        for repo in result.get("results", []):
            saved = store.add(repo)
            if saved:
                added.append(saved)
    except Exception:
        pass
    return {
        "results": result.get("results", []),
        "added": added,
        "error": result.get("error", ""),
    }


# --------------------------------------------------------------------------
# Channels
# --------------------------------------------------------------------------
@router.get("/api/channels")
def channels(request: Request):
    require_key(request)
    configured = False
    detail = "not configured"
    try:
        if os.environ.get("TELEGRAM_BOT_TOKEN", "").strip():
            configured = True
            detail = "configured via TELEGRAM_BOT_TOKEN"
        else:
            try:
                from zeb_cli import config as _cfg

                cfg = _cfg.load_config() or {}
                tg = cfg.get("telegram")
                if isinstance(tg, dict) and (
                    tg.get("bot_token") or tg.get("token") or tg.get("api_key")
                ):
                    configured = True
                    detail = "configured via config"
            except Exception:
                pass
    except Exception as exc:
        return {"telegram": {"configured": False, "detail": str(exc)}}
    channel_list: list = []
    try:
        from zeb_chat.stores import ChannelStore

        channel_list = ChannelStore().list()
    except Exception:
        channel_list = []
    return {
        "telegram": {"configured": configured, "detail": detail},
        "channels": channel_list,
    }


@router.post("/api/channels")
async def create_channel(request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import ChannelStore

        body = await _json_body(request)
        name = str(body.get("name", "") or "").strip()
        token = str(body.get("token", "") or "").strip()
        if not name or not token:
            raise HTTPException(status_code=400, detail="name and token required")
        return ChannelStore().add(name, token, str(body.get("kind", "telegram") or "telegram"))
    except HTTPException:
        raise
    except Exception as exc:
        return {"error": str(exc)}


@router.delete("/api/channels/{cid}")
def delete_channel(cid: str, request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import ChannelStore

        return {"ok": bool(ChannelStore().delete(cid))}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------------
# Keys
# --------------------------------------------------------------------------
@router.get("/api/keys")
def list_keys(request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import ApiKeyStore

        return {"keys": ApiKeyStore().list()}
    except Exception as exc:
        return {"keys": [], "error": str(exc)}


@router.post("/api/keys")
async def create_key(request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import ApiKeyStore

        body = await _json_body(request)
        key = str(body.get("key", "") or "").strip()
        if not key:
            raise HTTPException(status_code=400, detail="key required")
        return ApiKeyStore().add(key, str(body.get("label", "") or ""))
    except HTTPException:
        raise
    except Exception as exc:
        return {"error": str(exc)}


@router.delete("/api/keys/{kid}")
def delete_key(kid: str, request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import ApiKeyStore

        return {"ok": bool(ApiKeyStore().delete(kid))}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------------
# Gateway
# --------------------------------------------------------------------------
@router.post("/api/gateway/restart")
def gateway_restart(request: Request):
    require_key(request)
    try:
        import subprocess

        subprocess.Popen(
            ["zeb", "gateway", "restart"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"ok": True, "message": "restart requested"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
