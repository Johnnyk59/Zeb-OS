"""Tests for proactive bundled-skill activation (agent/proactive_discovery.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.proactive_discovery import find_and_enable_matching_skill


_SKILLS = [
    {"name": "docker-compose-ops", "description": "Manage docker compose services", "category": "devops"},
    {"name": "poetry-writing", "description": "Write rhyming poems and verse", "category": "creative"},
    {"name": "already-enabled-skill", "description": "docker container basics", "category": "devops"},
]


@pytest.fixture
def config():
    return {"skills": {"disabled": ["docker-compose-ops", "poetry-writing"]}}


def _patch_skills(monkeypatch, skills=_SKILLS):
    monkeypatch.setattr(
        "zeb_cli.skills_config._list_all_skills", lambda: list(skills)
    )


class TestFindAndEnableMatchingSkill:
    def test_no_disabled_skills_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "zeb_cli.skills_config.get_disabled_skills", lambda config, platform=None: set()
        )
        assert find_and_enable_matching_skill("docker", {}) is None

    def test_strong_match_is_enabled_and_returned(self, monkeypatch, config):
        _patch_skills(monkeypatch)
        saved = {}
        monkeypatch.setattr(
            "zeb_cli.skills_config.save_disabled_skills",
            lambda cfg, disabled, platform=None: saved.update(disabled=disabled),
        )

        result = find_and_enable_matching_skill("manage my docker compose services", config)

        assert result is not None
        assert result["name"] == "docker-compose-ops"
        # The matched skill was removed (enabled) from the saved disabled set;
        # the unrelated one stays disabled.
        assert "docker-compose-ops" not in saved["disabled"]
        assert "poetry-writing" in saved["disabled"]

    def test_only_considers_disabled_skills(self, monkeypatch, config):
        # "already-enabled-skill" scores highest for "docker" but isn't in
        # the disabled set, so it must never be touched/returned.
        _patch_skills(monkeypatch)
        saved = {}
        monkeypatch.setattr(
            "zeb_cli.skills_config.save_disabled_skills",
            lambda cfg, disabled, platform=None: saved.update(disabled=disabled),
        )
        result = find_and_enable_matching_skill("docker", config)
        if result is not None:
            assert result["name"] != "already-enabled-skill"

    def test_no_query_tokens_returns_none(self, monkeypatch, config):
        _patch_skills(monkeypatch)
        assert find_and_enable_matching_skill("   ", config) is None

    def test_weak_unrelated_query_returns_none(self, monkeypatch, config):
        _patch_skills(monkeypatch)
        assert find_and_enable_matching_skill("xyzzy nonsense qwerty", config) is None

    def test_save_failure_returns_none_not_raises(self, monkeypatch, config):
        _patch_skills(monkeypatch)
        monkeypatch.setattr(
            "zeb_cli.skills_config.save_disabled_skills",
            MagicMock(side_effect=OSError("disk full")),
        )
        result = find_and_enable_matching_skill("docker compose", config)
        assert result is None
