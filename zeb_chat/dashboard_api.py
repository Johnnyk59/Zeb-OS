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

from fastapi import APIRouter, HTTPException, Request

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
    require_key(request)
    current = ""
    available: list[str] = []
    try:
        from zeb_cli import config as _cfg

        cfg = _cfg.load_config() or {}
        model_cfg = cfg.get("model")
        if isinstance(model_cfg, dict):
            current = str(model_cfg.get("default") or model_cfg.get("model") or "")
        elif isinstance(model_cfg, str):
            current = model_cfg
    except Exception:
        current = ""
    try:
        from providers import list_providers

        available = [getattr(p, "name", "") for p in list_providers() if getattr(p, "name", "")]
    except Exception:
        available = []
    if not available and current:
        available = [current]
    return {"current": current, "available": available}


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
    require_key(request)
    try:
        from tools import skills_tool

        raw = skills_tool._find_all_skills(skip_disabled=True) or []
        out = []
        for s in raw:
            if not isinstance(s, dict):
                continue
            out.append(
                {
                    "name": s.get("name"),
                    "description": s.get("description", ""),
                    "category": s.get("category", ""),
                }
            )
        return {"skills": out}
    except Exception as exc:
        return {"skills": [], "error": str(exc)}


# --------------------------------------------------------------------------
# Plugins
# --------------------------------------------------------------------------
@router.get("/api/plugins")
def plugins(request: Request):
    require_key(request)
    out = []
    try:
        import glob as _glob

        import yaml as _yaml

        patterns = ["plugins/*/plugin.yaml", "plugins/model-providers/*/plugin.yaml"]
        seen = set()
        for pattern in patterns:
            for manifest in _glob.glob(pattern):
                if manifest in seen:
                    continue
                seen.add(manifest)
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
