"""Self-improvement bot — feature 7 of the ZebOS autonomy subsystem.

Every twelve hours Zeb looks back over its recent conversations with Johnny
and tries to evolve a more human, better-matched communication style. It reads
recent interaction material, asks the local model (speaking *as Zeb*) to
analyze Johnny's tone/preferences and Zeb's own replies, and writes a small,
self-contained set of persona guidance files under
``<zeb_home>/autonomy/persona/``:

* ``persona_notes.md`` — append-only, dated log of each reflection.
* ``style_guide.md`` — overwritten each run with the current-best distilled
  bullets (the "latest guidance" Zeb should follow).

Safety: this bot NEVER touches ``SOUL.md`` or anything outside
``autonomy/persona/``. It is fail-open — when there is no material, no model,
or anything raises, it returns a clean ``ok=True`` no-op and never spams.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zeb_autonomy.base import BotContext, BotResult

_MAX_MATERIAL_CHARS = 12000
_RECENT_LIMIT = 200


def _gather_material(ctx: BotContext) -> str:
    """Collect recent conversation material, best-effort. '' if none.

    Order: (a) MemoryStore.recent_interactions (module may not exist yet),
    then (b) recent transcript files under ``<zeb_home>/sessions/``.
    """
    # (a) MemoryStore — imported lazily inside run because another agent may
    #     be creating this module in parallel; absence is not an error.
    try:
        from zeb_autonomy.memory_store import MemoryStore  # type: ignore

        rows = MemoryStore(ctx.zeb_home).recent_interactions(limit=_RECENT_LIMIT)
        text = _rows_to_text(rows)
        if text.strip():
            return text[:_MAX_MATERIAL_CHARS]
    except Exception:
        ctx.log.debug("self_improvement: MemoryStore unavailable", exc_info=True)

    # (b) Fall back to on-disk session transcripts.
    try:
        text = _sessions_to_text(ctx.zeb_home / "sessions")
        if text.strip():
            return text[:_MAX_MATERIAL_CHARS]
    except Exception:
        ctx.log.debug("self_improvement: sessions scan failed", exc_info=True)

    return ""


def _rows_to_text(rows: Any) -> str:
    """Flatten memory rows into a compact role: text transcript."""
    if not rows:
        return ""
    parts: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            role = row.get("role") or row.get("speaker") or row.get("who") or "?"
            content = (
                row.get("content")
                or row.get("text")
                or row.get("message")
                or ""
            )
        else:
            role, content = "?", str(row)
        content = str(content).strip()
        if content:
            parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _sessions_to_text(sessions_dir: Path) -> str:
    """Read recent *.json / *.jsonl transcripts under sessions_dir."""
    if not sessions_dir.exists() or not sessions_dir.is_dir():
        return ""
    files = [
        p
        for p in sessions_dir.rglob("*")
        if p.is_file() and p.suffix in (".json", ".jsonl")
    ]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    parts: list[str] = []
    total = 0
    for path in files:
        if total >= _MAX_MATERIAL_CHARS:
            break
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        chunk = _extract_from_transcript(raw, path.suffix)
        if chunk:
            parts.append(chunk)
            total += len(chunk)
    return "\n".join(parts)[:_MAX_MATERIAL_CHARS]


def _extract_from_transcript(raw: str, suffix: str) -> str:
    """Best-effort turn extraction from a json/jsonl transcript blob."""
    lines: list[str] = []
    if suffix == ".jsonl":
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            lines.append(_turn_str(obj))
    else:
        try:
            obj = json.loads(raw)
        except ValueError:
            # Not parseable JSON — fall back to the raw text itself.
            return raw.strip()
        if isinstance(obj, list):
            for item in obj:
                lines.append(_turn_str(item))
        elif isinstance(obj, dict):
            msgs = obj.get("messages") or obj.get("turns") or obj.get("history")
            if isinstance(msgs, list):
                for item in msgs:
                    lines.append(_turn_str(item))
            else:
                lines.append(_turn_str(obj))
    return "\n".join(l for l in lines if l)


def _turn_str(obj: Any) -> str:
    if not isinstance(obj, dict):
        return str(obj).strip()
    role = obj.get("role") or obj.get("speaker") or obj.get("who") or "?"
    content = obj.get("content") or obj.get("text") or obj.get("message") or ""
    if isinstance(content, (list, dict)):
        content = json.dumps(content, ensure_ascii=False)
    content = str(content).strip()
    return f"{role}: {content}" if content else ""


def _distill(material: str, ctx: BotContext) -> str | None:
    """Ask the model (as Zeb) for 3-5 first-person guidance bullets."""
    prompt = (
        "You are Zeb reflecting on your recent conversations with Johnny "
        "(transcript below). Analyze Johnny's tone, vocabulary, and what he "
        "seems to prefer, and critique your own replies. Then write 3 to 5 "
        "concise, first-person bullet points ('I will ...') describing how to "
        "sound more human and better matched to Johnny going forward. Output "
        "only the bullets, one per line, starting with '- '.\n\n"
        "--- RECENT CONVERSATION MATERIAL ---\n"
        f"{material}\n"
        "--- END ---"
    )
    try:
        text = ctx.complete(
            prompt,
            system="You are Zeb, improving your own communication style.",
            max_tokens=384,
        )
    except Exception:
        ctx.log.debug("self_improvement: complete() raised", exc_info=True)
        return None
    if not text or not str(text).strip():
        return None
    return str(text).strip()


class SelfImprovementBot:
    """Reflect on recent chats and evolve Zeb's persona guidance."""

    name = "self_improvement"

    def run(self, ctx: BotContext) -> BotResult:
        try:
            return self._run(ctx)
        except Exception as exc:  # never raise out of run()
            ctx.log.exception("self_improvement: unexpected failure")
            return BotResult.failed(self.name, f"unexpected error: {exc}")

    def _run(self, ctx: BotContext) -> BotResult:
        scfg = (ctx.config.get("autonomy", {}) or {}).get("self_improvement", {}) or {}
        notify_enabled = bool(scfg.get("notify", False))

        material = _gather_material(ctx)
        if not material.strip():
            return BotResult(
                bot=self.name,
                ok=True,
                summary="no conversation material / model offline; skipped",
            )

        bullets = _distill(material, ctx)
        if not bullets:
            return BotResult(
                bot=self.name,
                ok=True,
                summary="no conversation material / model offline; skipped",
            )

        now = datetime.now(timezone.utc)
        ts = now.isoformat()
        persona_dir = ctx.autonomy_dir("persona")
        notes_path = persona_dir / "persona_notes.md"
        guide_path = persona_dir / "style_guide.md"

        try:
            with notes_path.open("a", encoding="utf-8") as fh:
                fh.write(f"## Reflection — {ts}\n\n{bullets}\n\n")
            guide_path.write_text(
                f"# Zeb style guide (current best)\n\n"
                f"_Last updated: {ts}_\n\n{bullets}\n",
                encoding="utf-8",
            )
        except OSError as exc:
            return BotResult.failed(self.name, f"write failed: {exc}")

        summary = f"updated persona guidance from {len(material)} chars of material"
        result = BotResult(
            bot=self.name,
            ok=True,
            summary=summary,
            details={"guide": str(guide_path), "notes": str(notes_path)},
        )
        if notify_enabled:
            result.notify = True
            result.notify_message = "Refined my communication style based on recent chats."
            result.notify_level = "info"
        return result


# Module-level instance the scheduler can register directly.
bot = SelfImprovementBot()
