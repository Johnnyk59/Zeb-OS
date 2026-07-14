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
# Shared cross-provider context (one unified memory across all sessions)
# --------------------------------------------------------------------------
@router.get("/api/context")
def shared_context(request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import SharedContextStore

        limit = 50
        try:
            limit = int(request.query_params.get("limit", "50"))
        except Exception:
            pass
        return {"context": SharedContextStore().recent(limit)}
    except Exception as exc:  # pragma: no cover - fail-open
        return {"context": [], "error": str(exc)}


# --------------------------------------------------------------------------
# Agents (top-bar buttons + self-registered dashboards)
# --------------------------------------------------------------------------
@router.get("/api/agents")
def list_agents(request: Request):
    require_key(request)
    try:
        from zeb_chat.stores import AgentStore

        return {"agents": AgentStore().list()}
    except Exception as exc:  # pragma: no cover - fail-open
        return {"agents": [], "error": str(exc)}


@router.post("/api/agents/{aid}")
async def register_agent(aid: str, request: Request):
    """Zeb registers/updates an agent's dashboard URL + status at runtime.

    Body: {"dashboard_url": "...", "status": "...", "label": "..."} — this is
    how Zeb wires a dashboard it built to a top-bar button without a redeploy.
    """
    require_key(request)
    try:
        from zeb_chat.stores import AgentStore

        body = await _json_body(request)
        return {"ok": True, "agent": AgentStore().register(aid, body)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------------
# Files (full workspace access)
# --------------------------------------------------------------------------
def _default_files_root() -> str:
    """Directory the Files tab opens at when no path is supplied.

    Prefer ``/opt`` (the tidy top of a Docker deployment tree) so the browser
    lands on a clean, shallow view rather than deep inside ``/opt/zeb``. Fall
    back to the current working directory on hosts without ``/opt`` (local
    dev, macOS, Windows).
    """
    for candidate in ("/opt",):
        if os.path.isdir(candidate):
            return candidate
    return os.getcwd()


def _files_jail_root() -> str | None:
    """Optional confinement root for all file endpoints (``ZEB_CHAT_FILES_ROOT``).

    Off by default so the dashboard keeps its intended full-workspace browser.
    When set, every file path — list, read, and write — is resolved with
    symlinks/`..` collapsed and rejected unless it stays under this root.
    """
    root = os.environ.get("ZEB_CHAT_FILES_ROOT", "").strip()
    if not root:
        return None
    try:
        return os.path.realpath(root)
    except Exception:
        return None


def _enforce_jail(target: str) -> None:
    """Raise 403 if a jail is configured and ``target`` escapes it."""
    root = _files_jail_root()
    if root is None:
        return
    real = os.path.realpath(target)
    if real != root and not real.startswith(root + os.sep):
        raise HTTPException(status_code=403, detail="path is outside the allowed root")


# Realpath prefixes and basenames that a write must never touch, even with a
# valid key. This is defense-in-depth: the read/browse surface stays open (a
# personal server file manager), but WRITES to credentials, shell startup
# files, cron/systemd, and the OS tree are refused so a leaked key cannot be
# escalated into code execution by planting a payload.
_WRITE_DENY_PREFIXES = (
    "/etc", "/boot", "/sys", "/proc", "/dev", "/run/systemd",
    "/var/spool/cron", "/usr/lib/systemd", "/lib/systemd",
)
_WRITE_DENY_BASENAMES = {
    ".bashrc", ".bash_profile", ".bash_login", ".profile", ".zshrc",
    ".zprofile", ".zshenv", ".zlogin", "authorized_keys", "known_hosts",
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "sudoers", "crontab",
    ".netrc", ".pgpass",
}
# Path components that flag a sensitive directory regardless of depth.
_WRITE_DENY_COMPONENTS = {".ssh", ".gnupg"}


def _reject_dangerous_write(target: str) -> None:
    """Raise 403 if ``target`` resolves to a write that could grant code exec.

    Blocks: the OS tree (/etc, /boot, systemd, cron), any ``.ssh``/``.gnupg``
    directory, shell startup files, SSH keys, and Zeb's own secret files
    (``.env`` and the chat api_key). Uses realpath so symlinks and ``..`` can't
    dodge the check.
    """
    real = os.path.realpath(target)
    base = os.path.basename(real)
    parts = set(real.split(os.sep))

    if base in _WRITE_DENY_BASENAMES:
        raise HTTPException(status_code=403, detail=f"refusing to write protected file: {base}")
    if parts & _WRITE_DENY_COMPONENTS:
        raise HTTPException(status_code=403, detail="refusing to write inside a credentials directory")
    for pfx in _WRITE_DENY_PREFIXES:
        if real == pfx or real.startswith(pfx + os.sep):
            raise HTTPException(status_code=403, detail=f"refusing to write under {pfx}")
    if ".git" + os.sep + "hooks" in real:
        raise HTTPException(status_code=403, detail="refusing to write a git hook")
    # Zeb's own secrets: the .env and the chat api_key file.
    try:
        from zeb_cli.config import get_env_path

        if real == os.path.realpath(str(get_env_path())):
            raise HTTPException(status_code=403, detail="refusing to overwrite Zeb's .env")
    except HTTPException:
        raise
    except Exception:
        pass
    if base == "api_key" and (os.sep + "chat" + os.sep) in real:
        raise HTTPException(status_code=403, detail="refusing to overwrite the chat api_key")


@router.get("/api/files")
def list_files(request: Request, path: str | None = None):
    require_key(request)
    try:
        target = os.path.abspath(path or _default_files_root())
        _enforce_jail(target)
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
    except HTTPException:
        raise
    except Exception as exc:
        return {"path": path or "", "parent": "", "entries": [], "error": str(exc)}


@router.get("/api/files/read")
def read_file(request: Request, path: str | None = None):
    require_key(request)
    try:
        if not path:
            return {"path": "", "content": "", "truncated": False, "error": "path required"}
        target = os.path.abspath(path)
        _enforce_jail(target)
        with open(target, "rb") as fh:
            raw = fh.read(200_000 + 1)
        if b"\x00" in raw:
            return {"path": target, "binary": True, "content": "", "truncated": False}
        truncated = len(raw) > 200_000
        raw = raw[:200_000]
        content = raw.decode("utf-8", errors="replace")
        return {"path": target, "content": content, "truncated": truncated}
    except HTTPException:
        raise
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
        # Defense in depth: refuse writes that could plant a code-exec payload,
        # and honor the optional workspace jail.
        _enforce_jail(target)
        _reject_dangerous_write(target)
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
    # The always-on local backbone. It stays available as a background option,
    # but it is NO LONGER the default when a provider is connected: provider
    # models answer chat for speed/quality, local powers the thinking brain.
    available: list[dict] = [
        {
            "id": "local",
            "name": local_name,
            "provider": "local-model",
            "connected": True,
            "local": True,
            "priority": False,
            "background": True,
        }
    ]

    # Which remote providers are connected (api key in env, or an Anthropic
    # subscription token).
    provider_ids: list[str] = []
    try:
        provider_ids = sorted(
            pid for pid in _connected_provider_ids() if pid != "local-model"
        )
    except Exception:
        provider_ids = []
    try:
        from zeb_cli.config import get_env_value_prefer_dotenv

        if (get_env_value_prefer_dotenv("CLAUDE_CODE_OAUTH_TOKEN") or "").strip():
            if "anthropic" not in provider_ids:
                provider_ids.append("anthropic")
    except Exception:
        pass

    connected = bool(provider_ids)
    groups: list[dict] = []
    default_model = "local"  # falls back to local only when no provider connected

    for pid in provider_ids:
        try:
            pmodels = _provider_models(pid)
            pdefault = _provider_default_model(pid) or (pmodels[0] if pmodels else "")
            disp = _provider_display_name(pid)
            if pmodels:
                for m in pmodels:
                    available.append(
                        {
                            "id": f"{pid}/{m}",
                            "name": m,
                            "provider": pid,
                            "provider_name": disp,
                            "model": m,
                            "connected": True,
                            "local": False,
                            "priority": False,
                        }
                    )
            else:
                available.append(
                    {
                        "id": pid,
                        "name": disp,
                        "provider": pid,
                        "provider_name": disp,
                        "model": pdefault,
                        "connected": True,
                        "local": False,
                        "priority": False,
                    }
                )
            groups.append(
                {"provider": pid, "name": disp, "models": pmodels, "default": pdefault}
            )
            # The first connected provider's default becomes the chat default.
            if default_model == "local":
                default_model = f"{pid}/{pdefault}" if pdefault else pid
        except Exception:
            continue

    return {
        "current": default_model,
        "default": default_model,
        "available": available,
        "groups": groups,
        "connected": connected,
        "local_available": True,
    }


def _human_ctx(n: int) -> str:
    """Render a context-window token count as a compact label (e.g. 65536 -> '64K')."""
    try:
        n = int(n)
    except Exception:
        return str(n)
    if n <= 0:
        return "unknown"
    if n % 1024 == 0 and n >= 1024:
        k = n // 1024
        if k % 1024 == 0:
            return f"{k // 1024}M tokens"
        return f"{k}K tokens"
    if n >= 1000:
        return f"{n // 1000}K tokens"
    return f"{n} tokens"


def build_model_info() -> dict:
    """Describe the model Zeb is actually running on, for /status and self-awareness.

    Reports the human model name, the real context-window size, and the config
    file path — the facts a user (or Zeb itself) needs to answer "what model
    are you and how are you configured?" accurately, instead of leaking Python
    environment details. Fail-open: every field degrades independently.
    """
    info: dict = {
        "name": "Zeb Local",
        "backbone": "",
        "provider": "local-model",
        "context_window": 0,
        "context_window_human": "unknown",
        "quant": "",
        "repo_id": "",
        "config_path": "",
        "weights_path": "",
        "weights_ready": False,
        "loaded": False,
        "remote_connected": False,
        "remote_providers": [],
    }

    cfg = {}
    try:
        from zeb_cli.config import get_config_path, load_config

        cfg = load_config() or {}
        try:
            info["config_path"] = str(get_config_path())
        except Exception:
            pass
    except Exception:
        cfg = {}

    try:
        from agent.local_model_manager import (
            DEFAULT_LOCAL_MODEL_CTX,
            get_local_model_path,
            local_model_display_name,
            resolved_n_ctx,
            resolved_repo_quant,
        )

        info["backbone"] = local_model_display_name(cfg)
        info["name"] = "Zeb Local · " + info["backbone"]
        repo, quant = resolved_repo_quant(cfg)
        info["repo_id"] = repo
        info["quant"] = quant
        try:
            ctx = int(resolved_n_ctx(cfg))
        except Exception:
            ctx = int(DEFAULT_LOCAL_MODEL_CTX)
        info["context_window"] = ctx
        info["context_window_human"] = _human_ctx(ctx)
        p = get_local_model_path(cfg)
        if p is not None:
            info["weights_ready"] = True
            info["weights_path"] = str(p)
    except Exception:
        pass

    try:
        from agent.llama_cpp_adapter import is_model_loaded

        info["loaded"] = bool(is_model_loaded())
    except Exception:
        pass

    try:
        connected_ids = _connected_provider_ids()
        remotes = sorted(pid for pid in connected_ids if pid != "local-model")
        info["remote_providers"] = remotes
        info["remote_connected"] = bool(remotes)
    except Exception:
        pass

    return info


@router.get("/api/modelinfo")
def model_info(request: Request):
    """Live self-description of the active model (name, context window, config path)."""
    require_key(request)
    try:
        return build_model_info()
    except Exception as exc:  # pragma: no cover - fail-open
        return {"name": "Zeb Local", "error": str(exc)}


# --------------------------------------------------------------------------
# Anthropic subscription — connect via OAuth subscription token
# --------------------------------------------------------------------------
_ANTHROPIC_OAUTH_ENV = "CLAUDE_CODE_OAUTH_TOKEN"


@router.get("/api/anthropic/status")
def anthropic_status(request: Request):
    """Report whether an Anthropic subscription token is connected.

    A connected subscription routes chat through the user's Claude plan
    credits (via ``CLAUDE_CODE_OAUTH_TOKEN``) instead of a metered API key.
    """
    require_key(request)
    connected = False
    masked = ""
    try:
        from zeb_cli.config import get_env_value_prefer_dotenv

        token = (get_env_value_prefer_dotenv(_ANTHROPIC_OAUTH_ENV) or "").strip()
        if token:
            connected = True
            masked = (token[:6] + "…" + token[-4:]) if len(token) > 12 else "connected"
    except Exception as exc:
        return {"connected": False, "error": str(exc)}
    return {"connected": connected, "masked": masked, "env_var": _ANTHROPIC_OAUTH_ENV}


@router.post("/api/anthropic/connect")
async def anthropic_connect(request: Request):
    """Store a Claude subscription OAuth token so chat bills to plan credits.

    The token is produced by ``claude setup-token`` (Claude Code's subscription
    login). We persist it to ``~/.zeb/.env`` as ``CLAUDE_CODE_OAUTH_TOKEN`` —
    the same variable the provider registry already recognizes — so Anthropic
    requests authenticate against the user's subscription rather than a
    pay-as-you-go API key.
    """
    require_key(request)
    body = await _json_body(request)
    token = str(body.get("token", "") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="token required")
    # OAuth subscription tokens are long and start with a recognizable prefix;
    # accept liberally but reject obviously-wrong short values.
    if len(token) < 20:
        raise HTTPException(status_code=400, detail="token looks too short to be valid")
    try:
        from zeb_cli.config import save_env_value

        save_env_value(_ANTHROPIC_OAUTH_ENV, token)
        os.environ[_ANTHROPIC_OAUTH_ENV] = token
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "connected": True}


@router.post("/api/anthropic/disconnect")
def anthropic_disconnect(request: Request):
    """Remove the stored Anthropic subscription token."""
    require_key(request)
    try:
        from zeb_cli.config import save_env_value

        save_env_value(_ANTHROPIC_OAUTH_ENV, "")
        os.environ.pop(_ANTHROPIC_OAUTH_ENV, None)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "connected": False}


