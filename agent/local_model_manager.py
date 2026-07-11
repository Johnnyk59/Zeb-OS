"""Resolve and, if needed, download the local GGUF backbone weights.

ZebOS ships no model weights in the repo — they're too large to commit and
would go stale immediately. Instead this module resolves a local path for
the always-on local backbone, downloading it once into
``<zeb_home>/models/gguf/`` on first use and reusing that cache forever
after (mirrors the ``cache/images``, ``cache/videos`` convention in
zeb_constants.get_zeb_home()).

The default model is **Phi-3.5-mini-instruct** in a 4-bit GGUF quant
(~2.4GB) with a 128K context window — a light download that still handles
full conversations plus the complete agent system prompt and tools.  A
fresh container downloads it once on first boot and caches it forever;
users can override every part of this via ``config.yaml``'s
``local_model:`` section, or point ``local_model.path`` at any GGUF file
already on disk to skip the download path entirely (air-gapped installs,
custom fine-tunes).

Note on memory: Phi-3.5-mini does not use grouped-query attention, so its
KV cache grows quickly with ``n_ctx`` (roughly 0.37 MB/token → ~50GB at the
full 128K).  On a RAM-constrained host, lower ``local_model.n_ctx`` (32K is
~13GB), or switch ``local_model.repo_id`` to
``bartowski/Qwen2.5-7B-Instruct-GGUF`` (GQA → ~7.5GB at 128K) for a heavier
download but a far lighter long-context footprint.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from agent import local_model_status as _status

logger = logging.getLogger(__name__)

# Repo + quantization used when the user hasn't configured anything. Kept
# as plain module constants (not hardcoded deep in a function) so a fork or
# an advanced user can override at import time, and so config.yaml's
# ``local_model.repo_id`` / ``local_model.quant`` documentation has a
# single source of truth to point at.
#
# ONE capable model for everything (chat + background autonomy + aux).
# Phi-3.5-mini-instruct in a 4-bit quant (~2.4GB) has a 128K context window
# in a small, fast package, and bartowski's repo provides
# single-file-per-quant for clean downloads.  Loaded with mmap + a fraction
# of the CPU cores (see agent/llama_cpp_adapter.py) for efficiency.
# (For a stronger model / lighter long-context KV cache via GQA, set
# local_model.repo_id to "bartowski/Qwen2.5-7B-Instruct-GGUF" — ~4.7GB but
# only ~7.5GB KV cache at 128K vs Phi-3.5-mini's ~50GB.)
DEFAULT_LOCAL_MODEL_REPO = "bartowski/Phi-3.5-mini-instruct-GGUF"
DEFAULT_LOCAL_MODEL_QUANT = "Q4_K_M"  # single-file ~2.4GB
DEFAULT_LOCAL_MODEL_CTX = 131072  # Phi-3.5-mini native 128K window

ProgressCallback = Callable[[str], None]


class LocalModelUnavailable(RuntimeError):
    """Raised when the local backbone can't be resolved (missing deps, failed download, no disk)."""


def _models_dir() -> Path:
    from zeb_constants import get_zeb_home

    d = get_zeb_home() / "models" / "gguf"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_hf_hub_sdk():
    # Import-first: if huggingface_hub is already importable, return it
    # immediately and never touch lazy_deps.ensure() — ensure() can hang
    # trying to pip-install in CI where it isn't available.
    try:
        import huggingface_hub

        return huggingface_hub
    except ImportError:
        pass

    try:
        from tools.lazy_deps import ensure as _lazy_ensure

        _lazy_ensure("provider.local_model_download", prompt=False)
    except ImportError:
        pass
    except Exception:
        pass

    try:
        import huggingface_hub

        return huggingface_hub
    except ImportError:
        return None


