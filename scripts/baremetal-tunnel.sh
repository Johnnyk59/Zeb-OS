#!/usr/bin/env bash
# Run the public Cloudflare tunnel for the bare-metal dashboard.
set -euo pipefail

env_file="${ZEB_ENV_FILE:-/etc/zeb/zeb.env}"
set -a
# shellcheck disable=SC1090
. "$env_file"
set +a

target="http://127.0.0.1:${ZEB_DASHBOARD_PORT:-9119}"
url_file="${ZEB_HOME:-/var/lib/zeb}/DASHBOARD_URL.txt"
mkdir -p "$(dirname "$url_file")"

rule="======================================================================"
print_box() {
  local url="$1"
  local user="${ZEB_DASHBOARD_BASIC_AUTH_USERNAME:-admin}"
  local pw="${ZEB_DASHBOARD_BASIC_AUTH_PASSWORD:-see /etc/zeb/zeb.env}"
  printf '\n\n+%s+\n' "$rule"
  printf '| %-68s |\n' ''
  printf '| %-68s |\n' 'ZEBOS DASHBOARD - PUBLIC LINK'
  printf '| %-68s |\n' ''
  printf '| %-68s |\n' '  OPEN FROM ANY DEVICE:'
  printf '| %-68s |\n' "  $url"
  printf '| %-68s |\n' ''
  printf '| %-68s |\n' "  USERNAME: ${user}"
  printf '| %-68s |\n' "  PASSWORD: ${pw}"
  printf '| %-68s |\n' ''
  printf '| %-68s |\n' '  The link may take a few seconds to become reachable.'
  printf '+%s+\n\n' "$rule"
}

if [[ -n "${ZEB_TUNNEL_TOKEN:-}" ]]; then
  : > "$url_file"
  while IFS= read -r hostname; do
    [[ -n "$hostname" ]] || continue
    url="https://${hostname}"
    printf '%s\n' "$url" >> "$url_file"
    print_box "$url"
  done < <(printf '%s' "${ZEB_TUNNEL_HOSTNAMES:-}" | tr ',' '\n' | sed 's/^ *//;s/ *$//')
  exec cloudflared tunnel --no-autoupdate run --token "$ZEB_TUNNEL_TOKEN"
fi

echo '[tunnel] ZEB_TUNNEL_TOKEN is not set; starting a temporary public URL.'
cloudflared tunnel --no-autoupdate --url "$target" 2>&1 | while IFS= read -r line; do
  printf '%s\n' "$line"
  if [[ "$line" == *trycloudflare.com* ]]; then
    url="$(printf '%s\n' "$line" | grep -oE 'https://[a-zA-Z0-9._-]+\.trycloudflare\.com' | head -n1 || true)"
    if [[ -n "$url" ]] && ! grep -Fqx "$url" "$url_file" 2>/dev/null; then
      printf '%s\n' "$url" > "$url_file"
      print_box "$url"
    fi
  fi
done