# --------------------------------------------------------------------------
# First-run provider onboarding — pick a provider + paste a key
# --------------------------------------------------------------------------
# The ten most common providers offered at first run. `id` matches the runtime
# provider id the chat pipeline resolves; `env` is where the key is persisted so
# _connected_provider_ids() detects it and the chat dropdown lists it.
ONBOARD_PROVIDERS: list[dict] = [
    {"id": "openai", "name": "OpenAI", "env": "OPENAI_API_KEY"},
    {"id": "anthropic", "name": "Anthropic (Claude)", "env": "ANTHROPIC_API_KEY"},
    {"id": "google", "name": "Google (Gemini)", "env": "GEMINI_API_KEY"},
    {"id": "together", "name": "Together AI", "env": "TOGETHER_API_KEY"},
    {"id": "mistral", "name": "Mistral", "env": "MISTRAL_API_KEY"},
    {"id": "groq", "name": "Groq", "env": "GROQ_API_KEY"},
    {"id": "deepseek", "name": "DeepSeek", "env": "DEEPSEEK_API_KEY"},
    {"id": "xai", "name": "xAI (Grok)", "env": "XAI_API_KEY"},
    {"id": "openrouter", "name": "OpenRouter", "env": "OPENROUTER_API_KEY"},
    {"id": "fireworks", "name": "Fireworks AI", "env": "FIREWORKS_API_KEY"},
]
_ONBOARD_ENV_BY_ID = {p["id"]: p["env"] for p in ONBOARD_PROVIDERS}


