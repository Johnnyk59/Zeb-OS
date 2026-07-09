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
        try:
            # Lazy imports — keep the agent stack out of test-time imports.
            from zeb_cli.config import load_config
            from zeb_cli.fallback_config import get_fallback_chain
            from zeb_cli.runtime_provider import resolve_runtime_provider
            from zeb_cli.tools_config import _get_platform_tools
            from run_agent import AIAgent

            cfg = load_config()

            model_cfg = cfg.get("model") or {}
            if isinstance(model_cfg, str):
                effective_model = model_cfg
            else:
                effective_model = model_cfg.get("default") or model_cfg.get("model") or ""

            runtime = resolve_runtime_provider(
                requested=None,
                target_model=effective_model or None,
            )

            toolsets_list = sorted(_get_platform_tools(cfg, "cli"))
            fallback = get_fallback_chain(cfg)

            agent = AIAgent(
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

            result = agent.run_conversation(message, conversation_history=history)
            return result.get("final_response") or ""
        except Exception as exc:  # noqa: BLE001
            logger.exception("Chat turn failed")
            return f"[Zeb chat error: {exc}]"
