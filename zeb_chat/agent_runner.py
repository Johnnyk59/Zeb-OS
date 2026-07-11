"""Run a single full-permission Zeb agent turn for the chat server.

Mirrors ``zeb_cli/oneshot.py::_run_agent`` — same config, provider resolution,
toolsets, and ``AIAgent`` construction — so a chat turn has exactly the same
capabilities as a CLI chat turn (complete workspace read/modify access).

All heavy imports are lazy (inside the function) so that importing
``zeb_chat.server`` for tests does not drag in the whole agent stack. A
module-level lock serialises turns because ``AIAgent`` is not concurrency-safe.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger("zeb_chat")

# AIAgent is not concurrency-safe; run at most one turn at a time.
_turn_lock = threading.Lock()


_LOCAL_SELECTORS = ("", "local", "local-model", "zeb-local", "offline")

def run_chat_turn(
    message: str,
    history: list[dict] | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """Run one full Zeb agent turn and return the final response text.

    The **local GGUF backbone is always the default**. A remote API provider
    is used *only* when the caller explicitly selects one (``provider`` set
    to a connected remote via the chat model dropdown). This is deliberate:
    out of the box, and whenever nothing is selected, Zeb answers on the
    local model with zero keys — it never auto-reaches for OpenAI (or any
    other provider) and so can never raise "api_key not set". If an
    explicitly-selected remote fails, we fall back to local rather than
    erroring.

    Args:
        message: The user's message for this turn.
        history: Optional prior conversation history (list of role/content
            dicts) passed through to the agent.
        provider: Optional explicit provider selection from the chat UI
            ("local" / "" => local backbone; anything else => that remote).
        model: Optional explicit model id for the selected remote provider.

    Returns:
        The agent's final response text, or a clear error string on failure.
        Never raises.
    """
    with _turn_lock:
        # Lazy imports — keep the agent stack out of test-time imports.
        from zeb_cli.config import load_config
        from zeb_cli.tools_config import _get_platform_tools

        cfg = load_config()
        toolsets_list = sorted(_get_platform_tools(cfg, "cli"))

        # Teach the agent who it serves and what its mission is (first-boot
        # onboarding), so identity persists across every turn.
        history = _inject_identity(history)

        sel = str(provider or "").strip().lower()
        if sel not in _LOCAL_SELECTORS:
            # Explicit remote selection — try it, fall back to local on any
            # failure (missing key, network, etc.) so the user still gets a
            # reply instead of an error.
            try:
                agent = _build_remote_agent(cfg, toolsets_list, requested=sel, target_model=model)
                result = agent.run_conversation(message, conversation_history=history)
                return result.get("final_response") or ""
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Selected provider %r failed; falling back to local backbone", sel
                )

        # Local GGUF backbone — always available, zero configuration.
        try:
            agent = _build_local_agent(toolsets_list)
            result = agent.run_conversation(
                message,
                conversation_history=history,
            )
            return result.get("final_response") or ""
        except Exception as exc:  # noqa: BLE001
            logger.exception("Local backbone turn failed")
            return f"[Zeb chat error: {exc}]"


def _model_awareness_preamble() -> str:
    """A short, factual note about Zeb's own model configuration.

    Injected so that when a user asks "what model are you running?" or "what's
    your context window?", Zeb answers from its real configuration — the model
    name, context-window size, and config file path — instead of guessing or
    dumping Python/interpreter environment details.
    """
    try:
        from zeb_chat.dashboard_api import build_model_info

        info = build_model_info()
    except Exception:
        return ""
    backbone = info.get("backbone") or info.get("name") or "a local GGUF model"
    ctx_human = info.get("context_window_human") or "unknown"
    cfg_path = info.get("config_path") or "~/.zeb/config.yaml"
    lines = [
        "Your own runtime configuration (report these verbatim when the user "
        "asks what model you are, your context window, or how you are set up — "
        "do NOT describe the Python interpreter, OS, or process environment):",
        f"- Model / backbone: {backbone}",
        f"- Context window: {ctx_human}",
        f"- Provider: {info.get('provider') or 'local-model'}",
        f"- Config file: {cfg_path}",
    ]
    if info.get("weights_path"):
        lines.append(f"- Weights file: {info['weights_path']}")
    if info.get("remote_connected") and info.get("remote_providers"):
        lines.append(
            "- Connected remote providers (optional, only when selected): "
            + ", ".join(info["remote_providers"])
        )
    return "\n".join(lines)


def _inject_identity(history: list[dict] | None) -> list[dict] | None:
    """Prepend Zeb's model-awareness note + learned identity as a leading system message."""
    parts: list[str] = []
    awareness = _model_awareness_preamble()
    if awareness:
        parts.append(awareness)
    try:
        from zeb_chat.stores import IdentityStore

        identity = IdentityStore().system_preamble()
    except Exception:
        identity = ""
    if identity:
        parts.append(identity)
    preamble = "\n\n".join(parts).strip()
    if not preamble:
        return history
    sys_msg = {"role": "system", "content": preamble}
    if isinstance(history, list):
        # Don't double-inject if it's already the leading system message.
        if history and history[0].get("role") == "system" and history[0].get("content") == preamble:
            return history
        return [sys_msg] + history
    return [sys_msg]


def _build_remote_agent(
    cfg: dict,
    toolsets_list: list[str],
    *,
    requested: str | None = None,
    target_model: str | None = None,
):
    from zeb_cli.fallback_config import get_fallback_chain
    from zeb_cli.runtime_provider import resolve_runtime_provider
    from run_agent import AIAgent

    model_cfg = cfg.get("model") or {}
    if isinstance(model_cfg, str):
        cfg_model = model_cfg
    else:
        cfg_model = model_cfg.get("default") or model_cfg.get("model") or ""
    effective_model = (target_model or "").strip() or cfg_model

    runtime = resolve_runtime_provider(
        requested=(requested or None), target_model=effective_model or None
    )
    fallback = get_fallback_chain(cfg)

    return AIAgent(
        api_key=runtime.get("api_key"),
        base_url=runtime.get("base_url"),
        provider=runtime.get("provider"),
        api_mode=runtime.get("api_mode"),
        model=effective_model,
        enabled_toolsets=toolsets_list,
        quiet_mode=True,
        platform="cli",
        credential_pool=runtime.get("credential_pool"),
        fallback_model=fallback or None,
    )


def _build_local_agent(toolsets_list: list[str]):
    """Construct an AIAgent bound to the in-process local GGUF backbone.

    The agent stack (agent/agent_init.py, provider == "local-model") resolves
    and downloads the weights on first use.  With a 64K+ context window the
    local model handles the full agent system prompt, tools, context files,
    and memory just like a remote provider.
    """
    from run_agent import AIAgent

    return AIAgent(
        api_key="local-no-key-required",
        base_url="llama-cpp://local",
        provider="local-model",
        api_mode="chat_completions",
        model="zeb-local",
        enabled_toolsets=toolsets_list,
        quiet_mode=True,
        platform="cli",
    )
