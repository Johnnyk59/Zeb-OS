"""Tests for the self-evolution engine (24/7 custom-model development).

No network, no real model. The completion is faked and the dataset/cache
live under a temp zeb_home. Covers: the response cache genuinely avoiding a
second model call, dataset harvest de-duplication, and one full bot tick
producing a coherent manifest/status.
"""

from __future__ import annotations

import json
import logging

from zeb_autonomy import self_evolution as se
from zeb_autonomy.base import BotContext


def _ctx(tmp_path, *, complete, config=None):
    return BotContext(
        config=config or {"autonomy": {"self_evolution": {"enabled": True}}},
        zeb_home=tmp_path,
        log=logging.getLogger("test.self_evolution"),
        complete=complete,
        notify=lambda *a, **k: None,
    )


def test_cache_avoids_second_model_call(tmp_path):
    calls = {"n": 0}

    def fake(prompt, system="", max_tokens=512, **kw):
        calls["n"] += 1
        return "answer"

    a = se.cached_complete("q", complete=fake, zeb_home=tmp_path)
    b = se.cached_complete("q", complete=fake, zeb_home=tmp_path)
    assert a == b == "answer"
    assert calls["n"] == 1  # second call served from cache

    st = se.status(tmp_path)
    assert st["cache_hits"] == 1
    assert st["cache_misses"] == 1
    assert st["cache_entries"] == 1
    # Effective speed-up tracks the hit-rate.
    assert st["speedup_pct"] == 50.0


def test_harvest_dedupes(tmp_path):
    import time

    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True)
    convo = {
        "messages": [
            {"role": "user", "content": "Explain gravity"},
            {"role": "assistant", "content": "Gravity is the attraction between masses."},
        ]
    }
    (sessions / "s1.json").write_text(json.dumps(convo), encoding="utf-8")

    added = se.harvest_dataset(tmp_path, cutoff=time.time() - 3600)
    assert added == 1
    # Same content again → no new example.
    added2 = se.harvest_dataset(tmp_path, cutoff=time.time() - 3600)
    assert added2 == 0

    ds = (tmp_path / "autonomy" / "evolution" / "dataset.jsonl").read_text("utf-8")
    assert "Explain gravity" in ds


def test_bot_tick_writes_manifest(tmp_path):
    ctx = _ctx(tmp_path, complete=lambda *a, **k: "ready")
    result = se.bot.run(ctx)
    assert result.ok is True

    st = se.status(tmp_path)
    assert st["enabled"] is True
    assert st["generation"] == 0
    # No trainer configured → stays in collecting/pending, never "trained".
    assert st["training_state"] in ("collecting", "pending")
    assert st["trainer_available"] is False


def test_disabled_via_config(tmp_path):
    ctx = _ctx(
        tmp_path,
        complete=lambda *a, **k: "x",
        config={"autonomy": {"self_evolution": {"enabled": False}}},
    )
    result = se.bot.run(ctx)
    assert result.ok is True
    assert "disabled" in result.summary
