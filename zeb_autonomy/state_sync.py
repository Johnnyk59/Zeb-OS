"""Cross-instance state sync for the autonomy subsystem (feature 5).

Zeb may run on more than one machine. This module keeps their autonomy state
loosely converged using nothing but a shared filesystem directory (a synced
folder, an NFS mount, a Dropbox — anything both instances can read/write). No
server, no network protocol, no third-party deps.

Model: each instance periodically *exports* a snapshot of its own autonomy
state into ``<shared_dir>/<instance_id>/`` and *imports* every other
instance's snapshot into its local state. Convergence properties:

  * ``memory.db``            — merged via :meth:`MemoryStore.merge_from`
                               (INSERT OR IGNORE by content-stable id).
  * ``*.jsonl`` (notifications, decisions) — order-preserving line union,
                               exact-duplicate lines dropped.
  * ``schedule_state.json``  — per-bot MAX last-run (so a bot that fired more
                               recently on any instance is treated as such).

All operations are fail-open: a bad/partial snapshot is skipped, and the bot's
``run`` never raises.
"""

from __future__ import annotations

import json
import shutil
import socket
import time
from pathlib import Path
from typing import Any, Optional

from zeb_autonomy.base import BotContext, BotResult

# Files copied verbatim into a snapshot (relative to zeb_home).
_SNAPSHOT_FILES = (
    "autonomy/memory.db",
    "autonomy/notifications.jsonl",
    "autonomy/schedule_state.json",
    "autonomy/decisions.jsonl",
)

_JSONL_FILES = ("notifications.jsonl", "decisions.jsonl")


def _sync_cfg(config: dict[str, Any]) -> dict[str, Any]:
    try:
        return dict(config.get("autonomy", {}).get("state_sync", {}) or {})
    except AttributeError:
        return {}


def instance_id_from_config(config: dict[str, Any]) -> str:
    """Derive this instance's id: explicit config value, else the hostname."""
    cfg = _sync_cfg(config)
    iid = cfg.get("instance_id")
    if iid:
        return str(iid)
    return socket.gethostname()


# ── export ──────────────────────────────────────────────────────────────
def export_snapshot(zeb_home: Path, dest_dir: Path, instance_id: str) -> Path:
    """Copy this instance's autonomy state into ``dest_dir/<instance_id>/``.

    Only files that exist are copied. Writes a ``manifest.json`` recording the
    instance id, export time, and each copied file's source mtime. Returns the
    snapshot directory.
    """
    zeb_home = Path(zeb_home)
    snap = Path(dest_dir) / instance_id
    snap.mkdir(parents=True, exist_ok=True)

    files: dict[str, float] = {}
    for rel in _SNAPSHOT_FILES:
        src = zeb_home / rel
        if not src.exists():
            continue
        name = Path(rel).name
        try:
            shutil.copy2(src, snap / name)
            files[name] = src.stat().st_mtime
        except OSError:
            continue

    manifest = {
        "instance_id": instance_id,
        "exported_at": time.time(),
        "files": files,
    }
    try:
        (snap / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass
    return snap


# ── import helpers ────────────────────────────────────────────────────────
def _merge_jsonl(local_path: Path, incoming_path: Path) -> int:
    """Union incoming lines into local, preserving order, dropping exact dupes.

    Returns the number of new lines added.
    """
    existing: list[str] = []
    seen: set[str] = set()
    if local_path.exists():
        for line in local_path.read_text("utf-8").splitlines():
            existing.append(line)
            seen.add(line)

    added = 0
    for line in incoming_path.read_text("utf-8").splitlines():
        if line not in seen:
            existing.append(line)
            seen.add(line)
            added += 1

    if added:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(existing)
        if text:
            text += "\n"
        local_path.write_text(text, encoding="utf-8")
    return added


def _merge_schedule_state(local_path: Path, incoming_path: Path) -> int:
    """Merge schedule state taking the MAX last-run per bot.

    Returns the number of bot entries updated (new or bumped to a later run).
    """
    def _load(p: Path) -> dict[str, float]:
        try:
            return {
                k: float(v)
                for k, v in json.loads(p.read_text("utf-8")).items()
            }
        except Exception:
            return {}

    local = _load(local_path)
    incoming = _load(incoming_path)
    updated = 0
    for bot, ts in incoming.items():
        if ts > local.get(bot, float("-inf")):
            local[bot] = ts
            updated += 1
    if updated:
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = local_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(local), encoding="utf-8")
            tmp.replace(local_path)
        except OSError:
            pass
    return updated


def import_snapshot(zeb_home: Path, src_snapshot_dir: Path) -> dict[str, Any]:
    """Merge a single instance's snapshot into the local autonomy state.

    Returns a summary dict of what changed. Fail-open per-file: a missing or
    corrupt component is skipped without aborting the rest.
    """
    zeb_home = Path(zeb_home)
    src = Path(src_snapshot_dir)
    summary: dict[str, Any] = {"source": src.name}

    # memory.db — guarded import of MemoryStore to keep this fail-open.
    mem_src = src / "memory.db"
    if mem_src.exists():
        try:
            from zeb_autonomy.memory_store import MemoryStore

            summary["memory"] = MemoryStore(zeb_home).merge_from(mem_src)
        except Exception as exc:
            summary["memory_error"] = str(exc)

    # jsonl unions
    for name in _JSONL_FILES:
        inc = src / name
        if not inc.exists():
            continue
        try:
            summary[name] = _merge_jsonl(zeb_home / "autonomy" / name, inc)
        except OSError as exc:
            summary[f"{name}_error"] = str(exc)

    # schedule state — max last-run per bot
    sched = src / "schedule_state.json"
    if sched.exists():
        try:
            summary["schedule_state"] = _merge_schedule_state(
                zeb_home / "autonomy" / "schedule_state.json", sched
            )
        except OSError as exc:
            summary["schedule_state_error"] = str(exc)

    return summary


# ── bot ─────────────────────────────────────────────────────────────────
class StateSyncBot:
    """Import every other instance's snapshot, then export our own.

    Reads ``config['autonomy']['state_sync']['shared_dir']``. Unset → clean
    no-op. Never raises out of ``run``.
    """

    name = "state_sync"

    def run(self, ctx: BotContext) -> BotResult:
        try:
            cfg = _sync_cfg(ctx.config)
            shared_dir = cfg.get("shared_dir")
            if not shared_dir:
                return BotResult(
                    bot=self.name, ok=True, summary="no shared_dir configured"
                )

            shared = Path(shared_dir)
            iid = instance_id_from_config(ctx.config)
            shared.mkdir(parents=True, exist_ok=True)

            imported: list[dict[str, Any]] = []
            if shared.exists():
                for child in sorted(shared.iterdir()):
                    if not child.is_dir() or child.name == iid:
                        continue
                    imported.append(import_snapshot(ctx.zeb_home, child))

            snap = export_snapshot(ctx.zeb_home, shared, iid)

            return BotResult(
                bot=self.name,
                ok=True,
                summary=f"synced with {len(imported)} instance(s)",
                details={
                    "instance_id": iid,
                    "imported": imported,
                    "snapshot": str(snap),
                },
            )
        except Exception as exc:  # fail-open
            return BotResult.failed(self.name, f"raised: {exc}")
