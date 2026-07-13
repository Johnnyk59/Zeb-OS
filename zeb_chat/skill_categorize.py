"""Auto-categorization for skills Zeb discovers.

When Zeb finds a new capability — a skill pulled from a GitHub repo, a
hub install, a hand-authored SKILL.md — it should land in the right place in
the dashboard automatically, not in an "uncategorized" limbo. This module is
the single classifier both the Skills view and the repo-sync path use so the
routing is consistent:

* :func:`route` decides which sidebar *section* an artifact belongs to
  (GitHub Repos vs Skills vs Plugins).
* :func:`categorize` picks a Skills sub-category from a skill's name, tags,
  and description, so newly discovered skills slot under the correct heading.

Pure, dependency-free, and fail-open (returns a sensible default rather than
raising), so it's safe to call from request handlers and background bots.
"""

from __future__ import annotations

from typing import Any, Iterable

# Ordered category → trigger keywords. First category with a hit wins, so put
# the more specific buckets earlier. Keys match the headings the Skills view
# already groups by.
_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("development", ("code", "git", "github", "debug", "compile", "lint", "test", "ide", "programming", "repo")),
    ("ai-ml", ("llm", "model", "train", "inference", "embedding", "vector", "huggingface", "vllm", "llama", "diffusion", "agent")),
    ("data", ("database", "sql", "csv", "spreadsheet", "airtable", "notion", "analytics", "scrape", "dataset")),
    ("media", ("image", "video", "audio", "music", "gif", "render", "3d", "animation", "photo", "voice", "speech")),
    ("productivity", ("note", "calendar", "email", "reminder", "task", "todo", "document", "pdf", "office", "powerpoint", "obsidian")),
    ("communication", ("slack", "telegram", "discord", "sms", "message", "chat", "teams", "imessage")),
    ("web", ("browser", "web", "http", "url", "search", "crawl", "scrape", "download")),
    ("system", ("file", "shell", "process", "system", "docker", "cron", "monitor", "disk")),
    ("finance", ("payment", "invoice", "crypto", "polymarket", "trading", "stock", "budget")),
]

_DEFAULT_CATEGORY = "general"


def _haystack(name: str, description: str, tags: Iterable[str] | None) -> str:
    parts = [str(name or ""), str(description or "")]
    if tags:
        parts.extend(str(t) for t in tags)
    return " ".join(parts).lower()


def categorize(
    name: str,
    description: str = "",
    tags: Iterable[str] | None = None,
    existing: str = "",
) -> str:
    """Pick a Skills sub-category. Honors a valid existing category if present."""
    valid = {c for c, _ in _CATEGORY_KEYWORDS} | {_DEFAULT_CATEGORY}
    ex = str(existing or "").strip().lower()
    if ex and ex in valid:
        return ex
    hay = _haystack(name, description, tags)
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in hay for kw in keywords):
            return category
    # Keep an explicit non-empty existing category even if it's non-standard,
    # rather than flattening a curated label to "general".
    return ex or _DEFAULT_CATEGORY


def route(artifact: dict[str, Any]) -> str:
    """Which sidebar section a discovered artifact belongs to.

    Returns one of: ``"repos"`` (GitHub Repos), ``"plugins"`` (dashboard
    plugins), or ``"skills"`` (the Skills view). Skills are the default —
    most discoveries are capabilities.
    """
    kind = str((artifact or {}).get("kind") or "").lower()
    if kind in ("repo", "repository", "github"):
        return "repos"
    if kind in ("plugin", "dashboard-plugin"):
        return "plugins"
    # A full_name that looks like owner/repo with no skill payload → repos.
    full_name = str((artifact or {}).get("full_name") or "")
    if "/" in full_name and not artifact.get("skill") and not artifact.get("skills"):
        return "repos"
    return "skills"
