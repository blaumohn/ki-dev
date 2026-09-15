#!/bin/sh
set -eu
# Seed Claude onboarding state once; keep atomic config writes inside the volume.
if [ ! -f "$HOME/.claude.json" ] && [ -s /run/claude-host.json ]; then
    cp /run/claude-host.json "$HOME/.claude.json"
    chmod 600 "$HOME/.claude.json"
fi
exec "$@"
