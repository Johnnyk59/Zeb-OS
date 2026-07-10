"""Knowledge firehose bot — feature 6 of the ZebOS autonomy subsystem.

Every couple of hours this bot pulls a handful of fresh items on Johnny's
topics of interest, optionally distills them into a short knowledge note with
the local model, and appends them to a growing on-disk knowledge base under
``<zeb_home>/autonomy/knowledge/``.

The bot is deliberately dependency-free and fail-open:

* Web access flows through the single module-level seam :func:`_search_web`,
  which probes the repo's *existing* web capabilities with guarded imports and
  degrades to ``[]`` when the machine is offline or no provider is configured
  (the common case in CI / tests). Tests monkeypatch this one function.
* Reasoning flows through :meth:`BotContext.complete`, which returns ``None``
  when the local backbone is unavailable — handled as a graceful skip.
* ``run`` never raises. Worst case it returns a clean ``ok=True`` no-op.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from zeb_autonomy.base import BotContext, BotResult

DEFAULT_TOPICS = ["artificial intelligence", "technology news"]
_MAX_ITEMS_PER_TOPIC = 5


def _search_web(topic: str, ctx: BotContext) -> list[dict]:
    """Return a list of ``{title, url, snippet}`` dicts for *topic*.

    This is the single seam tests monkeypatch. It tries the repo's existing
    web capabilities in order, adapting whatever shape they return into our
    simple item dict. If none are usable, or any of them raise (e.g. offline,
    no API key, plugin disabled), it returns ``[]`` — it NEVER raises and
    NEVER adds a new dependency.
    """
    # 1) The high-level tool: tools.web_tools.web_search_tool(query, limit)
    #    returns a JSON string {"success", "data": {"web": [{title,url,
    #    description,position}]}}.
    try:
        from tools.web_tools import web_search_tool  # type: ignore

        raw = web_search_tool(topic, _MAX_ITEMS_PER_TOPIC)
        items = _items_from_web_search_json(raw)
        if items:
            return items
    except Exception:
        ctx.log.debug("knowledge_firehose: web_search_tool unavailable", exc_info=True)

    # 2) The registry's active provider: provider.search(query, limit) returns
    #    a dict shaped like {"data": {"web": [...]}} (same as above).
    try:
        from agent.web_search_registry import (  # type: ignore
            get_active_search_provider,
        )

        provider = get_active_search_provider()
        if provider is not None and provider.supports_search():
            resp = provider.search(topic, _MAX_ITEMS_PER_TOPIC)
            items = _items_from_search_dict(resp)
            if items:
                return items
    except Exception:
        ctx.log.debug(
            "knowledge_firehose: web_search_registry unavailable", exc_info=True
        )

    # 3) A directly-resolved provider from the provider module, if present.
    try:
        from agent.web_search_provider import (  # type: ignore
            get_active_search_provider as _get_provider,
        )

        provider = _get_provider()
        if provider is not None and getattr(provider, "supports_search", lambda: True)():
            resp = provider.search(topic, _MAX_ITEMS_PER_TOPIC)
            items = _items_from_search_dict(resp)
            if items:
                return items
    except Exception:
        ctx.log.debug(
            "knowledge_firehose: web_search_provider unavailable", exc_info=True
        )

    return []


def _items_from_web_search_json(raw: Any) -> list[dict]:
    """Parse the JSON string returned by ``web_search_tool`` into items."""
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    return _items_from_search_dict(data)


def _items_from_search_dict(data: Any) -> list[dict]:
    """Adapt a provider search response dict into ``{title,url,snippet}``."""
    if not isinstance(data, dict):
        return []
    if data.get("success") is False:
        return []
    web = data.get("data", {})
    if isinstance(web, dict):
        rows = web.get("web") or web.get("results") or []
    elif isinstance(web, list):
        rows = web
    else:
        rows = []
    items: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = row.get("url") or row.get("link") or ""
        title = row.get("title") or row.get("name") or url or "(untitled)"
        snippet = (
            row.get("snippet")
            or row.get("description")
            or row.get("content")
            or ""
        )
        if not url and not snippet:
            continue
        items.append(
            {"title": str(title), "url": str(url), "snippet": str(snippet)}
        )
    return items


def _summarize(topic: str, items: list[dict], ctx: BotContext) -> str | None:
    """Ask the local model for a short knowledge note. None if unavailable."""
    lines = []
    for it in items:
        lines.append(f"- {it['title']} ({it['url']}): {it['snippet']}")
    joined = "\n".join(lines)
    prompt = (
        f"You are Zeb, keeping a running knowledge journal for Johnny.\n"
        f"Here are fresh web results about \"{topic}\":\n{joined}\n\n"
        f"Write a concise 2-4 sentence note capturing what's new or notable. "
        f"Be factual and specific; no preamble."
    )
    try:
        text = ctx.complete(prompt, system="You distill web findings into brief notes.", max_tokens=256)
    except Exception:
        ctx.log.debug("knowledge_firehose: complete() raised", exc_info=True)
        return None
    if not text or not str(text).strip():
        return None
    return str(text).strip()


class KnowledgeFirehoseBot:
    """Periodically pull and journal fresh knowledge on Johnny's topics."""

    name = "knowledge_firehose"

    def run(self, ctx: BotContext) -> BotResult:
        try:
            return self._run(ctx)
        except Exception as exc:  # never raise out of run()
            ctx.log.exception("knowledge_firehose: unexpected failure")
            return BotResult.failed(self.name, f"unexpected error: {exc}")

    def _run(self, ctx: BotContext) -> BotResult:
        kcfg = (ctx.config.get("autonomy", {}) or {}).get("knowledge", {}) or {}
        topics = kcfg.get("topics") or DEFAULT_TOPICS
        if not isinstance(topics, list):
            topics = DEFAULT_TOPICS
        notify_enabled = bool(kcfg.get("notify", False))

        now = datetime.now(timezone.utc)
        day = now.strftime("%Y-%m-%d")
        ts = now.isoformat()

        knowledge_dir = ctx.autonomy_dir("knowledge")
        md_path = knowledge_dir / f"{day}.md"
        jsonl_path = knowledge_dir / "knowledge.jsonl"

        total_items = 0
        notes_written = 0
        md_sections: list[str] = []
        jsonl_lines: list[str] = []

        for topic in topics:
            if not isinstance(topic, str) or not topic.strip():
                continue
            try:
                items = _search_web(topic, ctx)
            except Exception:
                # _search_web is contracted never to raise, but stay defensive.
                ctx.log.debug("knowledge_firehose: _search_web raised", exc_info=True)
                items = []
            if not items:
                continue
            total_items += len(items)

            for it in items:
                jsonl_lines.append(
                    json.dumps(
                        {
                            "ts": ts,
                            "topic": topic,
                            "title": it.get("title", ""),
                            "url": it.get("url", ""),
                            "snippet": it.get("snippet", ""),
                        },
                        ensure_ascii=False,
                    )
                )

            note = _summarize(topic, items, ctx)
            section = [f"## {topic} — {ts}", ""]
            if note:
                section.append(note)
                notes_written += 1
            else:
                # Model offline: still journal the raw items so nothing is lost.
                for it in items:
                    section.append(f"- [{it.get('title','')}]({it.get('url','')}) — {it.get('snippet','')}")
            section.append("")
            md_sections.append("\n".join(section))

        if total_items == 0:
            return BotResult(
                bot=self.name,
                ok=True,
                summary="web unavailable or no results; skipped",
            )

        # Persist: append markdown sections and jsonl lines.
        try:
            header_needed = not md_path.exists()
            with md_path.open("a", encoding="utf-8") as fh:
                if header_needed:
                    fh.write(f"# Knowledge — {day}\n\n")
                fh.write("\n".join(md_sections))
                if md_sections:
                    fh.write("\n")
            with jsonl_path.open("a", encoding="utf-8") as fh:
                for line in jsonl_lines:
                    fh.write(line + "\n")
        except OSError as exc:
            return BotResult.failed(self.name, f"write failed: {exc}")

        summary = (
            f"journaled {total_items} item(s) across {len(topics)} topic(s); "
            f"{notes_written} note(s) summarized"
        )
        result = BotResult(
            bot=self.name,
            ok=True,
            summary=summary,
            details={
                "items": total_items,
                "notes": notes_written,
                "file": str(md_path),
            },
        )
        if notify_enabled:
            result.notify = True
            result.notify_message = summary
            result.notify_level = "info"
        return result


# Module-level instance the scheduler can register directly.
bot = KnowledgeFirehoseBot()
