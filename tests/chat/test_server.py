"""Tests for the zeb_chat FastAPI server.

The agent runner is monkeypatched so no real model is invoked.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from zeb_chat.server import create_app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(
        "zeb_chat.agent_runner.run_chat_turn",
        lambda *a, **k: "hello from zeb",
    )
    app = create_app()
    app.state.api_key = "testkey"
    return TestClient(app)


def test_health_no_auth(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_index_returns_html_with_key_gate(client):
    res = client.get("/")
    assert res.status_code == 200
    body = res.text
    assert "Enter your API key" in body
    assert "zeb_chat_key" in body


def test_chat_with_valid_bearer_key(client):
    res = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer testkey"},
        json={"message": "hi"},
    )
    assert res.status_code == 200
    assert res.json() == {"reply": "hello from zeb"}


def test_chat_with_x_api_key_header(client):
    res = client.post(
        "/api/chat",
        headers={"X-API-Key": "testkey"},
        json={"message": "hi"},
    )
    assert res.status_code == 200
    assert res.json() == {"reply": "hello from zeb"}


def test_chat_wrong_key_401(client):
    res = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer nope"},
        json={"message": "hi"},
    )
    assert res.status_code == 401
    assert res.json() == {"error": "invalid or missing API key"}


def test_chat_missing_key_401(client):
    res = client.post("/api/chat", json={"message": "hi"})
    assert res.status_code == 401


def test_chat_empty_message_400(client):
    res = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer testkey"},
        json={"message": "   "},
    )
    assert res.status_code == 400
