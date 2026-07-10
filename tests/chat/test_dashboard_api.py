"""Tests for zeb_chat.dashboard_api router."""

from __future__ import annotations

import pytest
import zeb_constants
from fastapi import FastAPI
from fastapi.testclient import TestClient

from zeb_chat.dashboard_api import router


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(zeb_constants, "get_zeb_home", lambda: tmp_path)
    app = FastAPI()
    app.state.api_key = "testkey"
    app.include_router(router)
    return TestClient(app)


AUTH = {"Authorization": "Bearer testkey"}


def test_requires_key(client):
    res = client.get("/api/status")
    assert res.status_code == 401


def test_status_idle(client):
    res = client.get("/api/status", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "idle"
    assert body["active_turns"] == 0
    assert "updated_at" in body


def test_x_api_key_header(client):
    res = client.get("/api/status", headers={"X-API-Key": "testkey"})
    assert res.status_code == 200


def test_keys_lifecycle(client):
    # Empty key -> 400
    res = client.post("/api/keys", headers=AUTH, json={"key": "", "label": "x"})
    assert res.status_code == 400

    res = client.post(
        "/api/keys", headers=AUTH, json={"key": "abcdef123456ghijkl", "label": "prod"}
    )
    assert res.status_code == 200
    created = res.json()
    assert "key" not in created
    assert created["masked"] == "abcd…ijkl"
    kid = created["id"]

    res = client.get("/api/keys", headers=AUTH)
    keys = res.json()["keys"]
    assert len(keys) == 1
    assert "key" not in keys[0]

    res = client.delete(f"/api/keys/{kid}", headers=AUTH)
    assert res.json() == {"ok": True}
    assert client.get("/api/keys", headers=AUTH).json()["keys"] == []


def test_sessions_lifecycle(client):
    res = client.post("/api/sessions", headers=AUTH, json={})
    assert res.status_code == 200
    sid = res.json()["id"]

    res = client.post(
        f"/api/sessions/{sid}/messages",
        headers=AUTH,
        json={"role": "user", "content": "hi there"},
    )
    assert res.json() == {"ok": True}

    res = client.get(f"/api/sessions/{sid}", headers=AUTH)
    full = res.json()
    assert len(full["messages"]) == 1

    res = client.get("/api/sessions", headers=AUTH)
    sessions = res.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["message_count"] == 1

    res = client.get("/api/sessions/doesnotexist", headers=AUTH)
    assert res.status_code == 404

    res = client.delete(f"/api/sessions/{sid}", headers=AUTH)
    assert res.json() == {"ok": True}
    assert client.get("/api/sessions", headers=AUTH).json()["sessions"] == []


def test_files_list_and_read(client, tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    (d / "sub").mkdir()
    f = d / "hello.txt"
    f.write_text("hello world", encoding="utf-8")

    res = client.get("/api/files", headers=AUTH, params={"path": str(d)})
    body = res.json()
    assert body["path"] == str(d)
    assert body["parent"] == str(tmp_path)
    names = [e["name"] for e in body["entries"]]
    assert "sub" in names and "hello.txt" in names
    # dirs first
    assert body["entries"][0]["is_dir"] is True

    res = client.get("/api/files/read", headers=AUTH, params={"path": str(f)})
    body = res.json()
    assert body["content"] == "hello world"
    assert body["truncated"] is False


def test_files_read_binary(client, tmp_path):
    f = tmp_path / "bin"
    f.write_bytes(b"\x00\x01\x02")
    res = client.get("/api/files/read", headers=AUTH, params={"path": str(f)})
    assert res.json().get("binary") is True


def test_models_shape(client):
    res = client.get("/api/models", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert "current" in body
    assert isinstance(body["available"], list)


def test_cron_shape(client):
    res = client.get("/api/cron", headers=AUTH)
    assert res.status_code == 200
    assert isinstance(res.json()["jobs"], list)


def test_skills_shape(client):
    res = client.get("/api/skills", headers=AUTH)
    assert res.status_code == 200
    assert isinstance(res.json()["skills"], list)


def test_plugins_shape(client):
    res = client.get("/api/plugins", headers=AUTH)
    assert res.status_code == 200
    assert isinstance(res.json()["plugins"], list)


def test_channels_shape(client):
    res = client.get("/api/channels", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    tg = body["telegram"]
    assert "configured" in tg
    assert isinstance(tg["configured"], bool)
    assert "detail" in tg
    assert isinstance(body["channels"], list)


def test_channels_lifecycle(client):
    # Missing name/token -> 400
    res = client.post("/api/channels", headers=AUTH, json={"name": "", "token": ""})
    assert res.status_code == 400

    res = client.post(
        "/api/channels",
        headers=AUTH,
        json={"name": "My Bot", "token": "123456:AAAAtokenvaluehere"},
    )
    assert res.status_code == 200
    created = res.json()
    assert "token" not in created
    assert created["name"] == "My Bot"
    cid = created["id"]

    res = client.get("/api/channels", headers=AUTH)
    channels = res.json()["channels"]
    assert len(channels) == 1
    assert "token" not in channels[0]

    res = client.delete(f"/api/channels/{cid}", headers=AUTH)
    assert res.json() == {"ok": True}
    assert client.get("/api/channels", headers=AUTH).json()["channels"] == []


def test_files_write_roundtrip(client, tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("original", encoding="utf-8")

    res = client.post(
        "/api/files/write",
        headers=AUTH,
        json={"path": str(f), "content": "updated content"},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert f.read_text(encoding="utf-8") == "updated content"


def test_files_write_missing_path(client):
    res = client.post("/api/files/write", headers=AUTH, json={"content": "x"})
    assert res.status_code == 400
