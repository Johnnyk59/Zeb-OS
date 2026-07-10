"""Tests for the self_improvement autonomy bot (feature 7).

No network and no real model. Material is supplied via a temp sessions
transcript; the model is faked. Covers the happy path (material + bullets ->
persona files) and the model-offline no-op.
"""

from __future__ import annotations

import json
import logging

from zeb_autonomy.base import BotContext
from zeb_autonomy.bots import self_improvement as si


def _make_ctx(tmp_path, *, complete, config=None):
    notes = []

    def _notify(message, level="info", **details):
        notes.append((message, level, details))

    ctx = BotContext(
        config=config or {},
        zeb_home=tmp_path,
        log=logging.getLogger("test.self_improvement"),
        complete=complete,
        notify=_notify,
    )
    return ctx, notes


def _write_transcript(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    transcript = [
        {"role": "user", "content": "hey zeb, keep it short and casual"},
        {"role": "assistant", "content": "Understood — I will be brief."},
    ]
    (sessions / "s1.json").write_text(json.dumps(transcript), encoding="utf-8")
    return sessions


def test_happy_path_writes_persona_files(tmp_path):
    _write_transcript(tmp_path)
    bullets = "- I will keep replies short.\n- I will match Johnny's casual tone."
    ctx, _ = _make_ctx(tmp_path, complete=lambda *a, **k: bullets)

    result = si.bot.run(ctx)
    assert result.ok is True

    persona = tmp_path / "autonomy" / "persona"
    notes = persona / "persona_notes.md"
    guide = persona / "style_guide.md"
    assert notes.exists() and guide.exists()

    notes_text = notes.read_text(encoding="utf-8")
    guide_text = guide.read_text(encoding="utf-8")
    assert "Reflection" in notes_text
    assert "keep replies short" in notes_text
    assert "keep replies short" in guide_text
    assert "current best" in guide_text.lower()


def test_notes_are_append_only(tmp_path):
    _write_transcript(tmp_path)
    ctx, _ = _make_ctx(tmp_path, complete=lambda *a, **k: "- I will improve.")
    si.bot.run(ctx)
    si.bot.run(ctx)
    notes_text = (tmp_path / "autonomy" / "persona" / "persona_notes.md").read_text()
    assert notes_text.count("## Reflection") == 2


def test_model_offline_noop(tmp_path):
    _write_transcript(tmp_path)
    ctx, _ = _make_ctx(tmp_path, complete=lambda *a, **k: None)
    result = si.bot.run(ctx)
    assert result.ok is True
    assert "skipped" in result.summary
    assert not (tmp_path / "autonomy" / "persona").exists() or not list(
        (tmp_path / "autonomy" / "persona").glob("*.md")
    )


def test_no_material_noop(tmp_path):
    # No sessions dir, no MemoryStore rows -> clean no-op even if model works.
    ctx, _ = _make_ctx(tmp_path, complete=lambda *a, **k: "- unused")
    result = si.bot.run(ctx)
    assert result.ok is True
    assert "skipped" in result.summary


def test_jsonl_transcript_material(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    with (sessions / "s.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"role": "user", "content": "be warmer"}) + "\n")
        fh.write(json.dumps({"role": "assistant", "content": "Okay!"}) + "\n")
    ctx, _ = _make_ctx(tmp_path, complete=lambda *a, **k: "- I will be warmer.")
    result = si.bot.run(ctx)
    assert result.ok is True
    assert (tmp_path / "autonomy" / "persona" / "style_guide.md").exists()


def test_notify_flag(tmp_path):
    _write_transcript(tmp_path)
    ctx, _ = _make_ctx(
        tmp_path,
        complete=lambda *a, **k: "- I will improve.",
        config={"autonomy": {"self_improvement": {"notify": True}}},
    )
    result = si.bot.run(ctx)
    assert result.notify is True
    assert result.notify_message
