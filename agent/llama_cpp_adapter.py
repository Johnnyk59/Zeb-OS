"""In-process llama.cpp adapter — the always-on local backbone.

This is ZebOS's default inference path: a quantized GGUF model loaded
directly into this process via ``llama-cpp-python``, with zero network
calls, zero API keys, and zero external processes to supervise. It exists
so ZebOS keeps functioning — degraded but alive — with no internet access
and no credentials configured at all; API-key providers layer on top of
this as optional upgrades, never a replacement for it.

Structurally this mirrors ``agent/moa_loop.py``'s ``MoAClient``: a minimal
facade that exposes ``.chat.completions.create()`` like the real OpenAI SDK
so the rest of the agent loop (``run_agent.py``, ``agent/conversation_loop.py``,
``agent/chat_completion_helpers.py``) never has to special-case it. Where
``MoAClient`` fans a request out to other network-backed clients,
``LlamaCppClient`` answers it in-process using ``llama_cpp.Llama``.

llama-cpp-python's own ``Llama.create_chat_completion()`` already returns an
OpenAI-chat-completion-shaped ``dict`` (message/choices/usage). The
translation layer here only needs to wrap that dict in attribute-access
namespaces, since the rest of the codebase reads ``.choices[0].message.content``
rather than dict subscripts.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from types import SimpleNamespace
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_loaded_model: Any = None
_loaded_model_path: Optional[str] = None


def _get_llama_cpp_sdk():
    # Import-first: if llama_cpp is already importable (installed, or a fake
    # injected into sys.modules by tests), return it immediately and never
    # touch lazy_deps.ensure() — ensure() would try to pip-compile the C++
    # package, which hangs for minutes in CI where it isn't installed.
    try:
        import llama_cpp

        return llama_cpp
    except ImportError:
        pass

    try:
        from tools.lazy_deps import ensure as _lazy_ensure

        _lazy_ensure("provider.llama_cpp", prompt=False)
    except ImportError:
        pass
    except Exception:
        pass

    try:
        import llama_cpp

        return llama_cpp
    except ImportError:
        return None


class LocalModelLoadError(RuntimeError):
    """Raised when llama-cpp-python or the GGUF weights can't be loaded."""


def _load_model(model_path: str, *, n_ctx: int, n_gpu_layers: int) -> Any:
    """Load (or reuse) the process-wide ``llama_cpp.Llama`` instance.

    Kept as a single module-level singleton, guarded by a lock: a ~2-4B
    quantized model already takes real memory and load time (seconds), so
    every caller in the process should share one loaded instance rather
    than each constructing (and leaking) its own.
    """
    global _loaded_model, _loaded_model_path
    with _model_lock:
        if _loaded_model is not None and _loaded_model_path == model_path:
            return _loaded_model

        llama_cpp = _get_llama_cpp_sdk()
        if llama_cpp is None:
            raise LocalModelLoadError(
                "llama-cpp-python is not installed and could not be "
                "lazy-installed. Run `zeb model` and select the local "
                "backbone, or install manually with "
                "`pip install llama-cpp-python`."
            )

        logger.info("Loading local GGUF model from %s (n_ctx=%d)", model_path, n_ctx)
        try:
            _loaded_model = llama_cpp.Llama(
                model_path=model_path,
                n_ctx=n_ctx,
                # -1 offloads every layer to GPU if llama-cpp-python was built
                # with GPU support and one is present; falls back to pure CPU
                # otherwise. Either way this must never raise — it's the
                # backbone with no fallback of its own.
                n_gpu_layers=n_gpu_layers,
                verbose=False,
            )
        except Exception as exc:
            raise LocalModelLoadError(
                f"Failed to load GGUF model at {model_path}: {exc}"
            ) from exc
        _loaded_model_path = model_path
        return _loaded_model


def unload_model() -> None:
    """Release the loaded model and free its memory.

    Exposed for the self-healing health checker: if the process is under
    memory pressure and the local backbone isn't the active provider right
    now, unloading reclaims that memory. The next request transparently
    reloads it.
    """
    global _loaded_model, _loaded_model_path
    with _model_lock:
        _loaded_model = None
        _loaded_model_path = None


def is_model_loaded() -> bool:
    return _loaded_model is not None


def _namespace_tool_calls(tool_calls: Optional[list[dict[str, Any]]]):
    if not tool_calls:
        return None
    return [
        SimpleNamespace(
            id=tc.get("id", ""),
            type=tc.get("type", "function"),
            function=SimpleNamespace(
                name=(tc.get("function") or {}).get("name", ""),
                arguments=(tc.get("function") or {}).get("arguments", "{}"),
            ),
        )
        for tc in tool_calls
    ]


