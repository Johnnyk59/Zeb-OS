# Running Zeb bare-metal on the VPS (no Docker)

This is the native deployment: Zeb runs directly on the VPS filesystem as a
`systemd` service — no containers, no volumes. It auto-starts on boot and
auto-restarts if it ever crashes, and **all of Zeb's memory, sessions, skills,
agent manifests and state live natively on disk**, so identity and memory
persist permanently across restarts and updates.

## Install

```
sudo bash scripts/install-baremetal.sh
```

That script (idempotent — safe to re-run to pull new code and restart):

1. installs system deps (`python3`, `venv`, `git`, build tools);
2. clones/updates the repo into `/opt/zeb`;
3. builds a virtualenv and installs Zeb;
4. creates the persistent state dirs under `/var/lib/zeb`;
5. writes a root-only secrets file at `/etc/zeb/zeb.env`;
6. installs, enables and starts the `zeb` systemd service.

## Service management

```
systemctl status zeb      # is it running?
systemctl restart zeb     # restart
journalctl -u zeb -f      # live logs (the DASHBOARD LOGIN box prints here)
```

`Restart=always` means a crash brings Zeb straight back; `WantedBy=multi-user.target`
means it starts on boot.

## Where persistent data lives

Everything Zeb remembers is under **`ZEB_HOME=/var/lib/zeb`** (override via the
env). This directory is never deleted by updates:

| Path | What |
| --- | --- |
| `/var/lib/zeb/chat/` | chat sessions, dashboard state, **shared cross-provider context**, agent registry, API-key vault |
| `/var/lib/zeb/agents/<id>/` | agent manifests + skills + dashboards Zeb builds (see `zeb_autonomy/agent_builder.py`) |
| `/var/lib/zeb/skills/` | Zeb's skills |
| `/var/lib/zeb/instagram/` | Instagram inbox (once a Meta app is connected) |
| `/etc/zeb/zeb.env` | secrets: API keys, tunnel id/hostnames, `IG_*` credentials (chmod 600) |

Because state is decoupled from code, you can wipe and re-clone `/opt/zeb`
without losing anything Zeb has learned — only `/var/lib/zeb` matters for memory.

## Hardware Zeb runs on

Zeb is hardwired to know its own machine (see `ZEB_HARDWARE` in
`zeb_chat/stores.py`): **32 GB RAM, 8 CPU cores, 400 GB storage, no GPU
(CPU-only inference)**. Local models are sized for CPU; heavy reasoning leans on
connected cloud providers.

## Permanent public URL (Cloudflare named tunnel)

Set `ZEB_TUNNEL_ID` + `ZEB_TUNNEL_HOSTNAMES` in `/etc/zeb/zeb.env` and run a
`cloudflared` service alongside Zeb (same approach as the container's
`zeb-tunnel` service) to bind your own domain — the URL stays stable across
restarts. See `docker/s6-rc.d/zeb-tunnel/run` for the ingress config format.

## Docker is still supported

The container path (`docker/`, `Dockerfile`) still works and is unchanged. Pick
one: bare-metal (this doc) **or** Docker — not both against the same state dir.
