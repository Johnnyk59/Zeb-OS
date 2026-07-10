"""Tests for zeb_chat.api_key resolution and verification."""

from __future__ import annotations

import stat

from zeb_chat import api_key as ak


def test_env_key_takes_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEB_CHAT_API_KEY", "env-secret")
    key, source = ak.resolve_or_create_api_key(zeb_home=tmp_path)
    assert key == "env-secret"
    assert source == "env"
    # No file should be written when env is used.
    assert not (tmp_path / "chat" / "api_key").exists()


def test_env_key_blank_falls_through(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEB_CHAT_API_KEY", "   ")
    key, source = ak.resolve_or_create_api_key(zeb_home=tmp_path)
    assert source == "generated"
    assert key


def test_generated_key_creates_file_0600(tmp_path, monkeypatch):
    monkeypatch.delenv("ZEB_CHAT_API_KEY", raising=False)
    key, source = ak.resolve_or_create_api_key(zeb_home=tmp_path)
    assert source == "generated"
    assert key
    key_file = tmp_path / "chat" / "api_key"
    assert key_file.exists()
    assert key_file.read_text().strip() == key
    mode = stat.S_IMODE(key_file.stat().st_mode)
    assert mode == 0o600


def test_file_key_persisted_and_reused(tmp_path, monkeypatch):
    monkeypatch.delenv("ZEB_CHAT_API_KEY", raising=False)
    first_key, first_source = ak.resolve_or_create_api_key(zeb_home=tmp_path)
    assert first_source == "generated"
    # Second call must read the same key from disk.
    second_key, second_source = ak.resolve_or_create_api_key(zeb_home=tmp_path)
    assert second_key == first_key
    assert second_source == "file"


def test_default_zeb_home_via_monkeypatch(tmp_path, monkeypatch):
    monkeypatch.delenv("ZEB_CHAT_API_KEY", raising=False)
    import zeb_constants

    monkeypatch.setattr(zeb_constants, "get_zeb_home", lambda: tmp_path)
    key, source = ak.resolve_or_create_api_key()
    assert source == "generated"
    assert (tmp_path / "chat" / "api_key").exists()
    assert key


def test_verify_key_true_false_empty():
    assert ak.verify_key("abc", "abc") is True
    assert ak.verify_key("abc", "xyz") is False
    assert ak.verify_key("", "abc") is False
    assert ak.verify_key("abc", "") is False
    assert ak.verify_key(None, "abc") is False
