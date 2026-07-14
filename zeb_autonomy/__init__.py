"""ZebOS autonomy subsystem — the always-on background capabilities.

This package holds the self-directed behaviors that make ZebOS an
"autonomous OS" rather than a request/response agent: periodic background
bots (knowledge firehose, self-improvement, file organizer), always-on
services (memory persistence, state sync, file index), and the decision
engine + notifier that let Zeb act — and reach Johnny — on its own.

Design principles (shared by every module here):

* **No external dependencies.** Everything runs on the local-model
  backbone (``agent/llama_cpp_adapter.py``), the local filesystem, and
  SQLite under ``<zeb_home>/autonomy/``. Network-using bots (the knowledge
  firehose) degrade gracefully to a no-op when offline instead of failing.
* **Fail-open.** A bot raising must never take down the scheduler, the
  gateway, or the core agent loop. Every run is wrapped; a failure is
  logged and reported, never propagated.
* **Runs alongside the core.** The scheduler is a daemon thread started
  from the gateway lifecycle (same pattern as ``gateway/self_healing.py``),
  so autonomy comes online with the gateway and shuts down cleanly with it.
* **Local-model first.** Bots that need reasoning call
  ``BotContext.complete()``, which routes to the baked-in GGUF backbone —
  never a hard dependency on an API key.
"""

from zeb_autonomy.base import Bot, BotContext, BotResult
from zeb_autonomy.agent_builder import AgentSpec, build_agent, spec_from_template

__all__ = [
    "AgentSpec",
    "Bot",
    "BotContext",
    "BotResult",
    "build_agent",
    "spec_from_template",
]
