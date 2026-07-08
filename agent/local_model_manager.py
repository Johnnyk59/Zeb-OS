"""Resolve and, if needed, download the local GGUF backbone weights.

ZebOS ships no model weights in the repo — they're too large to commit and
would go stale immediately. Instead this module resolves a local path for
the always-on local backbone, downloading it once into
``<zeb_home>/models/gguf/`` on first use and reusing that cache forever
after (mirrors the ``cache/images``, ``cache/videos`` convention in
zeb_constants.get_zeb_home()).

The default model is a small Nous Research "Hermes" GGUF quant — same
lineage as the rest of this fork — chosen for being small enough to run
acceptably on CPU-only hardware while still being tool-call capable. Users
can override every part of this via ``config.yaml``'s ``local_model:``
section, or point ``local_model.path`` at any GGUF file already on disk to
skip the download path entirely (air-gapped installs, custom fine-tunes).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Repo + quantization used when the user hasn't configured anything. Kept
# as plain module constants (not hardcoded deep in a function) so a fork or
# an advanced user can override at import time, and so config.yaml's
# ``local_model.repo_id`` / ``local_model.quant`` documentation has a
# single source of truth to point at.
DEFAULT_LOCAL_MODEL_REPO = "NousResearch/Hermes-3-Llama-3.2-3B-GGUF"
DEFAULT_LOCAL_MODEL_QUANT = "Q4_K_M"  # ~2GB — CPU-friendly quality/size tradeoff
DEFAULT_LOCAL_MODEL_CTX = 8192

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
        return cached

    hf_hub = _get_hf_hub_sdk()
    if hf_hub is None:
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
    try:
        downloaded = hf_hub.hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(target_dir),
        )
    except Exception as exc:
        raise LocalModelUnavailable(
            f"Download of {filename} from {repo_id!r} failed: {exc}. "
            f"Check network access, or set local_model.path in config.yaml "
            f"to a GGUF file you already have."
        ) from exc

    if progress_callback:
        progress_callback("Local model ready.")
    return Path(downloaded)
