"""Zeb Chat — a lightweight, self-contained chat-only web server for ZebOS.

Separate from the full dashboard in ``zeb_cli/web_server.py``, this package
serves a clean, Hermes-style chat UI: the user opens the page, pastes an API
key, and chats. Each turn runs the full Zeb agent with the same tools and
permissions as the CLI chat agent.

Public entry points:
    - ``create_app()`` — build the FastAPI application.
    - ``run_server(host, port)`` — build the app, log the key, run uvicorn.
"""

from __future__ import annotations

from zeb_chat.server import create_app, run_server

__all__ = ["create_app", "run_server"]
