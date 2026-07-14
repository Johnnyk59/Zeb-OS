"""FastAPI app for Zeb Chat — a clean, chat-only web server.

Serves a single-page, Hermes-style chat UI (no terminal, no multi-panel
dashboard) and one JSON endpoint that runs a full Zeb agent turn per message.
Access is gated by a shared API key (see ``zeb_chat.api_key``).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from zeb_chat.api_key import (
    log_api_key_banner,
    resolve_or_create_api_key,
    verify_key,
)

logger = logging.getLogger("zeb_chat")


CHAT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Zeb</title>
<style>
  :root {
    --bg: #f7f7f8;
    --panel: #ffffff;
    --border: #e3e3e8;
    --text: #1f1f23;
    --muted: #6b6b73;
    --user-bg: #2563eb;
    --user-text: #ffffff;
    --assistant-bg: #f0f0f3;
    --assistant-text: #1f1f23;
    --accent: #2563eb;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #17171a;
      --panel: #1f1f23;
      --border: #2e2e34;
      --text: #ececf1;
      --muted: #9a9aa5;
      --user-bg: #2563eb;
      --user-text: #ffffff;
      --assistant-bg: #26262c;
      --assistant-text: #ececf1;
      --accent: #3b82f6;
    }
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 Helvetica, Arial, sans-serif;
    display: flex;
    justify-content: center;
    min-height: 100%;
  }
  .app {
    width: 100%;
    max-width: 760px;
    display: flex;
    flex-direction: column;
    height: 100vh;
  }
  header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  header h1 { font-size: 18px; font-weight: 600; margin: 0; }
  header .change-key {
    font-size: 13px;
    color: var(--muted);
    background: none;
    border: none;
    cursor: pointer;
    text-decoration: underline;
  }
  #transcript {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .bubble {
    max-width: 82%;
    padding: 10px 14px;
    border-radius: 16px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-wrap: break-word;
    font-size: 15px;
  }
  .bubble.user {
    align-self: flex-end;
    background: var(--user-bg);
    color: var(--user-text);
    border-bottom-right-radius: 4px;
  }
  .bubble.assistant {
    align-self: flex-start;
    background: var(--assistant-bg);
    color: var(--assistant-text);
    border-bottom-left-radius: 4px;
  }
  .bubble.typing { color: var(--muted); font-style: italic; }
  .composer {
    display: flex;
    gap: 8px;
    padding: 14px 20px;
    border-top: 1px solid var(--border);
    background: var(--panel);
  }
  .composer textarea {
    flex: 1;
    resize: none;
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 10px 12px;
    font: inherit;
    font-size: 15px;
    background: var(--bg);
    color: var(--text);
    max-height: 160px;
  }
  .composer button {
    border: none;
    border-radius: 12px;
    padding: 0 18px;
    background: var(--accent);
    color: #fff;
    font-weight: 600;
    cursor: pointer;
  }
  .composer button:disabled { opacity: 0.5; cursor: default; }
  .gate {
    position: fixed;
    inset: 0;
    background: var(--bg);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }
  .gate .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 28px;
    width: 100%;
    max-width: 400px;
    text-align: center;
  }
  .gate h2 { margin: 0 0 6px; font-size: 20px; }
  .gate p { margin: 0 0 18px; color: var(--muted); font-size: 14px; }
  .gate input {
    width: 100%;
    padding: 11px 12px;
    border: 1px solid var(--border);
    border-radius: 10px;
    font: inherit;
    font-size: 15px;
    background: var(--bg);
    color: var(--text);
    margin-bottom: 12px;
  }
  .gate button {
    width: 100%;
    padding: 11px;
    border: none;
    border-radius: 10px;
    background: var(--accent);
    color: #fff;
    font-weight: 600;
    font-size: 15px;
    cursor: pointer;
  }
  .gate .err { color: #dc2626; font-size: 13px; min-height: 18px; margin-bottom: 8px; }
  .hidden { display: none !important; }
</style>
</head>
<body>
  <div class="app">
    <header>
      <h1>Zeb</h1>
      <button class="change-key" id="changeKey">change key</button>
    </header>
    <div id="transcript"></div>
    <form class="composer" id="composer">
      <textarea id="input" rows="1" placeholder="Message Zeb..." autocomplete="off"></textarea>
      <button type="submit" id="send">Send</button>
    </form>
  </div>

  <div class="gate" id="gate">
    <div class="card">
      <h2>Enter your API key</h2>
      <p>Paste the Zeb Chat API key to start chatting.</p>
      <div class="err" id="gateErr"></div>
      <input type="password" id="keyInput" placeholder="API key" autocomplete="off" />
      <button id="saveKey">Start chatting</button>
    </div>
  </div>

<script>
(function () {
  var KEY_STORE = "zeb_chat_key";
  var transcript = document.getElementById("transcript");
  var gate = document.getElementById("gate");
  var gateErr = document.getElementById("gateErr");
  var keyInput = document.getElementById("keyInput");
  var input = document.getElementById("input");
  var sendBtn = document.getElementById("send");
  var history = [];

  function getKey() { return localStorage.getItem(KEY_STORE) || ""; }
  function setKey(k) { localStorage.setItem(KEY_STORE, k); }
  function clearKey() { localStorage.removeItem(KEY_STORE); }

  function showGate() { gate.classList.remove("hidden"); keyInput.focus(); }
  function hideGate() { gate.classList.add("hidden"); input.focus(); }

  function addBubble(role, text) {
    var el = document.createElement("div");
    el.className = "bubble " + role;
    el.textContent = text;
    transcript.appendChild(el);
    transcript.scrollTop = transcript.scrollHeight;
    return el;
  }

  document.getElementById("saveKey").addEventListener("click", function () {
    var k = keyInput.value.trim();
    if (!k) { gateErr.textContent = "Please enter a key."; return; }
    setKey(k);
    gateErr.textContent = "";
    hideGate();
  });
  keyInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); document.getElementById("saveKey").click(); }
  });

  document.getElementById("changeKey").addEventListener("click", function () {
    keyInput.value = "";
    showGate();
  });

  input.addEventListener("input", function () {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      document.getElementById("composer").requestSubmit();
    }
  });

  document.getElementById("composer").addEventListener("submit", function (e) {
    e.preventDefault();
    var msg = input.value.trim();
    if (!msg) return;
    var key = getKey();
    if (!key) { showGate(); return; }

    addBubble("user", msg);
    history.push({ role: "user", content: msg });
    input.value = "";
    input.style.height = "auto";
    sendBtn.disabled = true;

    var typing = addBubble("assistant", "…");
    typing.classList.add("typing");

    fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key
      },
      body: JSON.stringify({ message: msg, history: history })
    }).then(function (res) {
      if (res.status === 401) {
        clearKey();
        typing.remove();
        showGate();
        gateErr.textContent = "Invalid API key. Please try again.";
        throw new Error("unauthorized");
      }
      return res.json();
    }).then(function (data) {
      typing.classList.remove("typing");
      var reply = (data && data.reply) || (data && data.error) || "(no response)";
      typing.textContent = reply;
      // Don't push system errors into conversation history — the model
      // reads history as prior dialogue and would parrot the error back
      // as if it were its own earlier advice.
      if (reply.indexOf("[Zeb chat error:") !== 0) {
        history.push({ role: "assistant", content: reply });
      }
      transcript.scrollTop = transcript.scrollHeight;
    }).catch(function () {
      if (typing.parentNode) {
        typing.classList.remove("typing");
        typing.textContent = typing.textContent === "…" ? "(request failed)" : typing.textContent;
      }
    }).finally(function () {
      sendBtn.disabled = false;
      input.focus();
    });
  });

  if (!getKey()) { showGate(); } else { hideGate(); }
})();
</script>
</body>
</html>
"""


