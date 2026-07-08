"""Resolve ZEB_HOME for standalone skill scripts.

Skill scripts may run outside the Zeb process (e.g. system Python,
nix env, CI) where ``zeb_constants`` is not importable.  This module
provides the same ``get_zeb_home()`` and ``display_zeb_home()``
contracts as ``zeb_constants`` without requiring it on ``sys.path``.

When ``zeb_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``zeb_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``ZEB_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from zeb_constants import display_zeb_home as display_zeb_home
    from zeb_constants import get_zeb_home as get_zeb_home
except (ModuleNotFoundError, ImportError):

    def get_zeb_home() -> Path:
        """Return the Zeb home directory (default: ~/.zeb).

        Mirrors ``zeb_constants.get_zeb_home()``."""
        val = os.environ.get("ZEB_HOME", "").strip()
        return Path(val) if val else Path.home() / ".zeb"

    def display_zeb_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``zeb_constants.display_zeb_home()``."""
        home = get_zeb_home()
        try:
            return "~/" + str(home.relative_to(Path.home()))
        except ValueError:
            return str(home)
