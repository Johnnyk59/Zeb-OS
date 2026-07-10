"""Tests for the knowledge_firehose autonomy bot (feature 6).

No network and no real model: the single web seam ``_search_web`` and the
``complete`` helper are both faked. Covers the happy path (items + model
summary -> files written) and the offline no-op path.
"""

from __future__ import annotations

import json
import logging

import pytest

from zeb_autonomy.base import BotContext
from zeb_autonomy.bots import knowledge_firehose as kf


def _make_ctx(tmp_path, *, complete=None, config=None):
    notes = []

    def _notify(message, level="info", **details):
        notes.append((message, level, details))

    ctx = BotContext(
        config=config or {},
        zeb_home=tmp_path,
        log=logging.getLogger("test.knowledge_firehose"),
        complete=complete if complete is not None else (lambda *a, **k: None),
        notify=_notify,
    )
    return ctx, notes


def test_happy_path_writes_files(tmp_path, monkeypatch):
    fake_items = [
        {"title": "Big AI news", "url": "https://ex.com/a", "snippet": "A thing happened."},
        {"title": "Chips", "url": "https://ex.com/b", "snippet": "New hardware."},
    ]
    monkeypatch.setattr(kf, "_search_web", lambda topic, ctx: list(fake_items))

    ctx, _notes = _make_ctx(
        tmp_path,
        complete=lambda *a, **k: "CANNED SUMMARY of the day.",
        config={"autonomy": {"knowledge": {"topics": ["ai"]}}},
    )

    result = kf.bot.run(ctx)
    assert result.ok is True
    assert result.details["items"] == 2
    assert result.details["notes"] == 1

    kdir = tmp_path / "autonomy" / "knowledge"
    md_files = list(kdir.glob("*.md"))
    assert len(md_files) == 1
    md_text = md_files[0].read_text(encoding="utf-8")
    assert "CANNED SUMMARY" in md_text
    assert "## ai" in md_text

    jsonl = kdir / "knowledge.jsonl"
    assert jsonl.exists()
    lines = [json.loads(l) for l in jsonl.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    assert lines[0]["topic"] == "ai"
    assert lines[0]["url"] == "https://ex.com/a"
    assert {"ts", "topic", "title", "url", "snippet"} <= set(lines[0])


def test_default_topics_when_unconfigured(tmp_path, monkeypatch):
    monkeypatch.setattr(
        kf,
        "_search_web",
        lambda topic, ctx: [{"title": topic, "url": "u", "snippet": "s"}],
    )
    ctx, _ = _make_ctx(tmp_path, complete=lambda *a, **k: "note")
    result = kf.bot.run(ctx)
    assert result.ok is True
    # Two default topics, one item each.
    assert result.details["items"] == 2


def test_offline_noop_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(kf, "_search_web", lambda topic, ctx: [])
    ctx, _ = _make_ctx(tmp_path, complete=lambda *a, **k: "should not be used")

    result = kf.bot.run(ctx)
    assert result.ok is True
    assert "skipped" in result.summary
    assert not (tmp_path / "autonomy" / "knowledge").exists() or not list(
        (tmp_path / "autonomy" / "knowledge").glob("*.md")
    )


def test_items_but_model_offline_still_journals(tmp_path, monkeypatch):
    monkeypatch.setattr(
        kf,
        "_search_web",
        lambda topic, ctx: [{"title": "T", "url": "https://x", "snippet": "S"}],
    )
    ctx, _ = _make_ctx(
        tmp_path,
        complete=lambda *a, **k: None,  # model offline
        config={"autonomy": {"knowledge": {"topics": ["ai"]}}},
    )
    result = kf.bot.run(ctx)
    assert result.ok is True
    assert result.details["items"] == 1
    assert result.details["notes"] == 0
    md = list((tmp_path / "autonomy" / "knowledge").glob("*.md"))[0]
    assert "https://x" in md.read_text()


def test_notify_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(
        kf,
        "_search_web",
        lambda topic, ctx: [{"title": "T", "url": "u", "snippet": "s"}],
    )
    ctx, _ = _make_ctx(
        tmp_path,
        complete=lambda *a, **k: "n",
        config={"autonomy": {"knowledge": {"topics": ["ai"], "notify": True}}},
    )
    result = kf.bot.run(ctx)
    assert result.notify is True
    assert result.notify_message


def test_search_web_never_raises_when_no_provider(tmp_path):
    # The real _search_web (not monkeypatched) must degrade to [] with no
    # provider configured, never raising.
    ctx, _ = _make_ctx(tmp_path)
    assert kf._search_web("anything", ctx) == []
