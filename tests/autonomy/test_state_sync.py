"""Tests for zeb_autonomy.state_sync (feature 5)."""

from __future__ import annotations

import json
import logging

from zeb_autonomy.base import BotContext
from zeb_autonomy.memory_store import MemoryStore
from zeb_autonomy.state_sync import (
    StateSyncBot,
    export_snapshot,
    import_snapshot,
    instance_id_from_config,
)


def _ctx(zeb_home, config):
    return BotContext(
        config=config,
        zeb_home=zeb_home,
        log=logging.getLogger("test"),
        complete=lambda *a, **k: None,
        notify=lambda *a, **k: None,
    )


def test_instance_id_from_config():
    cfg = {"autonomy": {"state_sync": {"instance_id": "zeb-1"}}}
    assert instance_id_from_config(cfg) == "zeb-1"
    # falls back to hostname (non-empty string)
    assert instance_id_from_config({}) != ""


def test_two_instances_merge_memory(tmp_path):
    shared = tmp_path / "shared"
    home_a = tmp_path / "home_a"
    home_b = tmp_path / "home_b"

    a = MemoryStore(home_a)
    b = MemoryStore(home_b)
    a.record_interaction("sa", "user", "alpha msg", ts=1.0)
    b.record_interaction("sb", "user", "bravo msg", ts=2.0)

    export_snapshot(home_a, shared, "a")
    export_snapshot(home_b, shared, "b")

    # each imports the OTHER's snapshot
    import_snapshot(home_a, shared / "b")
    import_snapshot(home_b, shared / "a")

    for home in (home_a, home_b):
        store = MemoryStore(home)
        contents = {r["content"] for r in store.recent_interactions()}
        assert contents == {"alpha msg", "bravo msg"}
        assert store.stats()["interactions"] == 2


def test_jsonl_union_dedups(tmp_path):
    shared = tmp_path / "shared"
    home_a = tmp_path / "home_a"
    home_b = tmp_path / "home_b"
    (home_a / "autonomy").mkdir(parents=True)
    (home_b / "autonomy").mkdir(parents=True)

    # shared line + unique lines each
    (home_a / "autonomy" / "notifications.jsonl").write_text(
        '{"m": "shared"}\n{"m": "only_a"}\n', encoding="utf-8"
    )
    (home_b / "autonomy" / "notifications.jsonl").write_text(
        '{"m": "shared"}\n{"m": "only_b"}\n', encoding="utf-8"
    )

    export_snapshot(home_b, shared, "b")
    import_snapshot(home_a, shared / "b")

    lines = (
        (home_a / "autonomy" / "notifications.jsonl")
        .read_text("utf-8")
        .splitlines()
    )
    assert lines.count('{"m": "shared"}') == 1  # deduped
    assert '{"m": "only_a"}' in lines
    assert '{"m": "only_b"}' in lines
    assert len(lines) == 3


def test_schedule_state_merge_takes_max(tmp_path):
    shared = tmp_path / "shared"
    home_a = tmp_path / "home_a"
    home_b = tmp_path / "home_b"
    (home_a / "autonomy").mkdir(parents=True)
    (home_b / "autonomy").mkdir(parents=True)

    (home_a / "autonomy" / "schedule_state.json").write_text(
        json.dumps({"bot1": 100.0, "bot2": 500.0}), encoding="utf-8"
    )
    (home_b / "autonomy" / "schedule_state.json").write_text(
        json.dumps({"bot1": 300.0, "bot3": 50.0}), encoding="utf-8"
    )

    export_snapshot(home_b, shared, "b")
    import_snapshot(home_a, shared / "b")

    merged = json.loads(
        (home_a / "autonomy" / "schedule_state.json").read_text("utf-8")
    )
    assert merged["bot1"] == 300.0  # max of 100 and 300
    assert merged["bot2"] == 500.0  # local only
    assert merged["bot3"] == 50.0  # incoming only


def test_bot_no_shared_dir_is_noop(tmp_path):
    ctx = _ctx(tmp_path, {})
    result = StateSyncBot().run(ctx)
    assert result.ok
    assert result.summary == "no shared_dir configured"


def test_bot_syncs_and_skips_own_dir(tmp_path):
    shared = tmp_path / "shared"
    home_a = tmp_path / "home_a"
    home_b = tmp_path / "home_b"

    MemoryStore(home_a).record_interaction("sa", "user", "alpha", ts=1.0)
    MemoryStore(home_b).record_interaction("sb", "user", "bravo", ts=2.0)

    # b exports first so its snapshot exists in shared
    export_snapshot(home_b, shared, "instance-b")

    cfg = {
        "autonomy": {
            "state_sync": {
                "instance_id": "instance-a",
                "shared_dir": str(shared),
            }
        }
    }
    result = StateSyncBot().run(_ctx(home_a, cfg))
    assert result.ok
    assert result.details["instance_id"] == "instance-a"
    # imported b's snapshot
    assert result.summary == "synced with 1 instance(s)"

    store_a = MemoryStore(home_a)
    contents = {r["content"] for r in store_a.recent_interactions()}
    assert contents == {"alpha", "bravo"}

    # our own snapshot was exported and re-running does not re-import ourselves
    assert (shared / "instance-a").is_dir()
    result2 = StateSyncBot().run(_ctx(home_a, cfg))
    assert result2.summary == "synced with 1 instance(s)"
