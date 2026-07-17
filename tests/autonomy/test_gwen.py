"""Behavioral coverage for Gwen's private, restart-safe background brain."""

from __future__ import annotations

import logging
import stat
from pathlib import Path

from zeb_autonomy.base import BotContext
from zeb_autonomy.bots.gwen import GwenBot, GwenStore, _mentor_settings


def _context(
    home: Path,
    *,
    complete,
    notify,
    config: dict | None = None,
) -> BotContext:
    return BotContext(
        config=config or {"autonomy": {"gwen": {}}},
        zeb_home=home,
        log=logging.getLogger("test.gwen"),
        complete=complete,
        notify=notify,
    )


def test_store_is_private_wal_and_claims_are_process_safe(tmp_path: Path) -> None:
    first = GwenStore(tmp_path, now=100.0)
    second = GwenStore(tmp_path, now=100.0)

    claim = first.claim_due(now=100.0, lease_seconds=120.0)
    assert claim is not None
    assert claim.reflection_due is True
    assert claim.mentor_due is True
    assert second.claim_due(now=101.0, lease_seconds=120.0) is None

    first.release_claim(claim.token, now=102.0)
    assert second.claim_due(now=103.0, lease_seconds=120.0) is not None
    assert stat.S_IMODE(first.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(first.db_path.stat().st_mode) == 0o600


def test_due_times_survive_restart(tmp_path: Path) -> None:
    store = GwenStore(tmp_path, now=500.0)
    claim = store.claim_due(now=500.0, lease_seconds=120.0)
    assert claim is not None
    assert store.finish_attempt(
        claim.token,
        kind="reflection",
        status="unavailable",
        now=501.0,
        next_at=2_301.0,
    )
    assert store.finish_attempt(
        claim.token,
        kind="mentor",
        status="unconfigured",
        now=501.0,
        next_at=4_101.0,
    )
    store.release_claim(claim.token, now=501.0)

    restarted = GwenStore(tmp_path, now=600.0)
    assert restarted.claim_due(now=2_000.0, lease_seconds=120.0) is None
    due = restarted.claim_due(now=2_400.0, lease_seconds=120.0)
    assert due is not None
    assert due.reflection_due is True
    assert due.mentor_due is False


def test_bot_persists_private_reflection_and_mentor_without_notifying(
    tmp_path: Path,
) -> None:
    now = [1_000.0]
    notifications: list[str] = []
    local_prompts: list[str] = []
    mentor_calls: list[tuple[str, str]] = []

    def complete(prompt: str, **_kwargs) -> str:
        local_prompts.append(prompt)
        return '{"reflection":"I should tighten my next plan.","summary":"Plan carefully."}'

    def mentor(settings, messages) -> str:
        mentor_calls.append((settings.provider, messages[-1]["content"]))
        return "Choose one measurable learning task and verify it."

    ctx = _context(
        tmp_path,
        complete=complete,
        notify=lambda message, *_args, **_kwargs: notifications.append(message),
    )
    result = GwenBot(clock=lambda: now[0], mentor_complete=mentor).run(ctx)

    assert result.ok is True
    assert result.notify is False
    assert result.details == {"reflection": "ok", "mentor": "ok"}
    assert len(local_prompts) == 1
    assert mentor_calls and mentor_calls[0][0] == "auto"
    assert notifications == []

    messages = GwenStore(tmp_path).messages()
    assert [message["role"] for message in messages] == ["gwen", "mentor"]
    assert "Plan carefully" in GwenStore(tmp_path).state()["summary"]
    assert not (tmp_path / "state.db").exists()
    assert not (tmp_path / "chat").exists()
    assert not (tmp_path / "sessions").exists()


def test_bot_respects_private_cadence_and_skips_model_work_when_not_due(
    tmp_path: Path,
) -> None:
    now = [2_000.0]
    calls = 0

    def complete(*_args, **_kwargs) -> str:
        nonlocal calls
        calls += 1
        return '{"reflection":"first","summary":"first"}'

    bot = GwenBot(clock=lambda: now[0], mentor_complete=lambda *_args: None)
    ctx = _context(tmp_path, complete=complete, notify=lambda *_args, **_kwargs: None)
    bot.run(ctx)
    assert calls == 1

    now[0] += 60.0
    result = bot.run(ctx)
    assert result.details == {"claimed": False}
    assert calls == 1


def test_mentor_defaults_to_credential_aware_auto_and_can_be_pinned() -> None:
    automatic = _mentor_settings({})
    assert automatic is not None
    assert automatic.provider == "auto"
    assert automatic.model == ""

    pinned = _mentor_settings(
        {
            "auxiliary": {
                "gwen_mentor": {
                    "provider": "openrouter",
                    "model": "example/superior-model",
                }
            }
        }
    )
    assert pinned is not None
    assert (pinned.provider, pinned.model) == (
        "openrouter",
        "example/superior-model",
    )
