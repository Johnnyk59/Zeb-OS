"""Local-model completion helper for autonomy bots.

Thin wrapper over the baked-in GGUF backbone (``agent/llama_cpp_adapter.py``
+ ``agent/local_model_manager.py``). Bots call this for any reasoning they
need — summarizing news, distilling a personality note, deciding whether
something is notification-worthy — without ever depending on an API key.

``complete()`` NEVER raises: if the model can't be resolved or loaded
(offline first-run before the weights are cached, no llama-cpp-python,
disk full), it returns ``None`` and the caller degrades gracefully. This
is the whole point of the local backbone — autonomy keeps running, just
with less reasoning power, instead of crashing.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The autonomy loop is single-threaded (one scheduler thread runs bots
# serially), but guard model access anyway so an ad-hoc caller from another
# thread can't drive two concurrent generations through one Llama instance.
_complete_lock = threading.Lock()


def complete(
    prompt: str,
    *,
    system: str = "",
    max_tokens: int = 512,
    temperature: float = 0.7,
    config: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Run one local-model chat completion. Returns text, or None if unavailable."""
    try:
        from agent.llama_cpp_adapter import LlamaCppClient, LocalModelLoadError
        from agent.local_model_manager import (
            DEFAULT_LOCAL_MODEL_CTX,
            LocalModelUnavailable,
            get_local_model_path,
        )
    except Exception as exc:  # pragma: no cover - import guard
        logger.debug("local_llm: backbone import failed: %s", exc)
        return None

    if config is None:
        try:
            from zeb_cli.config import load_config

            config = load_config()
        except Exception:
            config = {}

    # Status-only check first: never trigger a multi-GB download from inside
    # a background bot tick. If the weights aren't cached yet, the bot just
    # skips its LLM step this cycle; the model gets fetched the first time
    # the user actually selects/uses it interactively.
    try:
        model_path = get_local_model_path(config)
    except Exception:
        model_path = None
    if model_path is None:
        logger.debug("local_llm: no cached local model; skipping completion")
        return None

    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    ctx_size = 0
    try:
        ctx_size = int((config.get("local_model") or {}).get("n_ctx") or DEFAULT_LOCAL_MODEL_CTX)
    except Exception:
        ctx_size = DEFAULT_LOCAL_MODEL_CTX

    try:
        with _complete_lock:
            client = LlamaCppClient(model_path=str(model_path), n_ctx=ctx_size)
            resp = client.chat.completions.create(
                model="zeb-local",
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        choices = getattr(resp, "choices", None) or []
        if not choices:
            return None
        content = getattr(choices[0].message, "content", None)
        return content.strip() if isinstance(content, str) else None
    except (LocalModelLoadError, LocalModelUnavailable) as exc:
        logger.debug("local_llm: model unavailable: %s", exc)
        return None
    except Exception as exc:
        logger.warning("local_llm: completion failed: %s", exc)
        return None
