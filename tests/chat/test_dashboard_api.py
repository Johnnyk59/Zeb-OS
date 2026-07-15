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


def test_models_shape(client, monkeypatch):
    # With no provider connected, the local backbone is the fallback default
    # and is present as a background option.
    monkeypatch.setattr(
        "zeb_chat.dashboard_api._connected_provider_ids", lambda: {"local-model"}
    )
    monkeypatch.setattr(
        "zeb_chat.dashboard_api.get_env_value_prefer_dotenv", lambda k: "", raising=False
    )
    res = client.get("/api/models", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["available"], list)
    assert isinstance(body["groups"], list)
    assert body["local_available"] is True
    first = body["available"][0]
    assert first["id"] == "local"
    assert first["local"] is True
    assert first.get("background") is True


def test_detect_provider_from_key():
    from zeb_chat.dashboard_api import _detect_provider_from_key

    assert _detect_provider_from_key("sk-ant-abc123") == "anthropic"
    assert _detect_provider_from_key("sk-or-xyz") == "openrouter"
    assert _detect_provider_from_key("AIzaSyABC") == "google"
    assert _detect_provider_from_key("gsk_abc") == "groq"
    assert _detect_provider_from_key("xai-abc") == "xai"
    assert _detect_provider_from_key("sk-proj-abc") == "openai"
    assert _detect_provider_from_key("random") == ""


