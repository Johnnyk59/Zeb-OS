"""Tests for the Nous-Zeb-3/4 non-agentic warning detector.

Prior to this check, the warning fired on any model whose name contained
``"zeb"`` anywhere (case-insensitive). That false-positived on unrelated
local Modelfiles such as ``zeb-brain:qwen3-14b-ctx16k`` — a tool-capable
Qwen3 wrapper that happens to live under the "zeb" tag namespace.

``is_nous_zeb_non_agentic`` should only match the actual Nous Research
Zeb-3 / Zeb-4 chat family.
"""

from __future__ import annotations

import pytest

from zeb_cli.model_switch import (
    _ZEB_MODEL_WARNING,
    _check_zeb_model_warning,
    is_nous_zeb_non_agentic,
)


@pytest.mark.parametrize(
    "model_name",
    [
        "NousResearch/Zeb-3-Llama-3.1-70B",
        "NousResearch/Zeb-3-Llama-3.1-405B",
        "zeb-3",
        "Zeb-3",
        "zeb-4",
        "zeb-4-405b",
        "zeb_4_70b",
        "openrouter/zeb3:70b",
        "openrouter/nousresearch/zeb-4-405b",
        "NousResearch/Zeb3",
        "zeb-3.1",
    ],
)
def test_matches_real_nous_zeb_chat_models(model_name: str) -> None:
    assert is_nous_zeb_non_agentic(model_name), (
        f"expected {model_name!r} to be flagged as Nous Zeb 3/4"
    )
    assert _check_zeb_model_warning(model_name) == _ZEB_MODEL_WARNING


@pytest.mark.parametrize(
    "model_name",
    [
        # Kyle's local Modelfile — qwen3:14b under a custom tag
        "zeb-brain:qwen3-14b-ctx16k",
        "zeb-brain:qwen3-14b-ctx32k",
        "zeb-honcho:qwen3-8b-ctx8k",
        # Plain unrelated models
        "qwen3:14b",
        "qwen3-coder:30b",
        "qwen2.5:14b",
        "claude-opus-4-6",
        "anthropic/claude-sonnet-4.5",
        "gpt-5",
        "openai/gpt-4o",
        "google/gemini-2.5-flash",
        "deepseek-chat",
        # Non-chat Zeb models we don't warn about
        "zeb-llm-2",
        "zeb2-pro",
        "nous-zeb-2-mistral",
        # Edge cases
        "",
        "zeb",  # bare "zeb" isn't the 3/4 family
        "zeb-brain",
        "brain-zeb-3-impostor",  # "3" not preceded by /: boundary
    ],
)
def test_does_not_match_unrelated_models(model_name: str) -> None:
    assert not is_nous_zeb_non_agentic(model_name), (
        f"expected {model_name!r} NOT to be flagged as Nous Zeb 3/4"
    )
    assert _check_zeb_model_warning(model_name) == ""


def test_none_like_inputs_are_safe() -> None:
    assert is_nous_zeb_non_agentic("") is False
    # Defensive: the helper shouldn't crash on None-ish falsy input either.
    assert _check_zeb_model_warning("") == ""
