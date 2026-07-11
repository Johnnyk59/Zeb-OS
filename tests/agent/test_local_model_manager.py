"""Tests for local GGUF weight resolution/download (agent/local_model_manager.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.local_model_manager import (
    LocalModelUnavailable,
    ensure_local_model_weights,
    get_local_model_path,
)


@pytest.fixture(autouse=True)
def _zeb_home(tmp_path, monkeypatch):
    monkeypatch.setattr("zeb_constants.get_zeb_home", lambda: tmp_path)
    yield tmp_path


class TestGetLocalModelPath:
    def test_explicit_path_returns_when_file_exists(self, tmp_path):
        gguf = tmp_path / "custom.gguf"
        gguf.write_bytes(b"fake")
        config = {"local_model": {"path": str(gguf)}}
        assert get_local_model_path(config) == gguf

    def test_explicit_path_returns_none_when_missing(self, tmp_path):
        config = {"local_model": {"path": str(tmp_path / "nope.gguf")}}
        assert get_local_model_path(config) is None

    def test_no_cache_returns_none(self):
        assert get_local_model_path({}) is None

    def test_finds_cached_download(self, tmp_path):
        # Uses the module defaults (Phi-3-mini / q4) so the test tracks the
        # configured default instead of hardcoding a model name.
        from agent.local_model_manager import (
            DEFAULT_LOCAL_MODEL_QUANT,
            DEFAULT_LOCAL_MODEL_REPO,
        )

        target_dir = (
            tmp_path / "models" / "gguf" / DEFAULT_LOCAL_MODEL_REPO.replace("/", "__")
        )
        target_dir.mkdir(parents=True)
        (target_dir / f"model-{DEFAULT_LOCAL_MODEL_QUANT}.gguf").write_bytes(b"fake")
        assert get_local_model_path({}) is not None


class TestEnsureLocalModelWeights:
    def test_explicit_path_missing_raises(self, tmp_path):
        config = {"local_model": {"path": str(tmp_path / "missing.gguf")}}
        with pytest.raises(LocalModelUnavailable, match="doesn't exist"):
            ensure_local_model_weights(config)

    def test_explicit_path_present_returns_it(self, tmp_path):
        gguf = tmp_path / "custom.gguf"
        gguf.write_bytes(b"fake")
        config = {"local_model": {"path": str(gguf)}}
        assert ensure_local_model_weights(config) == gguf

    def test_missing_hf_hub_raises_clear_error(self, monkeypatch):
        monkeypatch.setattr(
            "agent.local_model_manager._get_hf_hub_sdk", lambda: None
        )
        with pytest.raises(LocalModelUnavailable, match="huggingface_hub is not installed"):
            ensure_local_model_weights({})

    def test_downloads_and_caches(self, tmp_path, monkeypatch):
        fake_hub = MagicMock()
        fake_hub.list_repo_files.return_value = [
            "README.md",
            "Hermes-3-Llama-3.2-3B.Q4_K_M.gguf",
            "Hermes-3-Llama-3.2-3B.Q8_0.gguf",
        ]
        downloaded_path = tmp_path / "models" / "gguf" / "repo" / "Hermes-3-Llama-3.2-3B.Q4_K_M.gguf"
        fake_hub.hf_hub_download.return_value = str(downloaded_path)
        monkeypatch.setattr(
            "agent.local_model_manager._get_hf_hub_sdk", lambda: fake_hub
        )

        progress = []
        result = ensure_local_model_weights({}, progress_callback=progress.append)

        assert result == downloaded_path
        fake_hub.hf_hub_download.assert_called_once()
        _, kwargs = fake_hub.hf_hub_download.call_args
        assert kwargs["filename"] == "Hermes-3-Llama-3.2-3B.Q4_K_M.gguf"
        assert progress  # progress callback was invoked at least once

    def test_no_matching_quant_raises(self, monkeypatch):
        fake_hub = MagicMock()
        fake_hub.list_repo_files.return_value = ["README.md", "model.Q8_0.gguf"]
        monkeypatch.setattr(
            "agent.local_model_manager._get_hf_hub_sdk", lambda: fake_hub
        )
        with pytest.raises(LocalModelUnavailable, match="GGUF file found"):
            ensure_local_model_weights({})

    def test_download_failure_wrapped_in_clear_error(self, monkeypatch):
        fake_hub = MagicMock()
        fake_hub.list_repo_files.return_value = ["model.Q4_K_M.gguf"]
        fake_hub.hf_hub_download.side_effect = OSError("network unreachable")
        monkeypatch.setattr(
            "agent.local_model_manager._get_hf_hub_sdk", lambda: fake_hub
        )
        with pytest.raises(LocalModelUnavailable, match="Download of .* failed"):
            ensure_local_model_weights({})
