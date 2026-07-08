"""Tests for the SQLite-backed FileIndex (features 4 + 8)."""

from __future__ import annotations

from pathlib import Path

from zeb_autonomy.file_index import FileIndex


def _make_tree(root: Path) -> None:
    (root / "report.md").write_text("hello")
    (root / "notes.txt").write_text("notes")
    (root / "photo.png").write_bytes(b"\x89PNG")
    sub = root / "src"
    sub.mkdir()
    (sub / "main.py").write_text("print(1)")
    # pruned dir must be ignored
    junk = root / "node_modules"
    junk.mkdir()
    (junk / "ignored.js").write_text("nope")


def test_refresh_counts_files_and_prunes(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _make_tree(proj)
    idx = FileIndex(tmp_path / "home", roots=[proj])
    n = idx.refresh()
    # report.md, notes.txt, photo.png, src/main.py == 4 (node_modules pruned)
    assert n == 4
    assert idx.count() == 4


def test_find_exact_and_substring(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _make_tree(proj)
    idx = FileIndex(tmp_path / "home", roots=[proj])
    idx.refresh()

    exact = idx.find("report.md")
    assert exact and exact[0]["name"] == "report.md"

    # substring, case-insensitive
    sub = idx.find("NOTE")
    assert any(m["name"] == "notes.txt" for m in sub)

    # path-substring match
    bysrc = idx.find("src")
    assert any(m["name"] == "main.py" for m in bysrc)

    assert idx.find("does-not-exist-xyz") == []


def test_record_rename_find_by_old_name(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _make_tree(proj)
    idx = FileIndex(tmp_path / "home", roots=[proj])
    idx.refresh()

    old = proj / "report.md"
    new = proj / "quarterly_summary.md"
    old.rename(new)
    assert idx.record_rename(str(old), str(new)) is True

    # searching the CURRENT name works
    cur = idx.find("quarterly_summary")
    assert cur and cur[0]["path"] == str(new)

    # searching the OLD name resolves to the NEW path
    byold = idx.find("report.md")
    assert byold, "old name should still be findable"
    assert byold[0]["path"] == str(new)

    # old path no longer indexed directly
    assert not any(m["path"] == str(old) for m in idx.find("quarterly_summary"))


def test_fail_open_on_empty_query(tmp_path):
    idx = FileIndex(tmp_path / "home", roots=[tmp_path])
    assert idx.find("") == []
    assert idx.find("   ") == []
