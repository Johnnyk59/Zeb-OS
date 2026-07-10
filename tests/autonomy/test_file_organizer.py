"""Tests for the nightly FileOrganizerBot (feature 9)."""

from __future__ import annotations

import logging
from pathlib import Path

from zeb_autonomy.base import BotContext
from zeb_autonomy.bots.file_organizer import FileOrganizerBot


def _ctx(config: dict, zeb_home: Path) -> BotContext:
    return BotContext(
        config=config,
        zeb_home=zeb_home,
        log=logging.getLogger("test.file_organizer"),
        complete=lambda *a, **k: None,
        notify=lambda *a, **k: None,
    )


def _seed(target: Path) -> None:
    (target / "essay.md").write_text("doc")
    (target / "data.csv").write_text("a,b")
    (target / "pic.png").write_bytes(b"\x89PNG")
    (target / "app.py").write_text("print(1)")
    (target / "bundle.zip").write_bytes(b"PK")
    (target / "weird.xyz").write_text("misc")
    # protected
    (target / "README.md").write_text("readme")
    (target / "LICENSE").write_text("mit")
    (target / "pyproject.toml").write_text("[tool]")
    (target / ".hidden").write_text("secret")
    (target / "deps.lock").write_text("lock")


def _count_all_files(root: Path) -> int:
    return sum(1 for p in root.rglob("*") if p.is_file())


def test_no_target_is_noop(tmp_path):
    bot = FileOrganizerBot()
    res = bot.run(_ctx({}, tmp_path))
    assert res.ok is True
    assert res.summary == "no organize target configured"
    assert res.notify is False


def test_organizes_into_categories_and_protects(tmp_path):
    target = tmp_path / "inbox"
    target.mkdir()
    _seed(target)
    before = _count_all_files(target)

    config = {"autonomy": {"file_organizer": {"target": str(target)}}}
    bot = FileOrganizerBot()
    res = bot.run(_ctx(config, tmp_path))

    assert res.ok is True
    # 6 loose files organized (essay, data, pic, app, bundle, weird)
    assert res.details["moved"] == 6
    assert res.notify is True

    # correct categories
    assert (target / "documents" / "essay.md").is_file()
    assert (target / "data" / "data.csv").is_file()
    assert (target / "images" / "pic.png").is_file()
    assert (target / "code" / "app.py").is_file()
    assert (target / "archives" / "bundle.zip").is_file()
    assert (target / "misc" / "weird.xyz").is_file()

    # protected files stayed put
    assert (target / "README.md").is_file()
    assert (target / "LICENSE").is_file()
    assert (target / "pyproject.toml").is_file()
    assert (target / ".hidden").is_file()
    assert (target / "deps.lock").is_file()

    # NOTHING deleted: total file count preserved
    assert _count_all_files(target) == before


def test_idempotent_second_run(tmp_path):
    target = tmp_path / "inbox"
    target.mkdir()
    _seed(target)
    config = {"autonomy": {"file_organizer": {"target": str(target)}}}
    bot = FileOrganizerBot()

    bot.run(_ctx(config, tmp_path))
    res2 = bot.run(_ctx(config, tmp_path))
    # second run finds nothing loose to move
    assert res2.details["moved"] == 0
    assert res2.notify is False


def test_dry_run_plans_without_moving(tmp_path):
    target = tmp_path / "inbox"
    target.mkdir()
    _seed(target)
    before = _count_all_files(target)
    config = {
        "autonomy": {"file_organizer": {"target": str(target), "dry_run": True}}
    }
    bot = FileOrganizerBot()
    res = bot.run(_ctx(config, tmp_path))

    assert res.details["dry_run"] is True
    assert res.details["moved"] == 6
    # nothing actually moved
    assert (target / "essay.md").is_file()
    assert not (target / "documents").exists()
    assert _count_all_files(target) == before


def test_protect_glob(tmp_path):
    target = tmp_path / "inbox"
    target.mkdir()
    (target / "keep_me.md").write_text("x")
    (target / "move_me.md").write_text("y")
    config = {
        "autonomy": {
            "file_organizer": {"target": str(target), "protect": ["keep_*"]}
        }
    }
    bot = FileOrganizerBot()
    res = bot.run(_ctx(config, tmp_path))
    assert res.details["moved"] == 1
    assert (target / "keep_me.md").is_file()
    assert (target / "documents" / "move_me.md").is_file()
