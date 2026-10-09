# Login shells (bash -lc, as Codex runs commands) get PATH reset by
# /etc/profile. Restore the container PATH the entrypoint saved, so the local
# bd build and the venv stay first (ki-dev-ablauf-3w1).
if [ -n "${KI_DEV_AGENT_PATH-}" ]; then
    PATH=$KI_DEV_AGENT_PATH
    export PATH
elif [ -n "${KI_DEV_AGENT_CONTAINER-}" ]; then
    echo "ki-dev: KI_DEV_AGENT_PATH missing (shell not started via" \
        "agent-entrypoint); PATH from /etc/profile lacks local bd and venv" >&2
fi
