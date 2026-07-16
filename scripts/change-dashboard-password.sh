#!/usr/bin/env bash
# Rotate the bare-metal dashboard password and invalidate every live session.
set -euo pipefail

ZEB_CODE_DIR="${ZEB_CODE_DIR:-/opt/zeb}"
ZEB_ENV_FILE="${ZEB_ENV_FILE:-/etc/zeb/zeb.env}"
ZEB_CREDENTIAL_FILE="${ZEB_CREDENTIAL_FILE:-/root/ZEB_DASHBOARD_LOGIN.txt}"
ZEB_USER="${ZEB_USER:-zeb}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo zeb-change-password" >&2
  exit 1
fi

if [[ ! -x "$ZEB_CODE_DIR/.venv/bin/python" || ! -f "$ZEB_ENV_FILE" ]]; then
  echo "Zeb bare-metal install not found under $ZEB_CODE_DIR." >&2
  exit 1
fi

read -r -s -p "New Zeb dashboard password: " password
printf '\n'
read -r -s -p "Confirm password: " confirmation
printf '\n'

if [[ -z "$password" ]]; then
  echo "Password cannot be empty." >&2
  exit 1
fi
if [[ "$password" != "$confirmation" ]]; then
  echo "Passwords do not match." >&2
  exit 1
fi

password_hash="$(
  printf '%s' "$password" |
    "$ZEB_CODE_DIR/.venv/bin/python" -c \
      'import sys; sys.path.insert(0, sys.argv[1]); from plugins.dashboard_auth.basic import hash_password; print(hash_password(sys.stdin.read()))' \
      "$ZEB_CODE_DIR"
)"
session_secret="$(openssl rand -hex 32)"

set_env_value() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$ZEB_ENV_FILE"; then
    sed -i "s#^${key}=.*#${key}=${value}#" "$ZEB_ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ZEB_ENV_FILE"
  fi
}

umask 077
set_env_value ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH "$password_hash"
set_env_value ZEB_DASHBOARD_BASIC_AUTH_SECRET "$session_secret"
sed -i '/^ZEB_DASHBOARD_BASIC_AUTH_PASSWORD=/d' "$ZEB_ENV_FILE"
chown root:"$ZEB_USER" "$ZEB_ENV_FILE"
chmod 640 "$ZEB_ENV_FILE"
rm -f "$ZEB_CREDENTIAL_FILE"

unset password confirmation password_hash session_secret
systemctl restart zeb.service

echo "Dashboard password changed. Every previous session has been invalidated."
echo "The old root recovery file was removed; store the new password in your password manager."
