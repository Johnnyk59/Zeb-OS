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

1. installs system deps (`python3`, `venv`, `git`, Node/npm, build tools);
2. creates the unprivileged `zeb` service account;
3. installs `cloudflared` for the public dashboard tunnel;
4. clones/updates the repo into `/opt/zeb`;
5. builds a virtualenv, installs Zeb and builds the React dashboard;
6. creates the persistent state dirs under `/var/lib/zeb`;
7. writes a root-only secrets file at `/etc/zeb/zeb.env`;
8. installs, enables and starts the dashboard and tunnel services.

## Service management

```
systemctl status zeb      # is it running?
systemctl restart zeb     # restart
journalctl -u zeb -f      # live logs (the DASHBOARD LOGIN box prints here)
journalctl -u zeb-tunnel -f # public link and tunnel logs
```

`Restart=always` means a crash brings Zeb straight back; `WantedBy=multi-user.target`
means it starts on boot. The service runs as the `zeb` account, which owns the
checkout and persistent state. It has full access to Zeb's workspace, but the
autonomous process is not granted root access to the entire VPS.

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

The React dashboard is built into `/opt/zeb/zeb_cli/web_dist/` during install and
served by `zeb dashboard` on port `9119`. Its `/api/ws` endpoint hosts the
in-process gateway used by the Chat tab, so one native systemd unit covers the
selected dashboard and its chat runtime.

## Hardware Zeb runs on

Zeb is hardwired to know its own machine (see `ZEB_HARDWARE` in
`zeb_chat/stores.py`): **32 GB RAM, 8 CPU cores, 400 GB storage, no GPU
(CPU-only inference)**. Local models are sized for CPU; heavy reasoning leans on
connected cloud providers.

## Permanent public URL (Cloudflare named tunnel)

Set `ZEB_TUNNEL_TOKEN` and `ZEB_TUNNEL_HOSTNAMES` in `/etc/zeb/zeb.env`.
Create a Cloudflare Tunnel, copy its token, and configure a Public Hostname
for your domain pointing to `http://localhost:9119`. The installer runs
`cloudflared` as `zeb-tunnel.service`, prints the public URL and credentials in
the journal, and restarts the tunnel automatically. If no token is set, it
falls back to a temporary `trycloudflare.com` URL.

Johnny's default bare-metal hostname is
`smartestmotherfuckerever.zeb.autos`. The fresh-install env template sets that
hostname automatically; Cloudflare still needs a matching Published
Application route targeting `http://localhost:9119`.

## Instagram webhook

Instagram perception is webhook-driven. Set `IG_APP_ID`, `IG_APP_SECRET`,
`IG_ACCESS_TOKEN`, `IG_BUSINESS_ACCOUNT_ID`, and a private `IG_VERIFY_TOKEN` in
`/etc/zeb/zeb.env`. Point Meta's callback URL at
`https://your-host/api/instagram/webhook`, subscribe the app to Instagram
messaging events, and complete Meta's required app review. Zeb validates Meta's
signature, stores normalized inbound messages and reel attachments under
`/var/lib/zeb/instagram/inbox.json`, and adds them to shared context. The
pipeline remains inert until credentials and webhook verification are present.
Authenticated automation can send a reply through `POST /api/instagram/reply`
with `{"recipient_id":"...","text":"..."}`. Set `IG_GRAPH_VERSION` if the
Meta app requires a different Graph API version.

## Docker is still supported

The container path (`docker/`, `Dockerfile`) still works and is unchanged. Pick
one: bare-metal (this doc) **or** Docker — not both against the same state dir.
