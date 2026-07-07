"""Helpers for reading the effective fallback provider chain from config."""

from __future__ import annotations

from typing import Any


def _normalized_base_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().rstrip("/")


def _iter_fallback_entries(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        candidates = [raw]
    elif isinstance(raw, list):
        candidates = raw
    else:
        return []

    entries: list[dict[str, Any]] = []
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        provider = str(entry.get("provider") or "").strip()
        model = str(entry.get("model") or "").strip()
        if not provider or not model:
            continue

        normalized = dict(entry)
        normalized["provider"] = provider
        normalized["model"] = model

        base_url = _normalized_base_url(entry.get("base_url"))
        if base_url:
            normalized["base_url"] = base_url

        entries.append(normalized)
    return entries


def _entry_identity(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(entry.get("provider") or "").strip().lower(),
        str(entry.get("model") or "").strip().lower(),
        _normalized_base_url(entry.get("base_url")).lower(),
    )


def get_fallback_chain(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return the effective fallback chain merged across old and new config keys.

    ``fallback_providers`` remains the primary source of truth and keeps its
    order. Legacy ``fallback_model`` entries are appended afterwards unless
    they target the same provider/model/base_url route as an earlier entry.
    The returned list always contains fresh dict copies.

    This is the *configured* chain only — it does not include the implicit
    local-model safety net. That's added at the point of use in
    ``agent/chat_completion_helpers.py::_try_activate_fallback`` (see
    ``append_local_model_safety_net``), not here, because this function is
    also read for display/config purposes (``zeb fallback list``, cron job
    config summaries) where injecting an entry the user never configured
    would be surprising.
    """

    config = config or {}
    chain: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for key in ("fallback_providers", "fallback_model"):
        for entry in _iter_fallback_entries(config.get(key)):
            identity = _entry_identity(entry)
            if identity in seen:
                continue
            seen.add(identity)
            chain.append(entry)

    return chain


def append_local_model_safety_net(
    chain: list[dict[str, Any]], config: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Return ``chain`` with the local GGUF backbone appended as a final entry.

    Used only by the live retry path (``_try_activate_fallback``), not by
    ``get_fallback_chain`` itself — see that function's docstring. Skips the
    append when the user opted out (``local_model.disable_auto_fallback:
    true``) or the chain already targets ``local-model`` explicitly.
    """
    config = config or {}
    local_model_cfg = config.get("local_model")
    if isinstance(local_model_cfg, dict) and local_model_cfg.get("disable_auto_fallback") is True:
        return chain

    seen = {_entry_identity(e) for e in chain}
    local_entry = {"provider": "local-model", "model": "zeb-local"}
    if _entry_identity(local_entry) in seen:
        return chain
    return [*chain, local_entry]
