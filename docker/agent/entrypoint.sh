#!/bin/sh
set -eu
# /etc/profile resets PATH in login shells; profile-path.sh restores this one.
export KI_DEV_AGENT_PATH="$PATH"
# Seed Claude onboarding state once; keep atomic config writes inside the volume.
if [ ! -f "$HOME/.claude.json" ] && [ -s /run/claude-host.json ]; then
    cp /run/claude-host.json "$HOME/.claude.json"
    chmod 600 "$HOME/.claude.json"
fi
# dolt commit needs an identity. The agent-home volume masks anything the image
# put in ~/.dolt, so seed each key here when it is still unset; a value set by
# hand stays untouched and the volume keeps it for later runs.
if command -v dolt >/dev/null 2>&1; then
    [ -n "$(dolt config --global --get user.name 2>/dev/null || true)" ] \
        || dolt config --global --add user.name "${DOLT_USER_NAME:-agent}" >/dev/null
    [ -n "$(dolt config --global --get user.email 2>/dev/null || true)" ] \
        || dolt config --global --add user.email "${DOLT_USER_EMAIL:-agent@ki-dev-ablauf.invalid}" >/dev/null
fi
exec "$@"