def _local_model_config(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config or {}
    return dict(config.get("local_model") or {})


def resolved_repo_quant(config: dict[str, Any] | None = None) -> tuple[str, str]:
    """Return the (repo_id, quant) that would be used, applying defaults."""
    lm = _local_model_config(config)
    repo = (lm.get("repo_id") or DEFAULT_LOCAL_MODEL_REPO).strip()
    quant = (lm.get("quant") or DEFAULT_LOCAL_MODEL_QUANT).strip()
    return repo, quant


def resolved_n_ctx(config: dict[str, Any] | None = None) -> int:
    """Return the context window size for the local model, applying defaults."""
    lm = _local_model_config(config)
    val = lm.get("n_ctx") or lm.get("context_length")
    if isinstance(val, int) and val > 0:
        return val
    return DEFAULT_LOCAL_MODEL_CTX


def local_model_display_name(config: dict[str, Any] | None = None) -> str:
    """Human-friendly name for the active local backbone (for the dashboard).

    Derives a clean label from ``local_model.path`` (its filename) or from
    the configured/default repo id + quant, so the Local Model Status panel
    can show e.g. "Phi-3-mini-4k-instruct · q4" without the caller needing
    to know the resolution rules.
    """
    lm = _local_model_config(config)
    explicit = (lm.get("path") or "").strip()
    if explicit:
        return Path(explicit).name
    repo, quant = resolved_repo_quant(config)
    short = repo.split("/")[-1] if "/" in repo else repo
    return f"{short} · {quant}" if quant else short


def get_local_model_path(config: dict[str, Any] | None = None) -> Optional[Path]:
    """Return the resolved GGUF path if it's already on disk, without downloading.

    Use this for status checks (doctor, health checker, picker UI) that
    shouldn't trigger a multi-GB download just to answer "is it ready?".
    """
    lm_config = _local_model_config(config)

    explicit = (lm_config.get("path") or "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None

    repo_id = (lm_config.get("repo_id") or DEFAULT_LOCAL_MODEL_REPO).strip()
    quant = (lm_config.get("quant") or DEFAULT_LOCAL_MODEL_QUANT).strip()
    target_dir = _models_dir() / repo_id.replace("/", "__")
    if not target_dir.is_dir():
        return None
    matches = sorted(target_dir.glob(f"*{quant}*.gguf"))
    return matches[0] if matches else None


def _resolve_gguf_filename(hf_hub, repo_id: str, quant: str) -> str:
    """Find the exact filename for ``quant`` in ``repo_id`` without hardcoding it.

    GGUF repos are quantized by third parties with varying naming
    conventions (``Model.Q4_K_M.gguf`` vs ``model-q4_k_m.gguf``); listing
    the repo and matching case-insensitively is more robust than a single
    hardcoded filename guess, and adapts automatically if the upstream repo
    renames files.
    """
    files = hf_hub.list_repo_files(repo_id)
    quant_lower = quant.lower()
    candidates = [
        f for f in files if f.lower().endswith(".gguf") and quant_lower in f.lower()
    ]
    if not candidates:
        gguf_files = [f for f in files if f.lower().endswith(".gguf")]
        raise LocalModelUnavailable(
            f"No {quant} GGUF file found in {repo_id!r}. "
            f"Available .gguf files: {gguf_files or '(none)'}. "
            f"Set local_model.quant in config.yaml to one of the available "
            f"quantizations, or local_model.path to a GGUF file you already have."
        )
    # Prefer the shortest match (avoids e.g. "Q4_K_M" matching a
    # "Q4_K_M-imatrix" variant when the plain quant file also exists).
    candidates.sort(key=len)
    return candidates[0]


def ensure_local_model_weights(
    config: dict[str, Any] | None = None,
    *,
    progress_callback: Optional[ProgressCallback] = None,
) -> Path:
    """Return a local GGUF path, downloading the default model if needed.

    Resolution order:
      1. ``local_model.path`` in config.yaml — explicit override, used as-is.
      2. Already-downloaded cache at ``<zeb_home>/models/gguf/<repo>/``.
      3. Fresh download via huggingface_hub into that cache dir.

    Raises :class:`LocalModelUnavailable` with a clear, actionable message
    on any failure (missing deps, network unreachable, bad repo/quant) —
    callers should catch this and fall back to whatever they'd otherwise do
    when no backbone is available, never crash the caller.
    """
    lm_config = _local_model_config(config)

    explicit = (lm_config.get("path") or "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            raise LocalModelUnavailable(
                f"local_model.path is set to {explicit!r} but that file doesn't exist."
            )
        return p

    cached = get_local_model_path(config)
    if cached is not None:
        _status.record("weights.cached", cached.name)
        return cached

    hf_hub = _get_hf_hub_sdk()
    if hf_hub is None:
        _status.record(
            "weights.error", "huggingface_hub not installed", level="error"
        )
        raise LocalModelUnavailable(
            "huggingface_hub is not installed and could not be lazy-installed. "
            "Install it manually with `pip install huggingface_hub`, or set "
            "local_model.path in config.yaml to a GGUF file you already have."
        )

    repo_id = (lm_config.get("repo_id") or DEFAULT_LOCAL_MODEL_REPO).strip()
    quant = (lm_config.get("quant") or DEFAULT_LOCAL_MODEL_QUANT).strip()
    target_dir = _models_dir() / repo_id.replace("/", "__")
    target_dir.mkdir(parents=True, exist_ok=True)

    if progress_callback:
        progress_callback(f"Resolving {quant} GGUF file in {repo_id}…")
    try:
        filename = _resolve_gguf_filename(hf_hub, repo_id, quant)
    except LocalModelUnavailable:
        raise
    except Exception as exc:
        raise LocalModelUnavailable(
            f"Could not list files in {repo_id!r} (network unreachable, or the "
            f"repo doesn't exist): {exc}. Set local_model.path in config.yaml "
            f"to use a GGUF file you already have instead."
        ) from exc

    if progress_callback:
        progress_callback(f"Downloading {filename} ({repo_id}) — this happens once…")

    # Best-effort expected size so the dashboard's bandwidth meter has a
    # denominator. Never fatal — if the metadata call fails we just report an
    # unknown total and stream a live byte count instead.
    expected_size = 0
    try:
        meta = hf_hub.get_hf_file_metadata(
            hf_hub.hf_hub_url(repo_id=repo_id, filename=filename)
        )
        expected_size = int(getattr(meta, "size", 0) or 0)
    except Exception:
        expected_size = 0

    _status.download_started(filename, expected_size)
    _stop_poll = threading.Event()
    poller = threading.Thread(
        target=_poll_download_size,
        args=(target_dir, filename, expected_size, _stop_poll),
        name="local-model-dl-progress",
        daemon=True,
    )
    poller.start()
    try:
        downloaded = hf_hub.hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(target_dir),
        )
    except Exception as exc:
        _stop_poll.set()
        _status.download_finished(ok=False, detail=str(exc))
        raise LocalModelUnavailable(
            f"Download of {filename} from {repo_id!r} failed: {exc}. "
            f"Check network access, or set local_model.path in config.yaml "
            f"to a GGUF file you already have."
        ) from exc

    _stop_poll.set()
    _status.download_finished(ok=True, detail=f"{filename} ready")
    if progress_callback:
        progress_callback("Local model ready.")
    return Path(downloaded)


def _poll_download_size(
    target_dir: Path, filename: str, expected: int, stop: threading.Event
) -> None:
    """Watch the growing download on disk and report byte progress.

    huggingface_hub streams to an ``*.incomplete`` blob (or the final file);
    we don't need to know which — we sum the largest matching file's size on
    a short timer so the dashboard shows live bandwidth without hooking into
    hf_hub's internal tqdm. Entirely best-effort and fail-open.
    """
    stem = Path(filename).name
    while not stop.wait(0.5):
        try:
            best = 0
            for p in target_dir.rglob("*"):
                try:
                    if not p.is_file():
                        continue
                    nm = p.name
                    if stem in nm or nm.endswith(".incomplete"):
                        best = max(best, p.stat().st_size)
                except Exception:
                    continue
            if best:
                _status.download_progress(best, expected or None)
        except Exception:
            # Never let the progress poller disturb the actual download.
            time.sleep(0.5)
