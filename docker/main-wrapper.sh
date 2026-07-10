#!/command/with-contenv sh
# shellcheck shell=sh
# /opt/zeb/docker/main-wrapper.sh — wraps the container's CMD with
# the same argument-routing logic the pre-s6 entrypoint.sh used. Runs
# as /init's "main program" (Docker CMD) so it inherits stdin/stdout/
# stderr from the container.
#
# Shebang note: /init scrubs env before invoking CMD, so a plain
# `#!/bin/sh` wrapper sees an empty environ and `ENV ZEB_HOME=/opt/data`
# from the Dockerfile never reaches `zeb`. with-contenv repopulates
# the env from /run/s6/container_environment before exec'ing, which is
# what s6-supervised services use too (see main-zeb/run).
#
# Routing:
#   no args                       → exec `zeb` (the default)
#   first arg is an executable    → exec it directly (sleep, bash, sh, …)
#   first arg is anything else    → exec `zeb <args>` (subcommand passthrough)
#
# Drop to zeb via s6-setuidgid, but skip it when already non-root.
set -e

drop() { [ "$(id -u)" = 0 ] && set -- s6-setuidgid zeb "$@"; exec "$@"; }

# --- Reject the unsupported `docker run --user <uid>:<gid>` start ---
# Mirror the guard in stage2-hook.sh (cont-init). This is the surface the
# user actually sees in `docker run` output: when the container is pinned to
# an arbitrary non-root, non-zeb UID, the bootstrap was skipped and the
# baked image dirs (owned by the zeb build UID) are unwritable, so fail
# fast here with actionable guidance rather than crashing on `cd`/EACCES
# further down. See stage2-hook.sh for the full rationale.
cur_uid="$(id -u)"
if [ "$cur_uid" != 0 ] && [ "$cur_uid" != "$(id -u zeb)" ]; then
    cat >&2 <<EOF
[zeb] ERROR: container started with --user $cur_uid (an arbitrary, non-zeb UID) — not supported.

To make container-written files match your HOST user, don't use --user.
Start as root (the default) and pass your host UID/GID instead:

    docker run -e ZEB_UID=\$(id -u) -e ZEB_GID=\$(id -g) ...

NAS users (Synology / unRAID / UGOS) can use the PUID/PGID aliases:

    docker run -e PUID=\$(id -u) -e PGID=\$(id -g) ...

The image remaps the zeb user to that UID/GID at boot and chowns the data
volume, so files land owned by your host user — the same outcome --user gave,
without breaking the s6 supervision tree.
EOF
    exit 1
fi

# HOME comes through with-contenv as /root (the /init context). Override
# to the zeb user's home before dropping privileges so libraries that
# resolve paths via $HOME (e.g. discord lockfile under XDG_STATE_HOME)
# don't try to write to /root.
export HOME=/opt/data

# Save the Docker -w (or default) working directory before init
# scripts cd to /opt/data, so the container starts in the
# directory the user requested.
_zeb_orig_cwd="${ZEB_ORIG_CWD:-$PWD}"

cd /opt/data
# shellcheck disable=SC1091
. /opt/zeb/.venv/bin/activate

# Restore the original working directory before handing off to
# the user's command so `zeb chat` starts in the Docker -w
# directory, not /opt/data.
cd "$_zeb_orig_cwd"

if [ $# -eq 0 ]; then
    # No command was given to `docker run`.
    #
    # Interactive (a TTY is attached — `docker run -it`): launch the
    # interactive agent, exactly as before.
    #
    # Detached (no TTY — `docker run -d`): the interactive agent would read
    # EOF from the closed stdin and exit immediately. Because this wrapper is
    # /init's "main program", its exit tears the whole container down (taking
    # the supervised services with it) — the "chat UI exits on startup /
    # container shuts down" symptom. So a detached container must run a
    # long-lived, TTY-free program instead. Default: the chat-only web UI
    # (serves :8000 and prints its API key to the logs) — the intended
    # headless ZebOS surface. Override with ZEB_DETACHED_CMD=gateway|idle.
    if [ -t 0 ]; then
        drop zeb
    fi
    case "${ZEB_DETACHED_CMD:-chatui}" in
        chatui)
            drop zeb chatui \
                --host "${ZEB_CHAT_HOST:-0.0.0.0}" \
                --port "${ZEB_CHAT_PORT:-8000}"
            ;;
        gateway)
            drop zeb gateway run
            ;;
        idle)
            # Keep the container alive doing nothing; the s6 supervision tree
            # (dashboard, and zeb-chat when ZEB_CHAT_UI=1) runs alongside.
            drop sleep infinity
            ;;
        *)
            echo "[zeb] Unknown ZEB_DETACHED_CMD='${ZEB_DETACHED_CMD:-}'; using chatui." >&2
            drop zeb chatui \
                --host "${ZEB_CHAT_HOST:-0.0.0.0}" \
                --port "${ZEB_CHAT_PORT:-8000}"
            ;;
    esac
fi

if command -v "$1" >/dev/null 2>&1; then
    # Bare executable — pass through directly.
    drop "$@"
fi

# Zeb subcommand pass-through.
drop zeb "$@"
