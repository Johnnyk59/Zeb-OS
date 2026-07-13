"""Tests for the unified-Zeb identity, skill auto-categorization, and the
Zeb-writable live dashboard state."""

from __future__ import annotations

from pathlib import Path

from zeb_chat.skill_categorize import categorize, route
from zeb_chat.stores import (
    ZEB_CREATOR,
    ZEB_IDENTITY_PREAMBLE,
    DashboardStateStore,
    IdentityStore,
)


# ── identity ──────────────────────────────────────────────────────────────


def test_creator_hardwired():
    assert ZEB_CREATOR == "Johnny Kowalski"
    assert "Johnny Kowalski" in ZEB_IDENTITY_PREAMBLE


def test_identity_preamble_always_present(tmp_path: Path):
    # Even a fresh, never-onboarded identity carries the hardwired core.
    pre = IdentityStore(tmp_path).system_preamble()
    assert "Johnny Kowalski" in pre
    assert "one unified" in pre.lower()


def test_identity_layers_onboarding(tmp_path: Path):
    store = IdentityStore(tmp_path)
    store.set({"mission": "run the lab"})
    pre = store.system_preamble()
    assert "Johnny Kowalski" in pre  # core stays
    assert "run the lab" in pre  # onboarding layered on top


# ── skill auto-categorization ─────────────────────────────────────────────


def test_categorize_by_keyword():
    assert categorize("github-tools", "clone and manage git repos") == "development"
    assert categorize("tts-voice", "text to speech audio") == "media"
    assert categorize("vecdb", "vector database embeddings") == "ai-ml"


def test_categorize_keeps_valid_existing():
    assert categorize("x", "y", existing="finance") == "finance"


def test_categorize_default():
    assert categorize("mystery", "") == "general"


def test_route_sections():
    assert route({"full_name": "owner/repo"}) == "repos"
    assert route({"kind": "plugin"}) == "plugins"
    assert route({"name": "obsidian", "skill": True}) == "skills"


# ── live dashboard state ───────────────────────────────────────────────────


def test_dashboard_state_allowlist(tmp_path: Path):
    store = DashboardStateStore(tmp_path)
    out = store.update(
        {"brand": "ZEB", "pinned_note": "hi", "tagline": "one mind", "danger": "x"}
    )
    assert out["brand"] == "ZEB"
    assert out["pinned_note"] == "hi"
    assert out["tagline"] == "one mind"
    assert "danger" not in out  # non-allowlisted keys are dropped
    assert out["updated_at"] > 0


def test_dashboard_state_persists(tmp_path: Path):
    DashboardStateStore(tmp_path).update({"brand": "PRIME"})
    assert DashboardStateStore(tmp_path).get()["brand"] == "PRIME"