@router.get("/api/providers")
def list_providers(request: Request):
    """The provider menu shown at first run (id + display name)."""
    require_key(request)
    return {"providers": [{"id": p["id"], "name": p["name"]} for p in ONBOARD_PROVIDERS]}


@router.post("/api/onboard/provider")
async def onboard_provider(request: Request):
    """Persist a first-run provider key so chat can use it for fast responses.

    The local GGUF backbone keeps running in the background (it powers the
    always-on "thinking" brain visualization); this simply sets the provider
    the user-facing chat prefers for speed and quality. The key is saved to the
    provider's standard env var, so the existing connected-provider detection
    and chat runtime pick it up with no further wiring.
    """
    require_key(request)
    body = await _json_body(request)
    provider = str(body.get("provider", "") or "").strip().lower()
    key = str(body.get("key", "") or "").strip()
    if provider not in _ONBOARD_ENV_BY_ID:
        raise HTTPException(status_code=400, detail="unknown provider")
    if not key:
        raise HTTPException(status_code=400, detail="key required")
    env_var = _ONBOARD_ENV_BY_ID[provider]
    try:
        from zeb_cli.config import save_env_value

        save_env_value(env_var, key)
        os.environ[env_var] = key
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    # Warm the model list so the selector/Models tab populate immediately.
    models = _provider_models(provider, force=True)
    return {
        "ok": True,
        "provider": provider,
        "default_model": _provider_default_model(provider),
        "models": models,
    }


