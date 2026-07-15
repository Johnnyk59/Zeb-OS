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
ZEB_USER="${ZEB_USER:-zeb}"

echo "==> Zeb bare-metal install"
echo "    code:  $ZEB_CODE_DIR"
echo "    state: $ZEB_HOME  (persistent)"
echo "    env:   $ZEB_ENV_FILE"
echo "    user:  $ZEB_USER"

if [ "$(id -u)" -ne 0 ]; then
  echo "!! Please run as root (sudo)." >&2
  exit 1
fi

# 1. System deps -----------------------------------------------------------
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git curl build-essential nodejs npm openssl

# cloudflared is not included in the default Ubuntu repositories on every
# supported VPS image. Install the official package when it is absent.
if ! command -v cloudflared >/dev/null 2>&1; then
  arch="$(dpkg --print-architecture)"
  case "$arch" in
    amd64) cloudflared_deb="cloudflared-linux-amd64.deb" ;;
    arm64) cloudflared_deb="cloudflared-linux-arm64.deb" ;;
    *) echo "Unsupported CPU architecture for cloudflared: $arch" >&2; exit 1 ;;
  esac
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/$cloudflared_deb" -o /tmp/cloudflared.deb
  dpkg -i /tmp/cloudflared.deb
  rm -f /tmp/cloudflared.deb
fi

# Keep the autonomous service out of root while giving it ownership of its
# checkout and persistent state. It can modify Zeb, but not the whole OS.
if ! id -u "$ZEB_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$ZEB_HOME" --create-home --shell /usr/sbin/nologin "$ZEB_USER"
fi

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

# Build the selected React dashboard once. The systemd service uses
# --skip-build so a restart never mutates the checkout or needs npm access.
if [ -f "$ZEB_CODE_DIR/package-lock.json" ]; then
  npm --prefix "$ZEB_CODE_DIR" install --workspace web --ignore-scripts
  npm --prefix "$ZEB_CODE_DIR" run build --workspace web
fi

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
# ZEB_TUNNEL_TOKEN=
# ZEB_TUNNEL_ID=
ZEB_TUNNEL_HOSTNAMES=smartestmotherfuckerever.zeb.autos
# --- Instagram (Meta Business app; pipeline stays inert until all set) ---
# IG_APP_ID=
# IG_APP_SECRET=
# IG_ACCESS_TOKEN=
# IG_BUSINESS_ACCOUNT_ID=
# IG_VERIFY_TOKEN=use-a-long-random-string
# IG_GRAPH_VERSION=v20.0
EOF
  chmod 600 "$ZEB_ENV_FILE"
  echo "==> Wrote template $ZEB_ENV_FILE (chmod 600) — edit it to add keys."
fi

# Generate credentials once when the operator has not supplied them. They are
# persisted in the root-only env file and printed on every service start.
umask 077
set_env_default() {
  key="$1"
  value="$2"
  if grep -q "^${key}=" "$ZEB_ENV_FILE"; then
    current="$(sed -n "s/^${key}=//p" "$ZEB_ENV_FILE" | head -n1)"
    if [ -z "$current" ]; then
      sed -i "s#^${key}=.*#${key}=${value}#" "$ZEB_ENV_FILE"
    fi
  else
    printf '%s=%s\n' "$key" "$value" >> "$ZEB_ENV_FILE"
  fi
}
set_env_default ZEB_DASHBOARD_BASIC_AUTH_USERNAME admin
set_env_default ZEB_DASHBOARD_BASIC_AUTH_PASSWORD "$(openssl rand -hex 12)"
set_env_default ZEB_DASHBOARD_BASIC_AUTH_SECRET "$(openssl rand -hex 32)"

chown -R "$ZEB_USER:$ZEB_USER" "$ZEB_CODE_DIR" "$ZEB_HOME"
chmod 700 "$ZEB_HOME"

# 5. systemd unit ----------------------------------------------------------
install -m 644 "$ZEB_CODE_DIR/packaging/systemd/zeb.service" /etc/systemd/system/zeb.service
install -m 644 "$ZEB_CODE_DIR/packaging/systemd/zeb-tunnel.service" /etc/systemd/system/zeb-tunnel.service
install -m 755 "$ZEB_CODE_DIR/scripts/baremetal-login-box.sh" /usr/local/libexec/zeb-login-box
install -m 755 "$ZEB_CODE_DIR/scripts/baremetal-tunnel.sh" /usr/local/libexec/zeb-tunnel
# Point the unit at the chosen paths.
sed -i "s#WorkingDirectory=/opt/zeb#WorkingDirectory=$ZEB_CODE_DIR#" /etc/systemd/system/zeb.service
sed -i "s#ZEB_HOME=/var/lib/zeb#ZEB_HOME=$ZEB_HOME#" /etc/systemd/system/zeb.service
sed -i "s#ExecStart=/opt/zeb/.venv/bin/python#ExecStart=$ZEB_CODE_DIR/.venv/bin/python#" /etc/systemd/system/zeb.service
sed -i "s#^User=zeb#User=$ZEB_USER#" /etc/systemd/system/zeb.service
sed -i "s#^Group=zeb#Group=$ZEB_USER#" /etc/systemd/system/zeb.service
sed -i "s#^EnvironmentFile=-\?/etc/zeb/zeb.env#EnvironmentFile=$ZEB_ENV_FILE#" /etc/systemd/system/zeb.service
sed -i "s#^EnvironmentFile=/etc/zeb/zeb.env#EnvironmentFile=$ZEB_ENV_FILE#" /etc/systemd/system/zeb-tunnel.service
sed -i "s#^Environment=ZEB_ENV_FILE=/etc/zeb/zeb.env#Environment=ZEB_ENV_FILE=$ZEB_ENV_FILE#" /etc/systemd/system/zeb.service
sed -i "s#^Environment=ZEB_ENV_FILE=/etc/zeb/zeb.env#Environment=ZEB_ENV_FILE=$ZEB_ENV_FILE#" /etc/systemd/system/zeb-tunnel.service
sed -i "s#^User=zeb#User=$ZEB_USER#" /etc/systemd/system/zeb-tunnel.service
sed -i "s#^Group=zeb#Group=$ZEB_USER#" /etc/systemd/system/zeb-tunnel.service

systemctl daemon-reload
systemctl enable zeb.service
systemctl enable zeb-tunnel.service
systemctl restart zeb.service
systemctl restart zeb-tunnel.service

echo ""
echo "==> Dashboard credentials and link: journalctl -u zeb -n 80 --no-pager"
echo "==> Public tunnel logs and link: journalctl -u zeb-tunnel -n 120 --no-pager"

echo ""
echo "==> Zeb is installed as a systemd service (auto-start on boot, auto-restart on crash)."
echo "    Status:  systemctl status zeb"
echo "    Logs:    journalctl -u zeb -f    (look for the DASHBOARD LOGIN box)"
echo "    State:   $ZEB_HOME  (persists across restarts & updates)"
