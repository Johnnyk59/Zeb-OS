"""Search GitHub for open-source repositories matching a description.

Backs the dashboard's "Scan GitHub" button: the user describes what they
need, Zeb queries GitHub's public search API, and returns the top matching
open-source repos to save for later integration. No API token is required
(unauthenticated search works, just rate-limited); if ``GITHUB_TOKEN`` /
``GH_TOKEN`` is present it's used to raise the rate limit.

Uses the stdlib ``urllib`` so it needs no extra dependency; it honours the
``HTTPS_PROXY`` environment proxy automatically. Entirely fail-soft — any
error returns an empty list with an error string rather than raising.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("zeb_chat")

_API = "https://api.github.com/search/repositories"


def _token() -> str:
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"):
        v = os.environ.get(var, "").strip()
        if v:
            return v
    return ""


def scan(query: str, limit: int = 10) -> dict[str, Any]:
    """Search GitHub repositories for ``query``. Returns {results, error}.

    ``query`` is the user's free-text description of what they need. We bias
    toward well-maintained open source by sorting on stars. Each result is a
    dict shaped for ``RepoStore.add``.
    """
    query = (query or "").strip()
    if not query:
        return {"results": [], "error": "empty query"}

    # Bias to real, usable open source: reasonably starred, not archived.
    q = f"{query} stars:>50"
    params = urllib.parse.urlencode(
        {"q": q, "sort": "stars", "order": "desc", "per_page": max(1, min(30, limit))}
    )
    url = f"{_API}?{params}"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ZebOS-repo-scan",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    tok = _token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001 - fail-soft for the dashboard
        logger.info("GitHub scan failed: %s", exc)
        return {"results": [], "error": f"GitHub search failed: {exc}"}

    out = []
    for item in (payload.get("items") or [])[:limit]:
        if not isinstance(item, dict):
            continue
        # Only surface open-source (licensed / public, non-archived) repos.
        if item.get("archived"):
            continue
        out.append(
            {
                "full_name": item.get("full_name") or "",
                "url": item.get("html_url") or "",
                "description": item.get("description") or "",
                "stars": int(item.get("stargazers_count") or 0),
                "language": item.get("language") or "",
                "source": "scan",
            }
        )
    return {"results": out, "error": ""}
