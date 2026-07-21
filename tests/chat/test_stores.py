"""Tests for zeb_chat.stores (ApiKeyStore, SessionStore)."""

from __future__ import annotations

import zeb_constants
from zeb_chat.stores import (
    ApiKeyStore,
    ChannelStore,
    IdentityStore,
    RepoStore,
    SessionStore,
)


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


def test_repo_store_discovers_local_clone(monkeypatch, tmp_path):
    _point_home(monkeypatch, tmp_path)
    checkout = tmp_path / "workspace" / "quant-engine"
    git_dir = checkout / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/acme/quant-engine.git\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ZEB_REPO_ROOTS", str(tmp_path / "workspace"))
    RepoStore._last_discovery = 0

    store = RepoStore()
    assert store.sync_local_clones(force=True) == 1
    repo = store.list()[0]
    assert repo["full_name"] == "acme/quant-engine"
    assert repo["local_path"] == str(checkout.resolve())
    assert repo["source"] == "local-clone"


def test_api_key_store_short_key_mask(monkeypatch, tmp_path):
    _point_home(monkeypatch, tmp_path)
    created = ApiKeyStore().add("abc", "short")
    assert created["masked"] == "•••"


def test_channel_store_roundtrip(monkeypatch, tmp_path):
    _point_home(monkeypatch, tmp_path)
    store = ChannelStore()
    created = store.add("My Bot", "123456:AAAAtokenvaluehere", "telegram")
    assert created["name"] == "My Bot"
    assert created["kind"] == "telegram"
    assert "token" not in created  # public view never leaks the raw token
    assert created["masked"] == "1234…here"

    listed = store.list()
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]
    assert "token" not in listed[0]

    assert store.delete(created["id"]) is True
    assert store.list() == []
    assert store.delete("nope") is False


def test_identity_store_roundtrip(monkeypatch, tmp_path):
    _point_home(monkeypatch, tmp_path)
    store = IdentityStore()
    assert store.get()["onboarded"] is False
    # Identity is hardwired: even before onboarding, the preamble carries
    # Zeb's core (creator + unified-being framing).
    assert "Johnny Kowalski" in store.system_preamble()

    out = store.set({"who_am_i": "Johnny", "who_are_you": "Zeb", "mission": "Ship"})
    assert out["onboarded"] is True
    assert out["who_am_i"] == "Johnny"

    # Persisted + preamble now renders identity + agency framing.
    preamble = IdentityStore().system_preamble()
    assert "Johnny" in preamble and "Ship" in preamble
    assert "full agency" in preamble.lower()


def test_identity_store_explicit_skip(monkeypatch, tmp_path):
    _point_home(monkeypatch, tmp_path)
    # Skipping onboarding still marks it done so the modal doesn't re-appear.
    out = IdentityStore().set({"onboarded": True})
    assert out["onboarded"] is True


def test_repo_store_roundtrip(monkeypatch, tmp_path):
    _point_home(monkeypatch, tmp_path)
    store = RepoStore()
    assert store.list() == []

    entry = store.add(
        {"full_name": "rhasspy/piper", "description": "TTS", "stars": 9, "language": "C++"}
    )
    assert entry["full_name"] == "rhasspy/piper"
    assert entry["url"] == "https://github.com/rhasspy/piper"

    assert len(store.list()) == 1
    assert len(store.list(query="piper")) == 1
    assert store.list(query="nope") == []

    # De-dupe by full_name; no second entry created.
    store.add({"full_name": "rhasspy/piper"})
    assert len(store.list()) == 1

    # Missing full_name is rejected.
    assert store.add({"description": "x"}) is None

    assert store.delete(entry["id"]) is True
    assert store.list() == []
    assert store.delete("nope") is False


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
