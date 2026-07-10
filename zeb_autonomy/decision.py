"""Autonomous decision engine (feature 1).

Zeb doesn't wait to be told something's wrong. On a short cadence the
decision engine polls a set of *sensors* — cheap functions that inspect
live state (self-healing health, disk, workspace clutter, notification
backlog) and emit :class:`Signal`s. The engine then decides, without
instruction, what warrants action: it escalates warning/critical signals
to Johnny through the notifier and records every decision to
``<zeb_home>/autonomy/decisions.jsonl`` for the self-improvement loop and
audit.

When the local model is available it's used to phrase the situation as one
human-readable heads-up; when it isn't (offline first-run), the engine
falls back to a deterministic rule-based summary. Either way it decides and
acts — the model only changes the wording, never whether Zeb responds.

Sensors are injected (default set below) so the engine is unit-testable
with fake sensors and a fake ``BotContext`` — no gateway, model, or disk
required.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from zeb_autonomy.base import BotContext, BotResult

Sensor = Callable[[BotContext], "list[Signal]"]

_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


@dataclass
class Signal:
    name: str
    severity: str  # "info" | "warning" | "critical"
    summary: str
    action: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _health_sensor(ctx: BotContext) -> list[Signal]:
    """Lift self-healing health checks into decision signals."""
    try:
        from gateway.self_healing import run_health_checks
    except Exception:
        return []
    signals: list[Signal] = []
    for r in run_health_checks(ctx.config):
        if r.status == "ok":
            continue
        signals.append(
            Signal(
                name=f"health.{r.component}",
                severity="critical" if r.status == "critical" else "warning",
                summary=r.message,
                action="auto-repaired" if r.repaired else "needs attention",
            )
        )
    return signals


def _clutter_sensor(ctx: BotContext) -> list[Signal]:
    """Flag when the workspace root has accumulated a lot of loose files.

    A high loose-file count is the signal the decision engine uses to
    recommend running the nightly organizer early. Threshold is configurable
    under ``autonomy.decision.clutter_threshold``.
    """
    try:
        threshold = int(
            ((ctx.config.get("autonomy") or {}).get("decision") or {}).get(
                "clutter_threshold", 200
            )
        )
    except Exception:
        threshold = 200
    root = ctx.zeb_home
    try:
        loose = sum(1 for p in root.iterdir() if p.is_file())
    except OSError:
        return []
    if loose <= threshold:
        return []
    return [
        Signal(
            name="workspace.clutter",
            severity="warning",
            summary=f"{loose} loose files in {root} (threshold {threshold})",
            action="run file organizer",
            details={"loose": loose, "threshold": threshold},
        )
    ]


def default_sensors() -> list[Sensor]:
    return [_health_sensor, _clutter_sensor]


class DecisionEngine:
    name = "decision_engine"

    def __init__(self, sensors: "list[Sensor] | None" = None):
        self.sensors = sensors if sensors is not None else default_sensors()

    def run(self, ctx: BotContext) -> BotResult:
        signals: list[Signal] = []
        for sensor in self.sensors:
            try:
                signals.extend(sensor(ctx) or [])
            except Exception as exc:
                ctx.log.debug("decision sensor %r failed: %s", getattr(sensor, "__name__", sensor), exc)

        self._record(ctx, signals)

        actionable = [s for s in signals if _SEVERITY_RANK.get(s.severity, 0) >= 1]
        if not actionable:
            return BotResult(bot=self.name, ok=True, summary=f"{len(signals)} signals, none actionable")

        worst = max(actionable, key=lambda s: _SEVERITY_RANK.get(s.severity, 0))
        message = self._phrase(ctx, actionable)
        return BotResult(
            bot=self.name,
            ok=True,
            summary=f"{len(actionable)} actionable signal(s); escalating",
            details={"signals": [s.__dict__ for s in actionable]},
            notify=True,
            notify_message=message,
            notify_level=worst.severity,
        )

    def _phrase(self, ctx: BotContext, actionable: list[Signal]) -> str:
        # Deterministic fallback first — always correct, model-independent.
        rule_based = "Heads up — " + "; ".join(
            f"{s.summary} ({s.action})" if s.action else s.summary for s in actionable
        )
        prompt = (
            "You are Zeb, an autonomous OS, writing a short heads-up to Johnny. "
            "Summarize these system signals in ONE friendly sentence, most "
            "important first, no preamble:\n"
            + "\n".join(f"- [{s.severity}] {s.summary} — {s.action}" for s in actionable)
        )
        phrased = ctx.complete(prompt, max_tokens=120)
        return phrased.strip() if phrased else rule_based

    def _record(self, ctx: BotContext, signals: list[Signal]) -> None:
        try:
            path = ctx.autonomy_dir() / "decisions.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {"ts": time.time(), "signals": [s.__dict__ for s in signals]},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except OSError as exc:
            ctx.log.debug("decision: could not record decisions: %s", exc)