def create_app() -> FastAPI:
    """Build and return the Zeb Chat FastAPI application.

    The expected API key is resolved once and stored on ``app.state.api_key``;
    tests may override it by reassigning that attribute.
    """
    app = FastAPI(title="Zeb Chat")

    api_key, source = resolve_or_create_api_key()
    app.state.api_key = api_key
    app.state.api_key_source = source
    logger.info("Zeb Chat API key resolved (source=%s)", source)

    @app.get("/health")
    async def health():
        return {"ok": True}

    # Mount the dashboard data endpoints (sessions, files, models, cron,
    # skills, plugins, channels, api-key vault, gateway restart, status).
    try:
        from zeb_chat.dashboard_api import router as _dashboard_router

        app.include_router(_dashboard_router)
    except Exception as _exc:  # pragma: no cover - never let a bad import kill chat
        logger.warning("dashboard API router not mounted: %s", _exc)

    # Serve the full custom dashboard (zeb_chat/static/dashboard.html) when it
    # exists; fall back to the minimal built-in chat page otherwise. The static
    # file is the from-scratch ZebOS dashboard (20/80 layout, tabs, WebGL brain).
    from pathlib import Path as _Path

    _dashboard_html = _Path(__file__).parent / "static" / "dashboard.html"

    @app.get("/", response_class=HTMLResponse)
    async def index():
        try:
            if _dashboard_html.is_file():
                return HTMLResponse(_dashboard_html.read_text(encoding="utf-8"))
        except Exception as _exc:
            logger.warning("failed to serve dashboard.html, using fallback: %s", _exc)
        return HTMLResponse(CHAT_HTML)

    @app.post("/api/chat")
    async def chat(request: Request):
        expected = getattr(request.app.state, "api_key", None)

        auth = request.headers.get("authorization", "")
        candidate = ""
        if auth.lower().startswith("bearer "):
            candidate = auth[7:].strip()
        if not candidate:
            candidate = request.headers.get("x-api-key", "").strip()

        if not verify_key(candidate, expected):
            return JSONResponse(
                {"error": "invalid or missing API key"}, status_code=401
            )

        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}

        message = body.get("message")
        history = body.get("history")
        # Optional explicit model selection from the chat dropdown. Absent /
        # "local" => the local backbone (the default). Anything else names a
        # connected remote provider to use for THIS request only.
        provider = body.get("provider")
        model = body.get("model")
        provider = provider if isinstance(provider, str) else None
        model = model if isinstance(model, str) else None
        if not isinstance(message, str) or not message.strip():
            return JSONResponse(
                {"error": "message must be a non-empty string"}, status_code=400
            )
        if not isinstance(history, list):
            history = None

        from starlette.concurrency import run_in_threadpool

        from zeb_chat.agent_runner import run_chat_turn

        # Drive the dashboard's 3D brain: mark the agent active for the
        # duration of the turn so GET /api/status reports "processing".
        try:
            from zeb_chat import activity as _activity
        except Exception:
            _activity = None

        if _activity is not None:
            _activity.begin("processing")
        try:
            reply = await run_in_threadpool(
                run_chat_turn, message, history, provider, model
            )
        finally:
            if _activity is not None:
                _activity.end()

        # Feed the one shared cross-provider context log so every session and
        # provider can read back what any of them just said (fail-open).
        try:
            from zeb_chat.stores import SharedContextStore

            _shared = SharedContextStore()
            _sid = body.get("session") if isinstance(body.get("session"), str) else None
            _shared.append("user", message, _sid, provider or "local")
            _shared.append("assistant", reply, _sid, provider or "local")
        except Exception:
            pass
        return {"reply": reply}

    return app


