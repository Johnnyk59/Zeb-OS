#!/usr/bin/env bash
# Install Zeb on the VPS as a native systemd service (no Docker).
#
# All persistent state (memory, sessions, skills, agent manifests, API keys)
# lives under ZEB_HOME=/var/lib/zeb and survives restarts, updates, and this
# script being re-run. See docs/BARE_METAL.md for the full layout.
#
# Usage (as root):
#   sudo bash scripts/install-baremetal.sh
#
# Idempotent: safe to re-run to pull new code and restart the service.
set -euo pipefail

ZEB_CODE_DIR="${ZEB_CODE_DIR:-/opt/zeb}"
ZEB_HOME="${ZEB_HOME:-/var/lib/zeb}"
ZEB_ENV_FILE="${ZEB_ENV_FILE:-/etc/zeb/zeb.env}"
REPO_URL="${REPO_URL:-https://github.com/Johnnyk59/Zeb-OS.git}"
BRANCH="${BRANCH:-main}"

echo "==> Zeb bare-metal install"
echo "    code:  $ZEB_CODE_DIR"
echo "    state: $ZEB_HOME  (persistent)"
echo "    env:   $ZEB_ENV_FILE"

if [ "$(id -u)" -ne 0 ]; then
  echo "!! Please run as root (sudo)." >&2
  exit 1
fi

# 1. System deps -----------------------------------------------------------
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git curl build-essential

# 2. Code ------------------------------------------------------------------
if [ -d "$ZEB_CODE_DIR/.git" ]; then
  echo "==> Updating existing checkout"
  git -C "$ZEB_CODE_DIR" fetch origin "$BRANCH"
  git -C "$ZEB_CODE_DIR" checkout "$BRANCH"
  git -C "$ZEB_CODE_DIR" pull --ff-only origin "$BRANCH"
else
  echo "==> Cloning $REPO_URL ($BRANCH)"
  git clone --branch "$BRANCH" "$REPO_URL" "$ZEB_CODE_DIR"
fi

# 3. Virtualenv + Python deps ---------------------------------------------
if [ ! -d "$ZEB_CODE_DIR/.venv" ]; then
  python3 -m venv "$ZEB_CODE_DIR/.venv"
fi
"$ZEB_CODE_DIR/.venv/bin/pip" install --upgrade pip
# Install the project (falls back to the core server deps if the full extra
# set is heavy for the box).
"$ZEB_CODE_DIR/.venv/bin/pip" install -e "$ZEB_CODE_DIR" \
  || "$ZEB_CODE_DIR/.venv/bin/pip" install fastapi "uvicorn[standard]" huggingface_hub

# 4. Persistent state dirs -------------------------------------------------
mkdir -p "$ZEB_HOME/chat" "$ZEB_HOME/agents" "$ZEB_HOME/skills" "$ZEB_HOME/instagram"
mkdir -p "$(dirname "$ZEB_ENV_FILE")"
if [ ! -f "$ZEB_ENV_FILE" ]; then
  cat > "$ZEB_ENV_FILE" <<'EOF'
# Zeb secrets & config (root-only). Uncomment/fill as needed.
# ANTHROPIC_API_KEY=
# OPENAI_API_KEY=
# ZEB_DASHBOARD_BASIC_AUTH_USERNAME=admin
# ZEB_DASHBOARD_BASIC_AUTH_PASSWORD=
# --- Cloudflare named tunnel (permanent domain) ---
# ZEB_TUNNEL_ID=
# ZEB_TUNNEL_HOSTNAMES=zeb.autos
# --- Instagram (Meta Business app; pipeline stays inert until all set) ---
# IG_APP_ID=
# IG_APP_SECRET=
# IG_ACCESS_TOKEN=
# IG_BUSINESS_ACCOUNT_ID=
EOF
  chmod 600 "$ZEB_ENV_FILE"
  echo "==> Wrote template $ZEB_ENV_FILE (chmod 600) — edit it to add keys."
fi

# 5. systemd unit ----------------------------------------------------------
install -m 644 "$ZEB_CODE_DIR/packaging/systemd/zeb.service" /etc/systemd/system/zeb.service
# Point the unit at the chosen paths.
sed -i "s#WorkingDirectory=/opt/zeb#WorkingDirectory=$ZEB_CODE_DIR#" /etc/systemd/system/zeb.service
sed -i "s#ZEB_HOME=/var/lib/zeb#ZEB_HOME=$ZEB_HOME#" /etc/systemd/system/zeb.service
sed -i "s#ExecStart=/opt/zeb/.venv/bin/python#ExecStart=$ZEB_CODE_DIR/.venv/bin/python#" /etc/systemd/system/zeb.service

systemctl daemon-reload
systemctl enable zeb.service
systemctl restart zeb.service

echo ""
echo "==> Zeb is installed as a systemd service (auto-start on boot, auto-restart on crash)."
echo "    Status:  systemctl status zeb"
echo "    Logs:    journalctl -u zeb -f    (look for the DASHBOARD LOGIN box)"
echo "    State:   $ZEB_HOME  (persists across restarts & updates)"