# --------------------------------------------------------------------------
# Provider model discovery — detect a key's provider and list its models
# --------------------------------------------------------------------------
import threading as _threading  # noqa: E402
import time as _time  # noqa: E402

_PROVIDER_DISPLAY = {p["id"]: p["name"] for p in ONBOARD_PROVIDERS}

# Base URL + auth style for a live GET .../models. Everything here is
# fail-open: a network/auth failure just falls back to the models.dev catalog
# and then the provider's curated default, never an error.
_PROVIDER_META: dict[str, dict] = {
    "openai": {"base": "https://api.openai.com/v1", "auth": "bearer"},
    "anthropic": {"base": "https://api.anthropic.com/v1", "auth": "anthropic"},
    "google": {"base": "https://generativelanguage.googleapis.com/v1beta", "auth": "google"},
    "together": {"base": "https://api.together.xyz/v1", "auth": "bearer"},
    "mistral": {"base": "https://api.mistral.ai/v1", "auth": "bearer"},
    "groq": {"base": "https://api.groq.com/openai/v1", "auth": "bearer"},
    "deepseek": {"base": "https://api.deepseek.com/v1", "auth": "bearer"},
    "xai": {"base": "https://api.x.ai/v1", "auth": "bearer"},
    "openrouter": {"base": "https://openrouter.ai/api/v1", "auth": "bearer"},
    "fireworks": {"base": "https://api.fireworks.ai/inference/v1", "auth": "bearer"},
}


