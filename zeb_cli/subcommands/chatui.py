"""``zeb chatui`` — launch the clean chat-only web UI (zeb_chat/).

Distinct from ``zeb dashboard`` (the full multi-panel management UI): this is
a minimal, key-gated, chat-only surface — the "paste your key and chat like
standard Hermes" experience served on port 8000 by default. It's what the
Docker container exposes for a no-terminal, chat-only deployment.
"""

from __future__ import annotations

from typing import Callable


def build_chatui_parser(subparsers, *, cmd_chatui: Callable) -> None:
    p = subparsers.add_parser(
        "chatui",
        help="Start the clean chat-only web UI (key-gated, port 8000)",
        description=(
            "Launch the ZebOS chat-only web interface. Generates/loads an API "
            "key, prints it to the logs, and serves a minimal chat UI. Open the "
            "URL, paste the key, and chat — full agent access, no terminal."
        ),
    )
    p.add_argument("--host", default="0.0.0.0", help="Bind host (default 0.0.0.0)")
    p.add_argument("--port", type=int, default=8000, help="Bind port (default 8000)")
    p.set_defaults(func=cmd_chatui)