def test_add_key_connects_provider_and_groups_models(client, tmp_path, monkeypatch):
    monkeypatch.setenv("ZEB_HOME", str(tmp_path))
    # Add an Anthropic-looking key: detected, connected, models fetched.
    r = client.post(
        "/api/keys", headers=AUTH, json={"key": "sk-ant-" + "x" * 40, "label": "claude"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "anthropic"
    assert isinstance(body["models"], list) and body["models"]  # at least the default

    # /api/models now reports the provider as connected, default a provider
    # model (NOT local), and groups the provider with its models.
    d = client.get("/api/models", headers=AUTH).json()
    assert d["connected"] is True
    assert d["default"].startswith("anthropic/")
    provs = {g["provider"] for g in d["groups"]}
    assert "anthropic" in provs
    # local is still available as a background option
    assert any(m.get("local") for m in d["available"])


def test_skills_stacks(client):
    res = client.get("/api/skills", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["skills"], list)
    assert isinstance(body["stacks"], list)
    # Every skill carries a stack label; every stack in the summary is a
    # {name, count} dict.
    for s in body["skills"]:
        assert "stack" in s
    for st in body["stacks"]:
        assert "name" in st and "count" in st


def test_diagnose_shape(client):
    res = client.get("/api/diagnose", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["checks"], list)
    assert body["offline"] is True
    assert body["overall"] in ("ok", "degraded", "critical", "unknown")
    # Every check is {component, status, message, repaired}.
    for c in body["checks"]:
        assert {"component", "status", "message", "repaired"} <= set(c)
        assert c["status"] in ("ok", "degraded", "critical")


def test_diagnose_requires_key(client):
    assert client.get("/api/diagnose").status_code == 401
    assert client.post("/api/diagnose/repair").status_code == 401


def test_diagnose_repair_runs(client):
    res = client.post("/api/diagnose/repair", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert body["offline"] is True
    assert isinstance(body["summary"], dict)


def test_localmodel_shape(client):
    res = client.get("/api/localmodel", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    # Identity + live-stat fields the dashboard panel binds to.
    for key in (
        "name", "provider", "loaded", "ready", "cpu_percent",
        "ram", "download", "events", "active",
    ):
        assert key in body
    assert body["provider"] == "local-model"
    assert isinstance(body["events"], list)
    # Out of the box (no weights on disk) the model is not ready/loaded.
    assert body["loaded"] is False
    # Name is derived from the configured/default repo (Phi-3 by default).
    assert isinstance(body["name"], str) and body["name"]


def test_localmodel_requires_key(client):
    assert client.get("/api/localmodel").status_code == 401


def test_voice_status_shape(client):
    res = client.get("/api/voice/status", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert body["engine"] in ("piper", "browser")
    assert body["offline"] is True


def test_voice_speak_falls_back_to_browser(client):
    # With no Piper voice installed, the server returns 204 to signal the
    # client should use its own speech engine.
    res = client.post("/api/voice/speak", headers=AUTH, json={"text": "hello"})
    assert res.status_code == 204


def test_voice_speak_missing_text(client):
    res = client.post("/api/voice/speak", headers=AUTH, json={})
    assert res.status_code == 400


def test_identity_lifecycle(client):
    # Fresh: not onboarded.
    res = client.get("/api/identity", headers=AUTH)
    assert res.status_code == 200
    assert res.json()["onboarded"] is False

    res = client.post(
        "/api/identity",
        headers=AUTH,
        json={"who_am_i": "Johnny", "who_are_you": "Zeb", "mission": "Build"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["onboarded"] is True
    assert body["who_am_i"] == "Johnny"
    assert body["mission"] == "Build"

    # Persisted across a fresh read.
    assert client.get("/api/identity", headers=AUTH).json()["who_are_you"] == "Zeb"


def test_identity_requires_key(client):
    assert client.get("/api/identity").status_code == 401
    assert client.post("/api/identity").status_code == 401


def test_repos_lifecycle(client):
    # Empty to start.
    assert client.get("/api/repos", headers=AUTH).json()["repos"] == []

    res = client.post(
        "/api/repos",
        headers=AUTH,
        json={
            "full_name": "rhasspy/piper",
            "description": "Local neural TTS",
            "stars": 11000,
            "language": "C++",
        },
    )
    assert res.status_code == 200
    created = res.json()
    assert created["full_name"] == "rhasspy/piper"
    rid = created["id"]

    repos = client.get("/api/repos", headers=AUTH).json()["repos"]
    assert len(repos) == 1

    # Search filters by name.
    assert len(client.get("/api/repos", headers=AUTH, params={"q": "piper"}).json()["repos"]) == 1
    assert client.get("/api/repos", headers=AUTH, params={"q": "nomatch"}).json()["repos"] == []

    # De-dupe by full_name.
    client.post("/api/repos", headers=AUTH, json={"full_name": "rhasspy/piper"})
    assert len(client.get("/api/repos", headers=AUTH).json()["repos"]) == 1

    assert client.delete(f"/api/repos/{rid}", headers=AUTH).json() == {"ok": True}
    assert client.get("/api/repos", headers=AUTH).json()["repos"] == []


def test_repos_add_requires_full_name(client):
    res = client.post("/api/repos", headers=AUTH, json={"description": "x"})
    assert res.status_code == 400


def test_repos_scan_requires_query(client):
    res = client.post("/api/repos/scan", headers=AUTH, json={})
    assert res.status_code == 400


def test_repos_requires_key(client):
    assert client.get("/api/repos").status_code == 401


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


# --------------------------------------------------------------------------
# Filesystem write-guard (P0-1): refuse code-exec-grade write targets
# --------------------------------------------------------------------------
def test_write_guard_blocks_shell_rc(client, tmp_path):
    rc = tmp_path / ".bashrc"
    res = client.post(
        "/api/files/write", headers=AUTH, json={"path": str(rc), "content": "evil"}
    )
    assert res.status_code == 403
    assert not rc.exists()


def test_write_guard_blocks_ssh_dir(client, tmp_path):
    key = tmp_path / ".ssh" / "authorized_keys"
    res = client.post(
        "/api/files/write", headers=AUTH, json={"path": str(key), "content": "ssh-rsa evil"}
    )
    assert res.status_code == 403
    assert not key.exists()


def test_write_guard_blocks_etc(client):
    res = client.post(
        "/api/files/write", headers=AUTH, json={"path": "/etc/cron.d/pwn", "content": "* * * * * root sh"}
    )
    assert res.status_code == 403


def test_write_guard_blocks_git_hook(client, tmp_path):
    hook = tmp_path / "repo" / ".git" / "hooks" / "post-checkout"
    res = client.post(
        "/api/files/write", headers=AUTH, json={"path": str(hook), "content": "#!/bin/sh\nevil"}
    )
    assert res.status_code == 403


def test_write_guard_allows_normal_file(client, tmp_path):
    ok = tmp_path / "notes" / "todo.md"
    ok.parent.mkdir(parents=True)
    res = client.post(
        "/api/files/write", headers=AUTH, json={"path": str(ok), "content": "hello"}
    )
    assert res.status_code == 200 and res.json()["ok"] is True
    assert ok.read_text() == "hello"


def test_files_jail_confines_all_endpoints(client, tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "inside.txt").write_text("ok")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    monkeypatch.setenv("ZEB_CHAT_FILES_ROOT", str(root))

    # Inside the jail: allowed.
    assert client.get("/api/files", headers=AUTH, params={"path": str(root)}).status_code == 200
    assert (
        client.get("/api/files/read", headers=AUTH, params={"path": str(root / "inside.txt")}).json()["content"]
        == "ok"
    )
    # Outside the jail: refused on read and write.
    assert client.get("/api/files/read", headers=AUTH, params={"path": str(outside)}).status_code == 403
    assert (
        client.post("/api/files/write", headers=AUTH, json={"path": str(outside), "content": "x"}).status_code
        == 403
    )


# --------------------------------------------------------------------------
# Model info (/status command backing endpoint) + self-awareness
# --------------------------------------------------------------------------
def test_modelinfo_shape(client):
    res = client.get("/api/modelinfo", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    for key in (
        "name", "backbone", "provider", "context_window",
        "context_window_human", "config_path",
    ):
        assert key in body
    assert body["provider"] == "local-model"
    assert isinstance(body["context_window"], int)
    # Human label is derived from the token count (e.g. 65536 -> "64K tokens").
    assert isinstance(body["context_window_human"], str) and body["context_window_human"]


def test_modelinfo_requires_key(client):
    assert client.get("/api/modelinfo").status_code == 401


def test_human_ctx_labels():
    from zeb_chat.dashboard_api import _human_ctx

    assert _human_ctx(65536) == "64K tokens"
    assert _human_ctx(131072) == "128K tokens"
    assert _human_ctx(0) == "unknown"


# --------------------------------------------------------------------------
# Files default root prefers /opt, falls back to cwd
# --------------------------------------------------------------------------
def test_default_files_root_prefers_opt(monkeypatch):
    from zeb_chat import dashboard_api

    monkeypatch.setattr(dashboard_api.os.path, "isdir", lambda p: p == "/opt")
    assert dashboard_api._default_files_root() == "/opt"


def test_default_files_root_falls_back_to_cwd(monkeypatch):
    from zeb_chat import dashboard_api

    monkeypatch.setattr(dashboard_api.os.path, "isdir", lambda p: False)
    monkeypatch.setattr(dashboard_api.os, "getcwd", lambda: "/somewhere")
    assert dashboard_api._default_files_root() == "/somewhere"


# --------------------------------------------------------------------------
# Anthropic subscription connect / status / disconnect
# --------------------------------------------------------------------------
def test_anthropic_lifecycle(client, tmp_path, monkeypatch):
    # Isolate env writes to the test home (save_env_value writes <home>/.env).
    monkeypatch.setenv("ZEB_HOME", str(tmp_path))

    # Not connected initially.
    res = client.get("/api/anthropic/status", headers=AUTH)
    assert res.status_code == 200
    assert res.json()["connected"] is False

    # Missing / too-short tokens are rejected.
    assert client.post("/api/anthropic/connect", headers=AUTH, json={}).status_code == 400
    assert (
        client.post("/api/anthropic/connect", headers=AUTH, json={"token": "short"}).status_code
        == 400
    )

    # A plausible OAuth token connects and is reported (masked).
    token = "sk-ant-oat01-" + "x" * 40
    res = client.post("/api/anthropic/connect", headers=AUTH, json={"token": token})
    assert res.status_code == 200 and res.json()["connected"] is True
    st = client.get("/api/anthropic/status", headers=AUTH).json()
    assert st["connected"] is True and st["masked"]

    # Once connected it is surfaced as a selectable model in the chat dropdown.
    models = client.get("/api/models", headers=AUTH).json()
    assert any(m.get("provider") == "anthropic" for m in models["available"])

    # Disconnect clears it.
    assert client.post("/api/anthropic/disconnect", headers=AUTH).json()["connected"] is False
    assert client.get("/api/anthropic/status", headers=AUTH).json()["connected"] is False


def test_anthropic_requires_key(client):
    assert client.get("/api/anthropic/status").status_code == 401
    assert client.post("/api/anthropic/connect").status_code == 401
    assert client.post("/api/anthropic/disconnect").status_code == 401


# --------------------------------------------------------------------------
# First-run provider onboarding
# --------------------------------------------------------------------------
def test_list_providers_shape(client):
    res = client.get("/api/providers", headers=AUTH)
    assert res.status_code == 200
    providers = res.json()["providers"]
    assert len(providers) == 10  # top ten
    ids = {p["id"] for p in providers}
    assert {"openai", "anthropic", "google", "together"} <= ids
    for p in providers:
        assert p["id"] and p["name"]


def test_onboard_provider_saves_key_and_connects(client, tmp_path, monkeypatch):
    monkeypatch.setenv("ZEB_HOME", str(tmp_path))
    # Unknown provider / missing key are rejected.
    assert client.post("/api/onboard/provider", headers=AUTH, json={"provider": "nope", "key": "x"}).status_code == 400
    assert client.post("/api/onboard/provider", headers=AUTH, json={"provider": "openai", "key": ""}).status_code == 400

    res = client.post(
        "/api/onboard/provider", headers=AUTH, json={"provider": "openai", "key": "sk-test-123456"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True and body["provider"] == "openai"
    assert isinstance(body["default_model"], str) and body["default_model"]
    # Persisted to the provider's standard env var.
    import os

    assert os.environ.get("OPENAI_API_KEY") == "sk-test-123456"


def test_onboard_provider_requires_key(client):
    assert client.get("/api/providers").status_code == 401
    assert client.post("/api/onboard/provider").status_code == 401


# ---------------------------------------------------------------------------
# Agents registry (top-bar buttons + self-registered dashboards)
# ---------------------------------------------------------------------------
def test_agents_seed_and_register(client):
    # Auth required.
    assert client.get("/api/agents").status_code == 401

    # Seeds the three default agents, none wired yet.
    res = client.get("/api/agents", headers=AUTH)
    assert res.status_code == 200
    agents = {a["id"]: a for a in res.json()["agents"]}
    assert set(["quant", "jewelry", "socials"]).issubset(agents)
    assert [agents[key]["label"] for key in ("quant", "socials", "jewelry")] == [
        "Quant Bot",
        "Socials Agent",
        "Jew",
    ]
    assert agents["quant"]["dashboard_url"] == ""

    # Zeb registers a dashboard for quant at runtime.
    res = client.post(
        "/api/agents/quant",
        headers=AUTH,
        json={"dashboard_url": "http://localhost:9200/quant", "status": "ready"},
    )
    assert res.status_code == 200 and res.json()["ok"] is True

    agents = {a["id"]: a for a in client.get("/api/agents", headers=AUTH).json()["agents"]}
    assert agents["quant"]["dashboard_url"] == "http://localhost:9200/quant"
    assert agents["quant"]["status"] == "ready"


# ---------------------------------------------------------------------------
# Shared cross-provider context
# ---------------------------------------------------------------------------
def test_shared_context_roundtrip(client):
    assert client.get("/api/context").status_code == 401

    from zeb_chat.stores import SharedContextStore

    SharedContextStore().append("user", "hello from one session", provider="anthropic")
    res = client.get("/api/context", headers=AUTH)
    assert res.status_code == 200
    ctx = res.json()["context"]
    assert ctx and ctx[-1]["content"] == "hello from one session"
    assert ctx[-1]["provider"] == "anthropic"
