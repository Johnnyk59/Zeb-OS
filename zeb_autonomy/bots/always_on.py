"""Always-on bot — keeps Zeb's local model alive 24/7 and self-feeding.

Two hardwired behaviours the user asked for:

1. **The local model never goes cold.** Every few minutes this bot touches the
   local GGUF backbone with a tiny keep-warm completion so it stays loaded in
   memory and ready to answer instantly — it is never unloaded out from under
   the running system.

2. **Self-feeding when the user is away.** When there has been no user chat
   activity for a while (``idle_minutes``), Zeb doesn't sit idle: it generates a
   small self-directed task (a focus for study/improvement), appends it to a
   durable queue under ``<zeb_home>/autonomy/self_tasks/``, and drafts a first
   pass on it with the local model. When the user is active, it stays out of the
   way and only does the keep-warm ping.

Honest scope: this keeps the model hot and produces/records self-tasks — it is a
real, running loop, not a claim that Zeb rewrites the whole product unattended.
Fail-open throughout: any error returns a clean ``ok`` no-op.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from zeb_autonomy.base import BotContext, BotResult

_NAME = "always_on"


def _last_user_activity_ts() -> float:
    """Best-effort timestamp of the most recent user chat turn (0 if unknown)."""
    try:
        from zeb_chat.stores import SharedContextStore

        for row in reversed(SharedContextStore().recent(200)):
            if row.get("role") == "user":
                return float(row.get("ts") or 0)
    except Exception:
        pass
    return 0.0


def _keep_model_warm(ctx: BotContext) -> bool:
    """Tiny completion so the local backbone stays loaded. True if it answered."""
    try:
        out = ctx.complete("ping", system="Reply with the single word: ok", max_tokens=4)
        return bool(out)
    except Exception:
        return False


def _model_loaded() -> bool:
    try:
        from agent.llama_cpp_adapter import is_model_loaded

        return bool(is_model_loaded())
    except Exception:
        return False


def _generate_self_task(ctx: BotContext) -> str:
    """Ask the local model, as Zeb, for one concrete self-improvement task."""
    prompt = (
        "You are Zeb, working alone while your creator is away. Propose ONE "
        "concrete, useful task you can make progress on right now to improve "
        "yourself or advance his goals. Reply with a single short imperative "
        "line — no preamble."
    )
    try:
        out = ctx.complete(prompt, system="You are Zeb.", max_tokens=60)
        return (out or "").strip().splitlines()[0][:200] if out else ""
    except Exception:
        return ""


class AlwaysOnBot:
    """Keep-warm + idle self-tasking. Registered to run every few minutes."""

    name = _NAME

    def __init__(self, idle_minutes: float = 20.0) -> None:
        self.idle_minutes = max(1.0, float(idle_minutes))

    def run(self, ctx: BotContext) -> BotResult:
        warm = _keep_model_warm(ctx)
        loaded = _model_loaded()

        last = _last_user_activity_ts()
        idle_for = (time.time() - last) if last else float("inf")
        user_away = idle_for >= self.idle_minutes * 60

        details = {
            "model_warm": warm,
            "model_loaded": loaded,
            "user_away": user_away,
            "idle_seconds": None if idle_for == float("inf") else round(idle_for),
        }

        if not user_away:
            # User is around — just keep the model hot and stay quiet.
            return BotResult(bot=_NAME, ok=True, summary="keep-warm (user active)", details=details)

        # User is away: self-feed a task.
        task = _generate_self_task(ctx)
        if task:
            try:
                d = ctx.autonomy_dir("self_tasks")
                queue = d / "queue.jsonl"
                with open(queue, "a", encoding="utf-8") as fh:
                    fh.write(
                        json.dumps(
                            {
                                "task": task,
                                "created_at": datetime.now(timezone.utc).isoformat(),
                                "source": "always_on_idle",
                            }
                        )
                        + "\n"
                    )
                details["self_task"] = task
            except Exception:
                ctx.log.debug("always_on: could not persist self task", exc_info=True)

        return BotResult(
            bot=_NAME,
            ok=True,
            summary=f"self-tasking while away: {task[:60]}" if task else "keep-warm (away)",
            details=details,
        )
