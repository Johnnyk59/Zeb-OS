"""Hardwired agent-builder for Zeb.

This is the built-in, ready-made system Zeb uses to spin up a new sub-agent
instead of improvising one each time (directive #6). It is deliberately a
*scaffold*, not a magic factory: it lays down the real, consistent structure a
new agent needs and wires it into the dashboard, so Zeb never has to reinvent
the plumbing. What it does, concretely and honestly:

  * writes an agent manifest (name, purpose, model, permissions, skills) under
    ``<zeb_home>/agents/<id>/agent.json``
  * creates a ``skills/`` and ``dashboard/`` directory for the agent
  * assigns a permission profile (inherits Zeb's own access by default)
  * registers the agent + its future dashboard URL with the dashboard's
    ``AgentStore`` so a top-bar button lights up for it — no redeploy

It does NOT write the agent's business logic (the actual trading/jewelry/social
behaviour) — that is Zeb's job to fill in, turn by turn. This module gives Zeb
a proven starting point and the wiring; the intelligence is Zeb's.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _zeb_home() -> Path:
    try:
        import zeb_constants

        return Path(zeb_constants.get_zeb_home())
    except Exception:
        return Path.home() / ".zeb"


def _agents_root() -> Path:
    return _zeb_home() / "agents"


# Permission profiles. "inherit" == the same full access level Zeb itself has;
# "scoped" narrows a fresh agent to a working directory + named tools.
PERMISSION_PROFILES = {
    "inherit": {
        "description": "Full access, equal to Zeb's own (creator-level).",
        "filesystem": "full",
        "network": "full",
        "shell": True,
        "confirm_destructive": True,  # honest default; opt-out is a Zeb decision
    },
    "scoped": {
        "description": "Sandboxed to the agent's own workdir and named tools.",
        "filesystem": "workdir",
        "network": "allowlist",
        "shell": False,
        "confirm_destructive": True,
    },
}

# Ready-made starting templates for the three seed agents plus a generic one.
TEMPLATES = {
    "quant": {
        "label": "Quant Bot",
        "purpose": "Quantitative market research, signals and backtests.",
        "suggested_skills": ["data-fetch", "backtest", "risk-report"],
        "model": "local",
    },
    "jewelry": {
        "label": "Jewelry Bot",
        "purpose": "Jewelry catalog, pricing and listing management.",
        "suggested_skills": ["image-tag", "price-lookup", "listing-writer"],
        "model": "local",
    },
    "socials": {
        "label": "Socials Agent",
        "purpose": "Social content planning, drafting and scheduling.",
        "suggested_skills": ["content-plan", "caption-writer", "scheduler"],
        "model": "local",
    },
    "generic": {
        "label": "New Agent",
        "purpose": "A general-purpose Zeb sub-agent.",
        "suggested_skills": [],
        "model": "local",
    },
}


@dataclass
class AgentSpec:
    """Everything needed to stand up one agent, filled from a template + args."""

    id: str
    label: str
    purpose: str
    model: str = "local"
    permission_profile: str = "inherit"
    skills: list[str] = field(default_factory=list)
    dashboard_url: str = ""
    created_at: float = field(default_factory=time.time)

    def permissions(self) -> dict:
        return PERMISSION_PROFILES.get(
            self.permission_profile, PERMISSION_PROFILES["inherit"]
        )

    def manifest(self) -> dict:
        d = asdict(self)
        d["permissions"] = self.permissions()
        return d


def spec_from_template(agent_id: str, template: str | None = None, **overrides) -> AgentSpec:
    """Build an :class:`AgentSpec` from a template, applying any overrides."""
    agent_id = str(agent_id or "").strip().lower()
    if not agent_id:
        raise ValueError("agent_id is required")
    tpl = TEMPLATES.get(template or agent_id, TEMPLATES["generic"])
    spec = AgentSpec(
        id=agent_id,
        label=str(overrides.get("label") or tpl["label"]),
        purpose=str(overrides.get("purpose") or tpl["purpose"]),
        model=str(overrides.get("model") or tpl["model"]),
        permission_profile=str(overrides.get("permission_profile") or "inherit"),
        skills=list(overrides.get("skills") or tpl["suggested_skills"]),
        dashboard_url=str(overrides.get("dashboard_url") or ""),
    )
    return spec


def build_agent(agent_id: str, template: str | None = None, **overrides) -> dict:
    """Scaffold an agent on disk and register it with the dashboard.

    Returns the written manifest. Fully idempotent-ish: re-running updates the
    manifest and re-registers the dashboard button.
    """
    spec = spec_from_template(agent_id, template, **overrides)
    root = _agents_root() / spec.id
    (root / "skills").mkdir(parents=True, exist_ok=True)
    (root / "dashboard").mkdir(parents=True, exist_ok=True)

    manifest = spec.manifest()
    (root / "agent.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Wire the agent to its top-bar button (no redeploy needed).
    register_dashboard(
        spec.id,
        dashboard_url=spec.dashboard_url,
        status="scaffolded" if not spec.dashboard_url else "ready",
        label=spec.label,
    )
    return manifest


def register_dashboard(
    agent_id: str,
    dashboard_url: str = "",
    status: str = "ready",
    label: str | None = None,
) -> dict:
    """Point a top-bar button at a dashboard Zeb built for ``agent_id``."""
    try:
        from zeb_chat.stores import AgentStore

        patch = {"dashboard_url": dashboard_url, "status": status}
        if label:
            patch["label"] = label
        return AgentStore().register(agent_id, patch)
    except Exception:
        return {}


def list_built_agents() -> list[dict]:
    """Every agent scaffolded on disk (manifest summaries)."""
    out: list[dict] = []
    root = _agents_root()
    if not root.exists():
        return out
    for child in sorted(root.iterdir()):
        mf = child / "agent.json"
        if mf.is_file():
            try:
                out.append(json.loads(mf.read_text(encoding="utf-8")))
            except Exception:
                continue
    return out
