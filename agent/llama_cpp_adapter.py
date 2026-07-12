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
import time
from types import SimpleNamespace
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_loaded_model: Any = None
_loaded_model_path: Optional[str] = None
# The cache key is (path, n_ctx): a request for a DIFFERENT context window must
# reload rather than silently reuse a model loaded at another n_ctx. Keying on
# path alone is the "first writer wins" trap that let one caller pin n_ctx for
# every other caller in the process.
_loaded_model_key: Optional[tuple] = None


def _record(event: str, detail: str = "", level: str = "info") -> None:
    """Push a status event without ever letting telemetry break inference."""
    try:
        from agent import local_model_status

        local_model_status.record(event, detail, level)
    except Exception:
        pass


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


def _default_threads() -> int:
    """A CPU-thread count that leaves headroom instead of pegging every core.

    Zeb runs one *larger* model at "lower capacity" for efficiency: using
    roughly half the cores (capped) keeps the box responsive for the rest of
    the agent + background bots while still generating at a usable rate.
    """
    try:
        import os

        cpus = os.cpu_count() or 4
    except Exception:
        cpus = 4
    return max(2, min(8, cpus // 2))


def _load_model(
    model_path: str,
    *,
    n_ctx: int,
    n_gpu_layers: int,
    n_threads: int | None = None,
    use_mmap: bool = True,
) -> Any:
    """Load (or reuse) the process-wide ``llama_cpp.Llama`` instance.

    Kept as a single module-level singleton, guarded by a lock: the model
    takes real memory and load time (seconds), so every caller in the
    process — interactive chat AND the background autonomy bots — shares one
    loaded instance rather than each constructing (and leaking) its own.
    That single shared weight is the whole point of "one model, not three".

    Loaded for efficiency: ``use_mmap`` keeps weights memory-mapped (lower
    resident RAM) and ``n_threads`` defaults to a fraction of the cores so
    the model runs at "lower capacity" without starving everything else.
    """
    global _loaded_model, _loaded_model_path, _loaded_model_key
    key = (model_path, int(n_ctx))
    with _model_lock:
        if _loaded_model is not None and _loaded_model_key == key:
            return _loaded_model
        if _loaded_model is not None and _loaded_model_key != key:
            logger.info(
                "Reloading local model: key changed %s -> %s",
                _loaded_model_key, key,
            )
            _loaded_model = None
            _loaded_model_path = None
            _loaded_model_key = None

        llama_cpp = _get_llama_cpp_sdk()
        if llama_cpp is None:
            raise LocalModelLoadError(
                "llama-cpp-python is not installed and could not be "
                "lazy-installed. Run `zeb model` and select the local "
                "backbone, or install manually with "
                "`pip install llama-cpp-python`."
            )

        threads = n_threads or _default_threads()
        logger.info(
            "Loading local GGUF model from %s (n_ctx=%d, n_threads=%d, mmap=%s)",
            model_path, n_ctx, threads, use_mmap,
        )
        _record(
            "model.loading",
            f"{model_path.split('/')[-1]} (n_ctx={n_ctx}, threads={threads})",
        )
        _t0 = time.time()
        try:
            _loaded_model = llama_cpp.Llama(
                model_path=model_path,
                n_ctx=n_ctx,
                # -1 offloads every layer to GPU if llama-cpp-python was built
                # with GPU support and one is present; falls back to pure CPU
                # otherwise. Either way this must never raise — it's the
                # backbone with no fallback of its own.
                n_gpu_layers=n_gpu_layers,
                n_threads=threads,
                use_mmap=use_mmap,
                verbose=False,
            )
        except Exception as exc:
            _record("model.load_error", str(exc), level="error")
            raise LocalModelLoadError(
                f"Failed to load GGUF model at {model_path}: {exc}"
            ) from exc
        _loaded_model_path = model_path
        _loaded_model_key = key
        _record("model.loaded", f"ready in {time.time() - _t0:.1f}s")
        return _loaded_model


def unload_model() -> None:
    """Release the loaded model and free its memory.

    Exposed for the self-healing health checker: if the process is under
    memory pressure and the local backbone isn't the active provider right
    now, unloading reclaims that memory. The next request transparently
    reloads it.
    """
    global _loaded_model, _loaded_model_path, _loaded_model_key
    with _model_lock:
        was_loaded = _loaded_model is not None
        _loaded_model = None
        _loaded_model_path = None
        _loaded_model_key = None
    if was_loaded:
        _record("model.unloaded", "freed for reload / memory reclaim")


def is_model_loaded() -> bool:
    return _loaded_model is not None


def loaded_model_path() -> Optional[str]:
    """Public accessor for the path of the currently loaded model (or None)."""
    return _loaded_model_path


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
        max_tokens = max_tokens or 2048
        # Transient fallback only — immediately replaced by the loaded
        # model's real n_ctx below.
        n_ctx = 65536
        try:
            _n = llama.n_ctx()
            if isinstance(_n, int) and _n > 0:
                n_ctx = _n
        except Exception:
            pass
        kwargs: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature if temperature is not None else 0.7,
            "max_tokens": min(max_tokens, n_ctx // 2),
        }
        # Only pass tools when the context window can absorb them. Each tool
        # schema serialises to ~200-500 tokens; a full CLI toolset easily
        # exceeds a 4K window before any user message fits.
        if tools:
            approx_tool_chars = sum(len(str(t)) for t in tools)
            approx_tool_tokens = approx_tool_chars // 4
            if approx_tool_tokens < n_ctx // 2:
                kwargs["tools"] = tools
                if tool_choice is not None:
                    kwargs["tool_choice"] = tool_choice
            else:
                logger.info(
                    "Stripping %d tools (~%d tokens) — exceeds half of n_ctx=%d",
                    len(tools), approx_tool_tokens, n_ctx,
                )

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
        n_ctx: int = 65536,
        n_gpu_layers: int = -1,
        n_threads: int | None = None,
        use_mmap: bool = True,
        **_ignored: Any,
    ):
        self.model_path = model_path
        self._llama = _load_model(
            model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            n_threads=n_threads,
            use_mmap=use_mmap,
        )
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
