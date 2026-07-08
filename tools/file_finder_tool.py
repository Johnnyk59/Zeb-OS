#!/usr/bin/env python3
"""
File Finder Tool Module - Fast file search & rename

Agent-invokable wrappers around the autonomy FileIndex (features 4 + 8):

- find_files: fuzzy, ranked, case-insensitive search over the indexed file
  tree. Refreshes the index on first use if it's empty. Because the index
  remembers renames, searching an OLD name still finds the file at its
  CURRENT path.
- rename_file: perform an on-disk rename and record it in the index so the
  old name stays searchable.

The index is fail-open and never raises; these handlers additionally wrap
everything and return a clear human-readable string (never an exception) so
the agent always gets actionable feedback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def _get_index():
    """Build a FileIndex rooted at the current Zeb home.

    Import is done lazily/guarded so the tool module loads even if the
    autonomy package or zeb_constants is unavailable in some contexts.
    """
    from zeb_autonomy.file_index import FileIndex

    try:
        from zeb_constants import get_zeb_home

        zeb_home = get_zeb_home()
    except Exception:
        zeb_home = Path.cwd()
    return FileIndex(zeb_home)


def _fmt_size(size: Any) -> str:
    try:
        n = int(size)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def handle_find_files(args: Dict[str, Any]) -> str:
    """Find files by name/path. Refreshes the index if it's empty."""
    try:
        query = str((args or {}).get("query", "")).strip()
        if not query:
            return "Error: 'query' is required."
        try:
            limit = int((args or {}).get("limit", 25))
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))

        index = _get_index()
        if index.count() == 0:
            indexed = index.refresh()
            if indexed == 0:
                return f"No files indexed yet (index empty). No matches for '{query}'."

        matches = index.find(query, limit=limit)
        if not matches:
            return f"No files found matching '{query}'."

        lines = [f"Found {len(matches)} match(es) for '{query}':"]
        for m in matches:
            lines.append(
                f"- {m['name']}  ({_fmt_size(m.get('size'))})  {m['path']}"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"Error searching files: {exc}"


def handle_rename_file(args: Dict[str, Any]) -> str:
    """Rename a file on disk and record it in the index."""
    try:
        a = args or {}
        old_path = str(a.get("old_path", "")).strip()
        new_path = str(a.get("new_path", "")).strip()
        if not old_path or not new_path:
            return "Error: both 'old_path' and 'new_path' are required."

        old = Path(old_path)
        new = Path(new_path)
        if not old.exists():
            return f"Error: source does not exist: {old}"
        if new.exists():
            return f"Error: destination already exists: {new}"

        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
        except OSError as exc:
            return f"Error renaming file: {exc}"

        try:
            index = _get_index()
            index.record_rename(str(old), str(new))
        except Exception as exc:
            # Rename already succeeded on disk — report success but note it.
            return f"Renamed {old} -> {new} (index update skipped: {exc})"

        return f"Renamed {old} -> {new} (recorded in index)."
    except Exception as exc:
        return f"Error renaming file: {exc}"


# =============================================================================
# OpenAI Function-Calling Schemas
# =============================================================================

FIND_FILES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "find_files",
        "description": (
            "Search the indexed file tree for files by name or path. "
            "Case-insensitive and ranked (exact name, then name prefix, then "
            "name substring, then path substring). The index remembers "
            "renames, so an old/previous name still finds the file at its "
            "current location. Refreshes the index automatically if empty."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Name or path fragment to search for.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum matches to return (default 25).",
                    "default": 25,
                },
            },
            "required": ["query"],
        },
    },
}

RENAME_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "rename_file",
        "description": (
            "Rename or move a file on disk and record the change in the file "
            "index so the old name/path remains searchable and resolves to "
            "the new location."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "old_path": {
                    "type": "string",
                    "description": "Current absolute path of the file.",
                },
                "new_path": {
                    "type": "string",
                    "description": "New absolute path for the file.",
                },
            },
            "required": ["old_path", "new_path"],
        },
    },
}


# =============================================================================
# Registration — self-registers at import time. Discovery
# (tools/registry.py::discover_builtin_tools) only detects TOP-LEVEL
# ``registry.register(...)`` statements via AST, so these must stay at module
# scope (not nested in a try/except). Registered under the existing "file"
# toolset so they ship wherever read_file/write_file/search_files do, without
# introducing a new toolset name.
# =============================================================================

from tools.registry import registry

registry.register(
    name="find_files",
    toolset="file",
    schema=FIND_FILES_SCHEMA,
    handler=lambda args, **kw: handle_find_files(args),
    emoji="🔍",
    description="Fast ranked file search (rename-aware) over the workspace index.",
)
registry.register(
    name="rename_file",
    toolset="file",
    schema=RENAME_FILE_SCHEMA,
    handler=lambda args, **kw: handle_rename_file(args),
    emoji="🏷️",
    description="Rename/move a file and keep it findable by its old name.",
)
