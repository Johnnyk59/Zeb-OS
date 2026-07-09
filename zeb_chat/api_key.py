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


def log_api_key_banner(key: str, host: str, port: int) -> None:
    """Log a prominent, boxed banner with the API key and connection URL.

    Uses both ``print()`` and ``logger.info`` so the key is visible regardless
    of logging configuration (e.g. in Docker logs).
    """
    url = f"http://{host}:{port}"
    lines = [
        "",
        "=" * 68,
        "  ZEB CHAT",
        "-" * 68,
        f"  ZEB CHAT API KEY: {key}",
        "",
        f"  Open {url} and paste this key to start chatting.",
        "=" * 68,
        "",
    ]
    banner = "\n".join(lines)
    try:
        print(banner, flush=True)
    except Exception:
        pass
    for line in lines:
        logger.info(line)
