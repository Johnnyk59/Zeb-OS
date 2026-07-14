"""``python -m zeb_chat`` — run the Zeb dashboard/chat server.

Host and port come from the environment so the same entrypoint works under
Docker (s6) and bare-metal (systemd):

    ZEB_DASHBOARD_HOST   default 0.0.0.0
    ZEB_DASHBOARD_PORT   default 9119
"""

from __future__ import annotations

import os


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except Exception:
        return default


def main() -> None:
    from zeb_chat.server import run_server

    host = os.environ.get("ZEB_DASHBOARD_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = _int_env("ZEB_DASHBOARD_PORT", 9119)
    run_server(host=host, port=port)


if __name__ == "__main__":
    main()