def _prefetch_local_model() -> None:
    """Kick off the local GGUF weight download in the background at boot.

    The backbone is lazy by default (loads on first request), which means
    the very first "yo" pays the multi-GB download before it can answer.
    Starting the download the moment the server boots means the weights are
    usually already on disk (or well underway) by the time anyone types, so
    the first local reply is fast. Fully fail-open and opt-out via
    ``ZEB_LOCAL_MODEL_PREFETCH=0``; the download itself is a no-op once the
    weights are cached, so a restart never re-downloads.
    """
    import os

    if os.environ.get("ZEB_LOCAL_MODEL_PREFETCH", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return

    def _worker() -> None:
        try:
            from zeb_cli.config import load_config

            cfg = load_config()
        except Exception:
            cfg = {}
        try:
            from agent.local_model_manager import ensure_local_model_weights

            ensure_local_model_weights(cfg)
            logger.info("Local model weights ready (prefetched at boot)")
        except Exception as exc:  # noqa: BLE001 - never crash the server
            logger.info("Local model prefetch skipped: %s", exc)

    import threading

    threading.Thread(
        target=_worker, name="local-model-prefetch", daemon=True
    ).start()


def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Build the app, log the API key banner, and run uvicorn."""
    app = create_app()
    log_api_key_banner(
        app.state.api_key,
        host,
        port,
        source=getattr(app.state, "api_key_source", "generated"),
    )

    # Start fetching the local backbone weights now so the first message
    # doesn't have to wait for the whole download.
    _prefetch_local_model()

    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning")
