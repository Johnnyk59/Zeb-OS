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


def run_chat_turn(message: str, history: list[dict] | None = None) -> str:
    """Run one full Zeb agent turn and return the final response text.

    Args:
        message: The user's message for this turn.
        history: Optional prior conversation history (list of role/content
            dicts) passed through to the agent.

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

        # Decide whether a usable *remote* provider is configured. Out of the
        # box nothing is (model == ""), so a fresh `docker run` still answers
        # "yo" instantly on the bundled local GGUF backbone — no keys, no
        # config. A configured provider is preferred when present; the local
        # backbone is also used as a last-resort fallback if the configured
        # turn fails to initialise (e.g. missing/invalid credentials).
        use_local = not _remote_provider_usable(cfg)

        if not use_local:
            try:
                agent = _build_remote_agent(cfg, toolsets_list)
                result = agent.run_conversation(message, conversation_history=history)
                return result.get("final_response") or ""
            except Exception:  # noqa: BLE001
                logger.exception("Configured provider turn failed; falling back to local backbone")
                use_local = True

        # Local GGUF backbone — always available, zero configuration.
        try:
            agent = _build_local_agent(toolsets_list)
            result = agent.run_conversation(message, conversation_history=history)
            return result.get("final_response") or ""
        except Exception as exc:  # noqa: BLE001
            logger.exception("Local backbone turn failed")
            return f"[Zeb chat error: {exc}]"


def _remote_provider_usable(cfg: dict) -> bool:
    """True when a configured remote provider looks ready to serve a turn.

    Conservative: any signal that a real model + reachable endpoint/credential
    exists counts. When this returns False the chat server uses the always-on
    local GGUF backbone instead.
    """
    try:
        model_cfg = cfg.get("model") or {}
        if isinstance(model_cfg, str):
            model_name = model_cfg
            provider = ""
            base_url = ""
        else:
            model_name = model_cfg.get("default") or model_cfg.get("model") or ""
            provider = str(model_cfg.get("provider") or "").strip().lower()
            base_url = str(model_cfg.get("base_url") or "").strip()
        if not model_name:
            return False
        if provider in ("local-model", "moa", "ollama"):
            # Offline/in-process providers are "usable" without a remote key.
            return True
        from zeb_cli.runtime_provider import resolve_runtime_provider

        runtime = resolve_runtime_provider(requested=None, target_model=model_name)
        rp = str(runtime.get("provider") or "").strip().lower()
        if rp in ("local-model", "moa", "ollama"):
            return True
        return bool(
            runtime.get("api_key")
            or runtime.get("credential_pool")
            or runtime.get("base_url")
            or base_url
        )
    except Exception:  # noqa: BLE001
        return False


def _build_remote_agent(cfg: dict, toolsets_list: list[str]):
    from zeb_cli.fallback_config import get_fallback_chain
    from zeb_cli.runtime_provider import resolve_runtime_provider
    from run_agent import AIAgent

    model_cfg = cfg.get("model") or {}
    if isinstance(model_cfg, str):
        effective_model = model_cfg
    else:
        effective_model = model_cfg.get("default") or model_cfg.get("model") or ""

    runtime = resolve_runtime_provider(requested=None, target_model=effective_model or None)
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
    and downloads the weights on first use. Full toolsets are kept so a local
    turn has the same workspace read/modify capabilities as a remote one.
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
