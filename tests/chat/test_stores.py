"""Tests for zeb_chat.stores (ApiKeyStore, SessionStore)."""

from __future__ import annotations

import zeb_constants
from zeb_chat.stores import ApiKeyStore, SessionStore


def _point_home(monkeypatch, tmp_path):
    monkeypatch.setattr(zeb_constants, "get_zeb_home", lambda: tmp_path)


def test_api_key_store_roundtrip(monkeypatch, tmp_path):
    _point_home(monkeypatch, tmp_path)
    store = ApiKeyStore()
    created = store.add("supersecretkey123456", "prod")
    assert created["label"] == "prod"
    assert created["masked"] == "supe…3456"
    assert "key" not in created  # public view never leaks the raw key

    listed = store.list()
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]
    assert "key" not in listed[0]
    assert listed[0]["masked"] == "supe…3456"

    assert store.delete(created["id"]) is True
    assert store.list() == []
    assert store.delete("nope") is False


def test_api_key_store_short_key_mask(monkeypatch, tmp_path):
    _point_home(monkeypatch, tmp_path)
    created = ApiKeyStore().add("abc", "short")
    assert created["masked"] == "•••"


def test_session_store_roundtrip(monkeypatch, tmp_path):
    _point_home(monkeypatch, tmp_path)
    store = SessionStore()
    session = store.create()
    sid = session["id"]
    assert session["title"] == "New chat"
    assert session["messages"] == []

    assert store.append(sid, "user", "Hello there world") is True
    assert store.append(sid, "assistant", "Hi!") is True

    full = store.get(sid)
    assert len(full["messages"]) == 2
    assert full["messages"][0]["role"] == "user"
    # Title derived from first user message.
    assert full["title"] == "Hello there world"

    listed = store.list()
    assert len(listed) == 1
    assert listed[0]["message_count"] == 2
    assert "messages" not in listed[0]

    assert store.delete(sid) is True
    assert store.get(sid) is None
    assert store.list() == []


def test_session_append_missing(monkeypatch, tmp_path):
    _point_home(monkeypatch, tmp_path)
    assert SessionStore().append("missing", "user", "x") is False


def test_fail_open_on_bad_dir(monkeypatch, tmp_path):
    # Point the store at a path where the "file" is actually a directory,
    # making reads/writes fail — everything should fail-open.
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "chat").mkdir()
    (bad / "chat" / "api_keys.json").mkdir()  # a dir where a file is expected
    monkeypatch.setattr(zeb_constants, "get_zeb_home", lambda: bad)

    store = ApiKeyStore()
    assert store.list() == []  # unreadable -> []
    # add should not raise even though write fails
    result = store.add("keythatwontsave", "x")
    assert isinstance(result, dict)

    # SessionStore listing on a missing dir -> []
    monkeypatch.setattr(zeb_constants, "get_zeb_home", lambda: tmp_path / "nowhere")
    assert SessionStore().list() == []
    assert SessionStore().get("x") is None
