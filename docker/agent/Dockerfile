FROM rust:1-bookworm AS loope-build
WORKDIR /build
COPY loope/Cargo.toml loope/Cargo.lock ./
COPY loope/src ./src
RUN cargo build --locked --release

FROM node:22-bookworm AS node
FROM python:3.12-bookworm
ARG AGENT_UID=1000
ARG AGENT_GID=1000
ARG BD_VERSION=1.2.2
ARG CODEX_VERSION=0.154.0
ARG CLAUDE_VERSION=2.1.272
RUN apt-get update && apt-get install -y --no-install-recommends ripgrep tini \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install -g @beads/bd@${BD_VERSION} @openai/codex@${CODEX_VERSION} @anthropic-ai/claude-code@${CLAUDE_VERSION}
COPY --from=loope-build /build/target/release/loope /usr/local/bin/loope
RUN (getent group ${AGENT_GID} || groupadd -g ${AGENT_GID} agent) \
    && useradd -m -u ${AGENT_UID} -g ${AGENT_GID} -s /bin/bash agent
COPY project /opt/project
RUN python -m venv /workspace/.venv \
    && /workspace/.venv/bin/pip install --no-cache-dir hatchling '/opt/project[test]' \
    && mkdir -p /home/agent/.claude /home/agent/.codex \
    && chown -R ${AGENT_UID}:${AGENT_GID} /workspace /home/agent
# access/ and model/ are bind targets; generated/ stays container-only.
RUN mkdir -p /opt/agent-settings/access /opt/agent-settings/model \
        /opt/agent-settings/generated \
    && chown ${AGENT_UID}:${AGENT_GID} /opt/agent-settings/generated \
    && chmod 700 /opt/agent-settings/generated
COPY docker/agent/agent_cli.py /opt/agent-bin/agent_cli.py
COPY docker/agent/entrypoint.sh /usr/local/bin/agent-entrypoint
RUN chmod +x /usr/local/bin/agent-entrypoint /opt/agent-bin/agent_cli.py \
    && ln -s agent_cli.py /opt/agent-bin/codex \
    && ln -s agent_cli.py /opt/agent-bin/claude
ENV HOME=/home/agent \
    VIRTUAL_ENV=/workspace/.venv \
    PATH=/opt/agent-bin:/workspace/.venv/bin:/usr/local/bin:/usr/bin:/bin \
    KI_DEV_AGENT_CONTAINER=1 \
    PYTHONPATH=/workspace/src
USER agent
WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/agent-entrypoint"]
CMD ["bash"]
