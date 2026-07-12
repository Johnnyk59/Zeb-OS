"""Tests for the in-process llama.cpp adapter (agent/llama_cpp_adapter.py)."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from agent.llama_cpp_adapter import (
    LlamaCppClient,
    _translate_response,
    _translate_stream_chunk,
)


def _fake_llama_module(fake_llama_instance):
    """Build a stand-in ``llama_cpp`` module exposing only ``Llama``."""
    mod = types.ModuleType("llama_cpp")
    mod.Llama = MagicMock(return_value=fake_llama_instance)
    return mod


@pytest.fixture(autouse=True)
def _reset_singleton():
    import agent.llama_cpp_adapter as m

    m._loaded_model = None
    m._loaded_model_path = None
    m._loaded_model_key = None
    yield
    m._loaded_model = None
    m._loaded_model_path = None
    m._loaded_model_key = None


class TestSingletonCacheKey:
    """The process-wide model must key on (path, n_ctx), not path alone."""

    def test_same_path_same_ctx_reuses(self, monkeypatch):
        import agent.llama_cpp_adapter as m

        inst = MagicMock()
        fake = _fake_llama_module(inst)
        monkeypatch.setattr(m, "_get_llama_cpp_sdk", lambda: fake)
        a = m._load_model("/w.gguf", n_ctx=65536, n_gpu_layers=0)
        b = m._load_model("/w.gguf", n_ctx=65536, n_gpu_layers=0)
        assert a is b
        assert fake.Llama.call_count == 1  # loaded once

    def test_same_path_different_ctx_reloads(self, monkeypatch):
        import agent.llama_cpp_adapter as m

        fake = _fake_llama_module(MagicMock())
        monkeypatch.setattr(m, "_get_llama_cpp_sdk", lambda: fake)
        m._load_model("/w.gguf", n_ctx=4096, n_gpu_layers=0)
        m._load_model("/w.gguf", n_ctx=65536, n_gpu_layers=0)
        # A different n_ctx must NOT silently reuse the 4096 instance.
        assert fake.Llama.call_count == 2
        _, kwargs = fake.Llama.call_args
        assert kwargs["n_ctx"] == 65536


class TestTranslateResponse:
    def test_translates_plain_message(self):
        raw = {
            "id": "cmpl-1",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hi there"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
        result = _translate_response(raw, "zeb-local")
        assert result.model == "zeb-local"
        assert result.choices[0].message.role == "assistant"
        assert result.choices[0].message.content == "hi there"
        assert result.choices[0].message.tool_calls is None
        assert result.choices[0].finish_reason == "stop"
        assert result.usage.total_tokens == 8

    def test_translates_tool_calls(self):
        raw = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
        result = _translate_response(raw, "zeb-local")
        tc = result.choices[0].message.tool_calls[0]
        assert tc.id == "call_1"
        assert tc.function.name == "read_file"
        assert tc.function.arguments == '{"path": "a.py"}'

    def test_missing_usage_defaults_to_zero(self):
        result = _translate_response({"choices": []}, "zeb-local")
        assert result.usage.prompt_tokens == 0
        assert result.usage.total_tokens == 0


class TestTranslateStreamChunk:
    def test_translates_delta(self):
        raw = {"choices": [{"index": 0, "delta": {"content": "tok"}, "finish_reason": None}]}
        chunk = _translate_stream_chunk(raw, "zeb-local")
        assert chunk.choices[0].delta.content == "tok"
        assert chunk.choices[0].finish_reason is None


class TestLlamaCppClient:
    def test_create_chat_completion_non_streaming(self, monkeypatch):
        fake_llama = MagicMock()
        fake_llama.create_chat_completion.return_value = {
            "id": "cmpl-1",
            "choices": [{"message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
            "usage": {},
        }
        monkeypatch.setitem(sys.modules, "llama_cpp", _fake_llama_module(fake_llama))

        client = LlamaCppClient(model_path="/fake/model.gguf")
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": "hi"}],
        )
        assert response.choices[0].message.content == "hello"
        fake_llama.create_chat_completion.assert_called_once()

    def test_reuses_loaded_model_for_same_path(self, monkeypatch):
        fake_llama = MagicMock()
        fake_llama.create_chat_completion.return_value = {"choices": []}
        llama_mod = _fake_llama_module(fake_llama)
        monkeypatch.setitem(sys.modules, "llama_cpp", llama_mod)

        LlamaCppClient(model_path="/fake/model.gguf")
        LlamaCppClient(model_path="/fake/model.gguf")
        # Llama(...) constructor should only be invoked once — the second
        # client reuses the process-wide singleton (see _load_model).
        assert llama_mod.Llama.call_count == 1

    def test_ping_success(self, monkeypatch):
        fake_llama = MagicMock()
        fake_llama.create_chat_completion.return_value = {"choices": [{"message": {"content": "pong"}}]}
        monkeypatch.setitem(sys.modules, "llama_cpp", _fake_llama_module(fake_llama))

        client = LlamaCppClient(model_path="/fake/model.gguf")
        assert client.ping() is True

    def test_ping_failure_returns_false(self, monkeypatch):
        fake_llama = MagicMock()
        fake_llama.create_chat_completion.side_effect = RuntimeError("boom")
        monkeypatch.setitem(sys.modules, "llama_cpp", _fake_llama_module(fake_llama))

        client = LlamaCppClient(model_path="/fake/model.gguf")
        assert client.ping() is False

    def test_missing_sdk_raises_clear_error(self, monkeypatch):
        # Force the "not installed" branch directly rather than trying to
        # fake package absence via sys.modules — llama-cpp-python may or
        # may not actually be installed in the test environment, and this
        # is the one path _get_llama_cpp_sdk itself is responsible for.
        monkeypatch.setattr(
            "agent.llama_cpp_adapter._get_llama_cpp_sdk", lambda: None
        )
        with pytest.raises(Exception, match="llama-cpp-python is not installed"):
            LlamaCppClient(model_path="/fake/model.gguf")