def _translate_response(raw: dict[str, Any], model: str) -> SimpleNamespace:
    choices = []
    for c in raw.get("choices", []) or []:
        msg = c.get("message", {}) or {}
        choices.append(
            SimpleNamespace(
                index=c.get("index", 0),
                message=SimpleNamespace(
                    role=msg.get("role", "assistant"),
                    content=msg.get("content"),
                    tool_calls=_namespace_tool_calls(msg.get("tool_calls")),
                ),
                finish_reason=c.get("finish_reason", "stop"),
            )
        )
    usage = raw.get("usage", {}) or {}
    return SimpleNamespace(
        id=raw.get("id", "local-completion"),
        model=model,
        choices=choices,
        usage=SimpleNamespace(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        ),
    )


def _translate_stream_chunk(raw: dict[str, Any], model: str) -> SimpleNamespace:
    choices = []
    for c in raw.get("choices", []) or []:
        delta = c.get("delta", {}) or {}
        choices.append(
            SimpleNamespace(
                index=c.get("index", 0),
                delta=SimpleNamespace(
                    role=delta.get("role"),
                    content=delta.get("content"),
                    tool_calls=_namespace_tool_calls(delta.get("tool_calls")),
                ),
                finish_reason=c.get("finish_reason"),
            )
        )
    return SimpleNamespace(id=raw.get("id", "local-completion"), model=model, choices=choices)


class _LocalChatCompletions:
    def __init__(self, client: "LlamaCppClient"):
        self._client = client

    def create(
        self,
        *,
        model: str = "zeb-local",
        messages: list[dict[str, Any]],
        stream: bool = False,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Any = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **_ignored: Any,
    ):
        llama = self._client._llama
        kwargs: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature if temperature is not None else 0.7,
            "max_tokens": max_tokens or 2048,
        }
        # Not every GGUF chat template supports tool calling — llama-cpp-python
        # raises on its own if the loaded model's template can't handle it,
        # which surfaces to the caller as a normal exception (handled the
        # same way a network error from any other provider would be).
        if tools:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

        if stream:
            return self._stream(llama, kwargs, model)

        raw = llama.create_chat_completion(**kwargs)
        return _translate_response(raw, model)

    def _stream(
        self, llama: Any, kwargs: dict[str, Any], model: str
    ) -> Iterator[SimpleNamespace]:
        for chunk in llama.create_chat_completion(stream=True, **kwargs):
            yield _translate_stream_chunk(chunk, model)


class LlamaCppClient:
    """Minimal OpenAI-SDK-compatible facade over an in-process llama.cpp model.

    No API key, no HTTP base_url — ``agent_init.py`` sets sentinel values
    for both (mirrors ``MoAClient`` wiring: ``base_url="moa://local"``,
    ``api_key="moa-virtual-provider"``) purely for display/logging; nothing
    ever dereferences them as a real endpoint.
    """

    def __init__(
        self,
        *,
        model_path: str,
        n_ctx: int = 8192,
        n_gpu_layers: int = -1,
        **_ignored: Any,
    ):
        self.model_path = model_path
        self._llama = _load_model(model_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers)
        self.chat = SimpleNamespace(completions=_LocalChatCompletions(self))

    def ping(self, timeout: float = 30.0) -> bool:
        """Cheap liveness probe used by the self-healing health checker.

        ``timeout`` is accepted for interface symmetry with network health
        checks but isn't enforced here — a stuck in-process generation call
        would mean llama.cpp itself has wedged, which no client-side timeout
        can fix; the health checker instead treats a hang here as a reason
        to fully unload and reload the model (see ``gateway/self_healing.py``).
        """
        try:
            raw = self._llama.create_chat_completion(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return bool(raw.get("choices"))
        except Exception:
            logger.warning("Local model ping failed", exc_info=True)
            return False


class AsyncLlamaCppClient:
    """Async wrapper over :class:`LlamaCppClient` via a worker thread.

    llama.cpp inference is CPU-bound and blocking; there's no native async
    API to wrap, so — like ``agent/gemini_native_adapter.py``'s
    ``AsyncGeminiNativeClient`` — this just runs the sync call in a thread
    and awaits it, giving async callers a non-blocking interface without
    needing a second inference implementation.
    """

    def __init__(self, sync_client: LlamaCppClient):
        self._sync = sync_client
        self.chat = SimpleNamespace(completions=_AsyncLocalChatCompletions(sync_client))

    @property
    def api_key(self) -> str:
        return "local-no-key-required"

    @property
    def base_url(self) -> str:
        return "llama-cpp://local"


class _AsyncLocalChatCompletions:
    def __init__(self, sync_client: LlamaCppClient):
        self._sync_client = sync_client

    async def create(self, *, stream: bool = False, **kwargs: Any):
        completions = self._sync_client.chat.completions
        if stream:
            sync_iter = await asyncio.to_thread(completions.create, stream=True, **kwargs)

            async def _agen():
                for chunk in sync_iter:
                    yield chunk

            return _agen()
        return await asyncio.to_thread(completions.create, stream=False, **kwargs)
