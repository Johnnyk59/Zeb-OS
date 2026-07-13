"""Tests for the self-review engine (6h / 12h / 24h summaries).

No network, no real model. The model is faked; activity is seeded on disk.
Covers: a review persists to Markdown + index, load_reviews returns all three
windows, the offline fallback still writes something, and the ReviewBot
refreshes stale windows.
"""

from __future__ import annotations

import json
import logging

from zeb_autonomy import self_review as sr
from zeb_autonomy.base import BotContext


def _seed_activity(tmp_path):
    """Write a recent session so the reviewer has material to summarize."""
    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    convo = {
        "messages": [
            {"role": "user", "content": "help me ship the dashboard"},
            {"role": "assistant", "content": "Shipped the dashboard changes."},
        ]
    }
    (sessions / "s1.json").write_text(json.dumps(convo), encoding="utf-8")


def test_generate_persists_markdown_and_index(tmp_path):
    _seed_activity(tmp_path)
    out = sr.generate_review(
        "6h",
        config={},
        zeb_home=tmp_path,
        complete=lambda p, system="", max_tokens=700: "## Highlights\nShipped features.",
    )
    assert out["window"] == "6h"
    assert out["window_hours"] == 6
    assert "Highlights" in out["markdown"]
    assert out["generating"] is False

    md = tmp_path / "autonomy" / "reviews" / "review_6h.md"
    assert md.exists()
    assert "Highlights" in md.read_text("utf-8")


def test_load_reviews_returns_all_windows(tmp_path):
    _seed_activity(tmp_path)
    sr.generate_review(
        "12h", config={}, zeb_home=tmp_path, complete=lambda *a, **k: "body"
    )
    reviews = sr.load_reviews(tmp_path)
    windows = {r["window"] for r in reviews}
    assert windows == {"6h", "12h", "24h"}
    twelve = next(r for r in reviews if r["window"] == "12h")
    assert twelve["markdown"]
    assert twelve["generated_at"] is not None


def test_offline_fallback_still_writes(tmp_path):
    # Model returns nothing → fallback markdown, never an exception.
    out = sr.generate_review(
        "24h", config={}, zeb_home=tmp_path, complete=lambda *a, **k: None
    )
    assert out["markdown"]
    assert "24-Hour Review" in out["markdown"]


def test_review_bot_refreshes(tmp_path):
    _seed_activity(tmp_path)
    ctx = BotContext(
        config={},
        zeb_home=tmp_path,
        log=logging.getLogger("test.self_review"),
        complete=lambda p, system="", max_tokens=700: "fresh summary",
        notify=lambda *a, **k: None,
    )
    result = sr.bot.run(ctx)
    assert result.ok is True
    # All three windows were missing → all refreshed.
    reviews = sr.load_reviews(tmp_path)
    assert all(r["markdown"] for r in reviews)