def _detect_provider_from_key(key: str) -> str:
    """Best-effort provider id from a key's prefix (empty if ambiguous/unknown)."""
    k = (key or "").strip()
    if k.startswith("sk-ant-"):
        return "anthropic"
    if k.startswith("sk-or-"):
        return "openrouter"
    if k.startswith("AIza"):
        return "google"
    if k.startswith("gsk_"):
        return "groq"
    if k.startswith("xai-"):
        return "xai"
    if k.startswith("sk-"):  # openai + several openai-compatible; default to openai
        return "openai"
    return ""


def _provider_display_name(provider: str) -> str:
    return _PROVIDER_DISPLAY.get(provider) or provider.capitalize()


def _provider_key(provider: str) -> str:
    """The stored API key for a provider (checks its env var), or ''."""
    env = _ONBOARD_ENV_BY_ID.get(provider)
    if not env:
        return ""
    try:
        from zeb_cli.config import get_env_value_prefer_dotenv

        return (get_env_value_prefer_dotenv(env) or "").strip()
    except Exception:
        return ""


def _fetch_provider_models_live(provider: str, key: str) -> list[str]:
    """GET the provider's /models with the key. Fail-open → []."""
    meta = _PROVIDER_META.get(provider)
    if not meta or not key:
        return []
    try:
        import httpx

        base = meta["base"].rstrip("/")
        auth = meta["auth"]
        if auth == "anthropic":
            r = httpx.get(
                base + "/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                timeout=6.0,
            )
        elif auth == "google":
            r = httpx.get(base + "/models", params={"key": key}, timeout=6.0)
        else:
            r = httpx.get(base + "/models", headers={"Authorization": "Bearer " + key}, timeout=6.0)
        if r.status_code != 200:
            return []
        data = r.json()
        ids: list[str] = []
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            for m in data["data"]:
                mid = m.get("id") if isinstance(m, dict) else None
                if mid:
                    ids.append(str(mid))
        elif isinstance(data, dict) and isinstance(data.get("models"), list):  # google
            for m in data["models"]:
                nm = (m.get("name", "") if isinstance(m, dict) else "").split("/")[-1]
                if nm:
                    ids.append(nm)
        return ids
    except Exception:
        return []


