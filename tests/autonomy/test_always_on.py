"""Tests for the always_on autonomy bot.

No real model. ``complete`` is faked. Covers: keep-warm when the user is active
(no self-task) vs. self-tasking when the user is away (task queued to disk).
"""

from __future__ import annotations

import json
import logging
import time

from zeb_autonomy.base import BotContext
from zeb_autonomy.bots.always_on import AlwaysOnBot


def _ctx(tmp_path, *, complete):
    return BotContext(
        config={},
        zeb_home=tmp_path,
        log=logging.getLogger("test.always_on"),
        complete=complete,
        notify=lambda *a, **k: None,
    )


def test_keep_warm_when_user_active(tmp_path, monkeypatch):
    # Recent user turn => not away => no self-task queued.
    import zeb_autonomy.bots.always_on as ao

    monkeypatch.setattr(ao, "_last_user_activity_ts", lambda: time.time())
    ctx = _ctx(tmp_path, complete=lambda *a, **k: "ok")
    res = AlwaysOnBot(idle_minutes=20).run(ctx)
    assert res.ok is True
    assert res.details["user_away"] is False
    assert not (tmp_path / "autonomy" / "self_tasks" / "queue.jsonl").exists()


def test_self_tasks_when_user_away(tmp_path, monkeypatch):
    import zeb_autonomy.bots.always_on as ao

    # No/old user activity => away => generate + persist a self-task.
    monkeypatch.setattr(ao, "_last_user_activity_ts", lambda: 0.0)
    ctx = _ctx(tmp_path, complete=lambda *a, **k: "Study CPU-friendly quantization")
    res = AlwaysOnBot(idle_minutes=20).run(ctx)
    assert res.ok is True
    assert res.details["user_away"] is True
    queue = tmp_path / "autonomy" / "self_tasks" / "queue.jsonl"
    assert queue.exists()
    row = json.loads(queue.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["task"] == "Study CPU-friendly quantization"
    assert row["source"] == "always_on_idle"


def test_failopen_when_model_offline(tmp_path, monkeypatch):
    import zeb_autonomy.bots.always_on as ao

    monkeypatch.setattr(ao, "_last_user_activity_ts", lambda: 0.0)
    # complete returns None (no model) — must not raise, still ok.
    ctx = _ctx(tmp_path, complete=lambda *a, **k: None)
    res = AlwaysOnBot(idle_minutes=20).run(ctx)
    assert res.ok is True
