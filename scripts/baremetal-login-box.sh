#!/usr/bin/env bash
# Print the public dashboard URL and credentials in the systemd journal.
set -euo pipefail

env_file="${ZEB_ENV_FILE:-/etc/zeb/zeb.env}"
if [[ -f "$env_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$env_file"
  set +a
fi

port="${ZEB_DASHBOARD_PORT:-9119}"
user="${ZEB_DASHBOARD_BASIC_AUTH_USERNAME:-admin}"
pw="${ZEB_DASHBOARD_BASIC_AUTH_PASSWORD:-see /etc/zeb/zeb.env}"
hostnames="${ZEB_TUNNEL_HOSTNAMES:-public link pending}"

rule="======================================================================"
printf '\n\n+%s+\n' "$rule"
printf '| %-68s |\n' ''
printf '| %-68s |\n' 'ZEBOS DASHBOARD - PUBLIC LOGIN'
printf '| %-68s |\n' ''
printf '| %-68s |\n' '--------------------------------------------------------------------'
printf '| %-68s |\n' ''
printf '| %-68s |\n' '  OPEN FROM ANY DEVICE:'
while IFS= read -r host; do
  [[ -n "$host" ]] || continue
  printf '| %-68s |\n' "  https://${host}"
done < <(printf '%s' "$hostnames" | tr ',' '\n' | sed 's/^ *//;s/ *$//')
printf '| %-68s |\n' ''
printf '| %-68s |\n' "  USERNAME: ${user}"
printf '| %-68s |\n' "  PASSWORD: ${pw}"
printf '| %-68s |\n' ''
printf '| %-68s |\n' "  Local fallback: http://127.0.0.1:${port}"
printf '| %-68s |\n' '  Public hostname must be configured in Cloudflare for the tunnel.'
printf '| %-68s |\n' '--------------------------------------------------------------------'
printf '| %-68s |\n' ''
printf '+%s+\n\n' "$rule"
