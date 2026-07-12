"""Nightly file organizer (feature 9).

Sorts *loose top-level files* in a configured target directory into category
subdirectories by extension. This is deliberately conservative: it requires an
explicit target (reorganizing an arbitrary tree is unsafe), it never recurses,
never deletes anything, and refuses to touch a set of protected names
(READMEs, licences, lockfiles, dotfiles, and anything matching a user glob).
Running it twice is a no-op — files already inside a category dir are skipped.

**Safe by default.** ``dry_run`` defaults to ``True``: out of the box the bot
only *plans* moves and reports them; it never relocates a real file until the
user explicitly sets ``autonomy.file_organizer.dry_run: false``. Every real
move is recorded to a reversible journal (``<zeb_home>/autonomy/move_journal.jsonl``)
so ``undo_last_organize()`` can put files back — an autonomous file mover must
never be a one-way, no-undo operation.

After a real move it best-effort updates the FileIndex rename history so the
old location stays searchable. All errors are wrapped: run() never raises.
"""

from __future__ import annotations

import fnmatch
import json
import shutil
import time
from pathlib import Path

from zeb_autonomy.base import BotContext, BotResult


def _journal_path(zeb_home) -> Path:
    """Path to the reversible move journal (append-only JSON Lines)."""
    d = Path(zeb_home) / "autonomy"
    d.mkdir(parents=True, exist_ok=True)
    return d / "move_journal.jsonl"


def undo_last_organize(zeb_home, count: int | None = None) -> dict:
    """Reverse journaled file-organizer moves, newest first.

    Moves each recorded destination back to its original source when it is safe
    to do so (destination still exists, original slot is free). Successfully
    reversed entries are dropped from the journal; anything skipped (already
    moved away, source now occupied) is kept so the record stays honest.

    Args:
        zeb_home: the Zeb home directory containing ``autonomy/move_journal.jsonl``.
        count: how many of the most recent moves to undo; ``None`` = all.

    Returns:
        ``{"undone": int, "skipped": int, "remaining": int}``.
    """
    journal = _journal_path(zeb_home)
    if not journal.is_file():
        return {"undone": 0, "skipped": 0, "remaining": 0}
    try:
        lines = [l for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return {"undone": 0, "skipped": 0, "remaining": 0}

    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except Exception:
            continue

    # Undo newest-first, up to `count`.
    to_consider = list(reversed(entries))
    if count is not None:
        to_consider = to_consider[: max(0, int(count))]

    undone = 0
    skipped = 0
    reversed_dsts = set()
    for e in to_consider:
        src = e.get("src")
        dst = e.get("dst")
        if not src or not dst:
            skipped += 1
            continue
        src_p, dst_p = Path(src), Path(dst)
        # Only reverse when the destination is present and the original slot is
        # free — never clobber a file that now lives at the old location.
        if dst_p.exists() and not src_p.exists():
            try:
                src_p.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst_p), str(src_p))
                undone += 1
                reversed_dsts.add(dst)
            except OSError:
                skipped += 1
        else:
            skipped += 1

    # Rewrite the journal without the entries we successfully reversed.
    remaining_entries = [e for e in entries if e.get("dst") not in reversed_dsts]
    try:
        if remaining_entries:
            journal.write_text(
                "\n".join(json.dumps(e) for e in remaining_entries) + "\n",
                encoding="utf-8",
            )
        else:
            journal.unlink(missing_ok=True)
    except OSError:
        pass

    return {"undone": undone, "skipped": skipped, "remaining": len(remaining_entries)}

