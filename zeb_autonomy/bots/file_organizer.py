"""Nightly file organizer (feature 9).

Sorts *loose top-level files* in a configured target directory into category
subdirectories by extension. This is deliberately conservative: it requires an
explicit target (reorganizing an arbitrary tree is unsafe), it never recurses,
never deletes anything, and refuses to touch a set of protected names
(READMEs, licences, lockfiles, dotfiles, and anything matching a user glob).
Running it twice is a no-op — files already inside a category dir are skipped.

After a real move it best-effort updates the FileIndex rename history so the
old location stays searchable. All errors are wrapped: run() never raises.
"""

from __future__ import annotations

import fnmatch
import shutil
from pathlib import Path

from zeb_autonomy.base import BotContext, BotResult

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

        dry_run = bool(cfg.get("dry_run", False))
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

    def _record_rename(self, ctx: BotContext, old: Path, new: Path) -> None:
        try:
            from zeb_autonomy.file_index import FileIndex

            idx = FileIndex(ctx.zeb_home)
            idx.record_rename(str(old), str(new))
        except Exception as exc:  # best-effort only
            ctx.log.debug("file_organizer: index update skipped: %s", exc)
