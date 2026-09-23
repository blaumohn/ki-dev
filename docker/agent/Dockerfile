FROM node:22-bookworm AS node
FROM python:3.12-bookworm
ARG AGENT_UID=1000
ARG AGENT_GID=1000
ARG BD_VERSION=1.2.2
ARG CODEX_VERSION=0.156.1
ARG CLAUDE_VERSION=2.1.272
ARG DOLT_VERSION=2.1.4
ARG RUST_VERSION=1.82.0
ARG TARGETARCH
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo
RUN apt-get update && apt-get install -y --no-install-recommends curl ripgrep tini \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install -g @beads/bd@${BD_VERSION} @openai/codex@${CODEX_VERSION} @anthropic-ai/claude-code@${CLAUDE_VERSION} \
    && chown -R ${AGENT_UID}:${AGENT_GID} /usr/local/lib/node_modules /usr/local/bin
# The build host may be arm64; a hardcoded x86_64 rustup-init dies under qemu
# because the arm64 rootfs has no /lib64/ld-linux-x86-64.so.2.
RUN case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
        amd64) rust_arch=x86_64-unknown-linux-gnu ;; \
        arm64) rust_arch=aarch64-unknown-linux-gnu ;; \
        *) echo "unsupported architecture" >&2; exit 1 ;; \
    esac \
    && curl -fsSLO "https://static.rust-lang.org/rustup/archive/1.27.1/${rust_arch}/rustup-init" \
    && curl -fsSLO "https://static.rust-lang.org/rustup/archive/1.27.1/${rust_arch}/rustup-init.sha256" \
    && sha256sum -c rustup-init.sha256 \
    && chmod +x rustup-init && ./rustup-init -y --profile minimal --default-toolchain "${RUST_VERSION}" \
    && rm rustup-init* \
    && chown -R ${AGENT_UID}:${AGENT_GID} "$RUSTUP_HOME" "$CARGO_HOME"
# dolt CLI for direct access to the bd database; 2.1.4 is the engine bd 1.2.2 embeds.
RUN arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && curl -fsSL "https://github.com/dolthub/dolt/releases/download/v${DOLT_VERSION}/dolt-linux-${arch}.tar.gz" \
        -o /tmp/dolt.tar.gz \
    && tar -xzf /tmp/dolt.tar.gz -C /tmp \
    && install -m 0755 "/tmp/dolt-linux-${arch}/bin/dolt" /usr/local/bin/dolt \
    && rm -rf /tmp/dolt.tar.gz "/tmp/dolt-linux-${arch}"
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
    PATH=/opt/agent-bin:/workspace/.venv/bin:/usr/local/cargo/bin:/usr/local/bin:/usr/bin:/bin \
    KI_DEV_AGENT_CONTAINER=1 \
    PYTHONPATH=/workspace/src
USER agent
WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/agent-entrypoint"]
CMD ["bash"]