# extension -> category
_CATEGORIES: "dict[str, tuple[str, ...]]" = {
    "documents": (".md", ".txt", ".pdf", ".doc", ".docx", ".rtf"),
    "images": (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"),
    "archives": (".zip", ".tar", ".gz", ".tgz", ".7z"),
    "code": (".py", ".js", ".ts", ".tsx", ".sh", ".rs", ".go", ".c", ".cpp", ".h"),
    "data": (".json", ".jsonl", ".csv", ".yaml", ".yml", ".xml", ".db", ".sqlite"),
}

_EXT_TO_CATEGORY: "dict[str, str]" = {
    ext: cat for cat, exts in _CATEGORIES.items() for ext in exts
}

_CATEGORY_DIRS = set(_CATEGORIES.keys()) | {"misc"}

# Protected filename prefixes/exact names (matched case-insensitively).
_PROTECTED_PREFIXES = ("readme", "license", "licence", "changelog")
_PROTECTED_EXACT = {"pyproject.toml", "package.json"}


class FileOrganizerBot:
    name = "file_organizer"

    def run(self, ctx: BotContext) -> BotResult:
        try:
            return self._run(ctx)
        except Exception as exc:  # never raise out of run()
            ctx.log.debug("file_organizer: unexpected error: %s", exc)
            return BotResult.failed(self.name, f"file_organizer error: {exc}")

    def _run(self, ctx: BotContext) -> BotResult:
        cfg = ((ctx.config.get("autonomy") or {}).get("file_organizer") or {})
        target_raw = cfg.get("target")
        if not target_raw:
            return BotResult(
                bot=self.name, ok=True, summary="no organize target configured"
            )

        target = Path(target_raw)
        if not target.is_dir():
            return BotResult.failed(
                self.name, f"target not a directory: {target}"
            )

        # Safe by default: only PLAN moves unless the user explicitly opts in
        # to real relocation with autonomy.file_organizer.dry_run: false.
        dry_run = bool(cfg.get("dry_run", True))
        protect_globs = cfg.get("protect") or []
        if not isinstance(protect_globs, list):
            protect_globs = []

        moved = 0
        categories_used: set[str] = set()
        planned: list[str] = []

        try:
            entries = sorted(target.iterdir())
        except OSError as exc:
            return BotResult.failed(self.name, f"cannot read target: {exc}")

        for entry in entries:
            try:
                if not entry.is_file():
                    continue  # never move directories
                name = entry.name
                if self._is_protected(name, protect_globs):
                    continue
                category = _EXT_TO_CATEGORY.get(entry.suffix.lower(), "misc")
                dest_dir = target / category
                # Idempotent: if it's somehow already under a category dir,
                # iterdir only yields top-level so this is belt-and-suspenders.
                if entry.parent.name in _CATEGORY_DIRS:
                    continue
                dest = dest_dir / name
                planned.append(f"{name} -> {category}/")
                categories_used.add(category)

                if dry_run:
                    moved += 1
                    continue

                dest_dir.mkdir(parents=True, exist_ok=True)
                final_dest = self._unique_dest(dest)
                shutil.move(str(entry), str(final_dest))
                moved += 1
                self._journal_move(ctx, entry, final_dest)
                self._record_rename(ctx, entry, final_dest)
            except OSError as exc:
                ctx.log.debug("file_organizer: skip %s: %s", entry, exc)
                continue

        verb = "would organize" if dry_run else "organized"
        summary = (
            f"{verb} {moved} files into {len(categories_used)} categories"
        )
        result = BotResult(
            bot=self.name,
            ok=True,
            summary=summary,
            details={
                "moved": moved,
                "categories": sorted(categories_used),
                "dry_run": dry_run,
                "plan": planned,
            },
        )
        if moved > 0:
            result.notify = True
            result.notify_message = summary
        return result

    # -- helpers -----------------------------------------------------------
    def _is_protected(self, name: str, protect_globs: list) -> bool:
        low = name.lower()
        if low.startswith("."):  # dotfiles
            return True
        if low in _PROTECTED_EXACT:
            return True
        if low.endswith(".lock"):
            return True
        for prefix in _PROTECTED_PREFIXES:
            if low.startswith(prefix):
                return True
        for pattern in protect_globs:
            try:
                if fnmatch.fnmatch(name, str(pattern)):
                    return True
            except Exception:
                continue
        return False

    def _unique_dest(self, dest: Path) -> Path:
        """Avoid clobbering an existing file at the destination."""
        if not dest.exists():
            return dest
        stem, suffix = dest.stem, dest.suffix
        i = 1
        while True:
            cand = dest.with_name(f"{stem}_{i}{suffix}")
            if not cand.exists():
                return cand
            i += 1

    def _journal_move(self, ctx: BotContext, old: Path, new: Path) -> None:
        """Append a reversible record of a real move so it can be undone."""
        try:
            entry = {
                "ts": time.time(),
                "src": str(old),
                "dst": str(new),
                "bot": self.name,
            }
            with open(_journal_path(ctx.zeb_home), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception as exc:  # best-effort — never break a move over logging
            ctx.log.debug("file_organizer: journal write skipped: %s", exc)

    def _record_rename(self, ctx: BotContext, old: Path, new: Path) -> None:
        try:
            from zeb_autonomy.file_index import FileIndex

            idx = FileIndex(ctx.zeb_home)
            idx.record_rename(str(old), str(new))
        except Exception as exc:  # best-effort only
            ctx.log.debug("file_organizer: index update skipped: %s", exc)
