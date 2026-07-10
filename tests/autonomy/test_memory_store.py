"""Tests for zeb_autonomy.memory_store (feature 3)."""

from __future__ import annotations

import logging

from zeb_autonomy.base import BotContext
from zeb_autonomy.memory_store import MemoryLearningBot, MemoryStore


def _ctx(zeb_home, complete_ret, notes):
    def _complete(prompt, *, system="", max_tokens=512, **kw):
        return complete_ret

    def _notify(message, level="info", **details):
        notes.append((message, level, details))

    return BotContext(
        config={},
        zeb_home=zeb_home,
        log=logging.getLogger("test"),
        complete=_complete,
        notify=_notify,
    )


def test_record_recent_search_learnings_stats(tmp_path):
    store = MemoryStore(tmp_path)

    store.record_interaction("s1", "user", "hello world", ts=1.0)
    store.record_interaction("s1", "assistant", "goodbye moon", ts=2.0)
    store.record_interaction("s2", "user", "another world here", ts=3.0)
    store.record_request("s1", "please summarize", ts=1.5)
    store.record_learning("greetings", "say hi back", source="test", ts=4.0)

    recent = store.recent_interactions(limit=10)
    assert len(recent) == 3
    # newest first
    assert recent[0]["content"] == "another world here"

    scoped = store.recent_interactions(session_id="s1")
    assert len(scoped) == 2
    assert all(r["session_id"] == "s1" for r in scoped)

    hits = store.search("world")
    assert len(hits) == 2
    assert all("world" in h["content"] for h in hits)

    learnings = store.learnings()
    assert len(learnings) == 1
    assert learnings[0]["insight"] == "say hi back"

    stats = store.stats()
    assert stats == {"interactions": 3, "requests": 1, "learnings": 1}


def test_metadata_roundtrip(tmp_path):
    store = MemoryStore(tmp_path)
    store.record_interaction("s1", "user", "with meta", metadata={"k": "v"}, ts=1.0)
    rec = store.recent_interactions()[0]
    assert rec["metadata"] == {"k": "v"}


def test_merge_from_dedups_by_id(tmp_path):
    home_a = tmp_path / "a"
    home_b = tmp_path / "b"
    a = MemoryStore(home_a)
    b = MemoryStore(home_b)

    a.record_interaction("s1", "user", "from a", ts=1.0)
    a.record_request("s1", "req a", ts=1.0)
    a.record_learning("t", "insight a", source="a", ts=1.0)
    b.record_interaction("s2", "user", "from b", ts=2.0)

    other_db = home_a / "autonomy" / "memory.db"

    first = b.merge_from(other_db)
    assert first == {"interactions": 1, "requests": 1, "learnings": 1}
    assert b.stats() == {"interactions": 2, "requests": 1, "learnings": 1}

    # Merging the same db again is a no-op (content-stable ids).
    second = b.merge_from(other_db)
    assert second == {"interactions": 0, "requests": 0, "learnings": 0}
    assert b.stats() == {"interactions": 2, "requests": 1, "learnings": 1}


def test_merge_from_missing_db(tmp_path):
    b = MemoryStore(tmp_path / "b")
    assert b.merge_from(tmp_path / "nope.db") == {
        "interactions": 0,
        "requests": 0,
        "learnings": 0,
    }


def test_learning_bot_records(tmp_path):
    store = MemoryStore(tmp_path)
    store.record_interaction("s1", "user", "I prefer terse answers", ts=1.0)
    store.record_interaction("s1", "assistant", "ok", ts=2.0)

    notes = []
    canned = "style: prefer terse answers\ntone: stay friendly"
    ctx = _ctx(tmp_path, canned, notes)

    result = MemoryLearningBot().run(ctx)
    assert result.ok
    assert result.details["learnings"] == 2

    learnings = store.learnings()
    assert len(learnings) == 2
    assert {l["topic"] for l in learnings} == {"style", "tone"}
    assert all(l["source"] == "memory_learning" for l in learnings)

    # Marker advanced → second run sees nothing new.
    result2 = MemoryLearningBot().run(ctx)
    assert result2.ok
    assert result2.summary == "nothing to learn"
    assert len(store.learnings()) == 2


def test_learning_bot_offline_model_is_noop(tmp_path):
    store = MemoryStore(tmp_path)
    store.record_interaction("s1", "user", "hi", ts=1.0)

    notes = []
    ctx = _ctx(tmp_path, None, notes)  # complete returns None → offline

    result = MemoryLearningBot().run(ctx)
    assert result.ok
    assert result.summary == "nothing to learn"
    assert store.learnings() == []


def test_learning_bot_no_interactions_is_noop(tmp_path):
    MemoryStore(tmp_path)  # empty
    ctx = _ctx(tmp_path, "topic: insight", [])
    result = MemoryLearningBot().run(ctx)
    assert result.ok
    assert result.summary == "nothing to learn"
