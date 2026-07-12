"""API key resolution, verification, and logging for Zeb Chat.

The chat server is protected by a single shared API key. It is resolved from
(in order): the ``ZEB_CHAT_API_KEY`` environment variable, a persisted file
under the Zeb home directory, or a freshly generated token that is written to
that file. The key is logged prominently at startup so it is easy to find in
Docker logs.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from pathlib import Path

logger = logging.getLogger("zeb_chat")

_ENV_VAR = "ZEB_CHAT_API_KEY"


def _default_zeb_home() -> Path:
    """Resolve the Zeb home directory, falling back to ``~/.zeb``."""
    try:
        import zeb_constants

        return Path(zeb_constants.get_zeb_home())
    except Exception:
        return Path.home() / ".zeb"


def resolve_or_create_api_key(zeb_home=None) -> tuple[str, str]:
    """Resolve the chat API key, generating and persisting one if needed.

    Resolution order:
      1. ``ZEB_CHAT_API_KEY`` env var (if non-empty)      → source "env"
      2. ``<zeb_home>/chat/api_key`` file (if non-empty)  → source "file"
      3. else generate a new token, write it 0600         → source "generated"

    Fails open: if writing the generated key fails, the key is still returned.

    Returns:
        A ``(key, source)`` tuple where source is "env" | "file" | "generated".
    """
    import os

    env_key = os.environ.get(_ENV_VAR, "")
    if env_key and env_key.strip():
        return env_key.strip(), "env"

    home = Path(zeb_home) if zeb_home is not None else _default_zeb_home()
    key_path = home / "chat" / "api_key"

    try:
        if key_path.exists():
            existing = key_path.read_text(encoding="utf-8").strip()
            if existing:
                return existing, "file"
    except Exception:
        # Unreadable file — fall through to generating a new one.
        pass

    generated = secrets.token_urlsafe(24)
    try:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(generated + "\n", encoding="utf-8")
        try:
            key_path.chmod(0o600)
        except Exception:
            pass
    except Exception:
        # Fail open — return the generated key even if it could not be saved.
        logger.warning("Could not persist chat API key to %s", key_path)

    return generated, "generated"


def verify_key(candidate: str, expected: str) -> bool:
    """Constant-time comparison of a candidate key against the expected key.

    Returns False if either value is falsy, otherwise compares with
    ``hmac.compare_digest`` to avoid timing side channels.
    """
    if not candidate or not expected:
        return False
    return hmac.compare_digest(str(candidate), str(expected))


def chat_api_key_path(zeb_home=None) -> Path:
    """Location of the persisted chat API key file."""
    home = Path(zeb_home) if zeb_home is not None else _default_zeb_home()
    return home / "chat" / "api_key"


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"}


def log_api_key_banner(
    key: str, host: str, port: int, *, source: str = "generated"
) -> None:
    """Log a startup banner — secure by default.

    The raw key is only printed when it was just *generated* (first boot, so
    there is no other way to learn it) or when the operator explicitly opts in
    with ``ZEB_CHAT_LOG_KEY=1``. Otherwise the banner shows only a short
    fingerprint plus the on-disk path, so restarts don't keep re-emitting a
    live host credential into ``docker logs``/journald/log shippers. When the
    server binds a non-loopback interface, a loud exposure warning is added.
    """
    import hashlib
    import os

    url = f"http://{host}:{port}"
    show_key = source == "generated" or _truthy(os.environ.get("ZEB_CHAT_LOG_KEY"))
    fingerprint = hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:12]

    lines = ["", "=" * 68, "  ZEB CHAT", "-" * 68]
    if show_key:
        lines += [f"  ZEB CHAT API KEY: {key}", ""]
        if source == "generated":
            lines.append(f"  (saved to {chat_api_key_path()} — shown once)")
    else:
        lines += [
            f"  API key fingerprint: sha256:{fingerprint}",
            f"  Retrieve it with:  cat {chat_api_key_path()}",
            "  (set ZEB_CHAT_LOG_KEY=1 to print the key here instead)",
        ]
    lines += ["", f"  Open {url} and paste your key to start chatting."]

    if host not in _LOOPBACK_HOSTS:
        lines += [
            "-" * 68,
            "  ⚠ SECURITY: bound to a non-loopback interface — the dashboard is",
            "    reachable from the network with FULL file read/write access.",
            "    Put it behind a firewall/VPN/TLS, or set ZEB_CHAT_HOST=127.0.0.1.",
        ]
    lines += ["=" * 68, ""]

    banner = "\n".join(lines)
    try:
        print(banner, flush=True)
    except Exception:
        pass
    for line in lines:
        logger.info(line)


def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")
