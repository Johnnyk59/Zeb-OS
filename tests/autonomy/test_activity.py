"""Tests for the brain-activity beacon (dashboard status pill source)."""

from __future__ import annotations

import zeb_autonomy.activity as activity


def test_set_get_roundtrip():
    activity.set("learning", "knowledge_firehose")
    got = activity.get()
    assert got["status"] == "learning"
    assert got["detail"] == "knowledge_firehose"


def test_unknown_status_falls_back_to_processing():
    activity.set("bogus")
    assert activity.get()["status"] == "processing"


def test_clear_returns_idle():
    activity.set("learning")
    activity.clear()
    assert activity.get()["status"] == "idle"


def test_ttl_decays_to_idle():
    activity.set("learning")
    # A tiny TTL forces the entry to be treated as stale.
    assert activity.get(ttl=-1)["status"] == "idle"