_models_cache: dict[str, dict] = {}
_models_cache_lock = _threading.Lock()
_MODELS_TTL = 300.0


def _provider_models(provider: str, force: bool = False) -> list[str]:
    """Models for a connected provider: live fetch → models.dev → default.

    Cached for _MODELS_TTL so the frequently-polled /api/models and the chat
    selector don't refetch on every call. Always fail-open.
    """
    now = _time.time()
    if not force:
        with _models_cache_lock:
            ent = _models_cache.get(provider)
            if ent and (now - ent["ts"] < _MODELS_TTL):
                return list(ent["models"])

    models = _fetch_provider_models_live(provider, _provider_key(provider))
    if not models:
        try:
            from agent.models_dev import list_provider_models

            models = list_provider_models(provider) or []
        except Exception:
            models = []
    if not models:
        d = _provider_default_model(provider)
        models = [d] if d else []

    seen: set = set()
    out: list[str] = []
    for m in models:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
        if len(out) >= 40:
            break
    with _models_cache_lock:
        _models_cache[provider] = {"models": out, "ts": now}
    return out


def _provider_default_model(provider: str) -> str:
    """The provider's default model id (curated), or '' if unknown."""
    try:
        from zeb_cli.models import get_default_model_for_provider

        d = (get_default_model_for_provider(provider) or "").strip()
        if d:
            return d
    except Exception:
        pass
    with _models_cache_lock:
        ent = _models_cache.get(provider)
    if ent and ent["models"]:
        return ent["models"][0]
    return ""


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
        from zeb_cli.auth import PROVIDER_REGISTRY
        from zeb_cli.config import get_env_value_prefer_dotenv

        for pid, pconf in PROVIDER_REGISTRY.items():
            for env_var in getattr(pconf, "api_key_env_vars", []) or []:
                if env_var == "CLAUDE_CODE_OAUTH_TOKEN":
                    continue
                if (get_env_value_prefer_dotenv(env_var) or "").strip():
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
    """Store a key and, when it maps to a known provider, connect it live.

    Adding a key here does more than vault it: the provider is detected from
    the key prefix (or an explicit ``provider`` in the body), the key is saved
    to that provider's standard env var so it counts as connected, and its
    model list is fetched and returned. The chat selector and Models tab then
    show the provider and its models immediately.
    """
    require_key(request)
    try:
        from zeb_chat.stores import ApiKeyStore

        body = await _json_body(request)
        key = str(body.get("key", "") or "").strip()
        if not key:
            raise HTTPException(status_code=400, detail="key required")

        provider = str(body.get("provider", "") or "").strip().lower()
        if provider in ("", "auto"):
            provider = _detect_provider_from_key(key)

        stored = ApiKeyStore().add(key, str(body.get("label", "") or ""))
        result = dict(stored) if isinstance(stored, dict) else {"ok": True}

        connected_provider = ""
        models: list[str] = []
        env_var = _ONBOARD_ENV_BY_ID.get(provider)
        if env_var:
            try:
                from zeb_cli.config import save_env_value

                save_env_value(env_var, key)
                os.environ[env_var] = key
                connected_provider = provider
                models = _provider_models(provider, force=True)
            except Exception:
                pass
        result["provider"] = connected_provider
        result["models"] = models
        return result
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
