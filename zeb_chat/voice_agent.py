"""Optional server-side voice for Zeb — offline neural TTS via Piper.

The dashboard already does voice *input* in the browser (Web Speech API →
``/api/chat`` → the local backbone) and can speak replies with the browser's
own ``speechSynthesis``. This module adds a better, fully-offline *output*
path: Piper (https://github.com/OHF-Voice/piper1-gpl, the actively-maintained
successor to rhasspy/piper) — a fast neural TTS that runs on CPU with no API
key and no network at synthesis time, so Zeb keeps a natural voice even with
zero credentials and no internet.

It is deliberately **optional**. If ``piper-tts`` isn't installed or a voice
model isn't present, every function here degrades quietly and the dashboard
falls back to browser speech. Nothing in the chat path depends on it.

Design mirrors ``agent/local_model_manager.py``: a small voice model is
resolved from a HuggingFace repo and cached once under
``<zeb_home>/models/piper/``; ``huggingface_hub`` (baked into the image for
the GGUF backbone) is reused for the download.
"""

from __future__ import annotations

import io
import logging
import threading
import wave
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("zeb_chat")

# A small, natural US-English voice. medium quality is ~60MB of ONNX — tiny
# next to the GGUF backbone — and streams instantly on CPU. Overridable via
# config.yaml's ``voice.piper_voice`` / ``voice.piper_repo``.
_DEFAULT_VOICE = "en_US-lessac-medium"
_DEFAULT_VOICE_REPO = "rhasspy/piper-voices"

_load_lock = threading.Lock()
_loaded_voice: Any = None
_loaded_voice_name: str = ""


def _voice_cfg() -> dict[str, Any]:
    try:
        from zeb_cli.config import load_config

        cfg = load_config() or {}
        v = cfg.get("voice")
        return dict(v) if isinstance(v, dict) else {}
    except Exception:
        return {}


def _models_dir() -> Path:
    from zeb_constants import get_zeb_home

    d = get_zeb_home() / "models" / "piper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _piper_installed() -> bool:
    try:
        import piper  # noqa: F401

        return True
    except Exception:
        return False


def _resolve_voice_files(voice: str, repo: str) -> Optional[tuple[Path, Path]]:
    """Return (onnx, onnx.json) local paths, downloading once if needed.

    Piper voices in ``rhasspy/piper-voices`` are laid out by
    language/region/name/quality; the filenames are always ``<voice>.onnx``
    and ``<voice>.onnx.json``. We first look in the local cache, then fetch
    both files via huggingface_hub. Returns None on any failure.
    """
    cache = _models_dir()
    onnx = cache / f"{voice}.onnx"
    cfg = cache / f"{voice}.onnx.json"
    if onnx.is_file() and cfg.is_file():
        return onnx, cfg

    try:
        import huggingface_hub as hf
    except Exception:
        return None

    # e.g. en_US-lessac-medium -> en/en_US/lessac/medium/<voice>.onnx
    try:
        lang_region = voice.split("-", 1)[0]        # en_US
        lang = lang_region.split("_", 1)[0]          # en
        name_quality = voice.split("-")[1:]          # [lessac, medium]
        subdir = f"{lang}/{lang_region}/{name_quality[0]}/{name_quality[1]}"
    except Exception:
        return None

    try:
        for suffix in (".onnx", ".onnx.json"):
            hf.hf_hub_download(
                repo_id=repo,
                filename=f"{subdir}/{voice}{suffix}",
                local_dir=str(cache),
                local_dir_use_symlinks=False,
            )
        # hf_hub_download preserves the repo subpath; flatten to the names we
        # probe for above by resolving whatever landed on disk.
        found_onnx = next(iter(cache.rglob(f"{voice}.onnx")), None)
        found_cfg = next(iter(cache.rglob(f"{voice}.onnx.json")), None)
        if found_onnx and found_cfg:
            return found_onnx, found_cfg
    except Exception as exc:
        logger.info("Piper voice download skipped: %s", exc)
        return None
    return None


def _get_voice() -> Any:
    """Load (once) and return the Piper voice object, or None if unavailable."""
    global _loaded_voice, _loaded_voice_name
    if not _piper_installed():
        return None
    cfg = _voice_cfg()
    voice = str(cfg.get("piper_voice") or _DEFAULT_VOICE).strip()
    repo = str(cfg.get("piper_repo") or _DEFAULT_VOICE_REPO).strip()
    with _load_lock:
        if _loaded_voice is not None and _loaded_voice_name == voice:
            return _loaded_voice
        files = _resolve_voice_files(voice, repo)
        if not files:
            return None
        onnx, _cfg = files
        try:
            from piper import PiperVoice

            _loaded_voice = PiperVoice.load(str(onnx))
            _loaded_voice_name = voice
            return _loaded_voice
        except Exception as exc:
            logger.info("Piper voice load failed: %s", exc)
            return None


def available() -> bool:
    """True only when Piper is importable AND a voice model is ready to use."""
    return _get_voice() is not None


def status() -> dict[str, Any]:
    """Describe the voice capability for the dashboard.

    ``engine`` is "piper" when the offline neural voice is ready, otherwise
    "browser" — telling the client to use its own ``speechSynthesis``.
    """
    cfg = _voice_cfg()
    voice = str(cfg.get("piper_voice") or _DEFAULT_VOICE).strip()
    installed = _piper_installed()
    ready = available()
    return {
        "engine": "piper" if ready else "browser",
        "offline": True,
        "piper_installed": installed,
        "voice": voice if ready else "",
        "detail": (
            f"Offline neural voice ready ({voice})"
            if ready
            else (
                "Piper installed — voice model will download on first use"
                if installed
                else "Using in-browser speech (install piper-tts for an offline neural voice)"
            )
        ),
    }


def synthesize(text: str) -> Optional[bytes]:
    """Render ``text`` to WAV bytes with Piper, or None to defer to the browser.

    Never raises — any failure returns None so the caller falls back to
    client-side speech. Output is a standard PCM WAV the browser can play
    directly from a Blob.
    """
    text = (text or "").strip()
    if not text:
        return None
    voice = _get_voice()
    if voice is None:
        return None
    # Cap runaway input so a huge reply can't tie up CPU synthesizing minutes
    # of audio the user won't wait for.
    text = text[:2000]
    try:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            # piper1-gpl exposes synthesize_wav(text, wave_file); older
            # rhasspy/piper used synthesize(text, wave_file). Support both.
            if hasattr(voice, "synthesize_wav"):
                voice.synthesize_wav(text, wav)
            else:
                voice.synthesize(text, wav)
        data = buf.getvalue()
        return data if data else None
    except Exception as exc:
        logger.info("Piper synthesis failed, deferring to browser TTS: %s", exc)
        return None
