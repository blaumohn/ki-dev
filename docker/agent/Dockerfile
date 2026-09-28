ARG NODE_IMAGE
ARG PYTHON_IMAGE
FROM ${NODE_IMAGE} AS node
FROM ${PYTHON_IMAGE}
ARG AGENT_UID=1000
ARG AGENT_GID=1000
ARG BD_VERSION
ARG CODEX_VERSION
ARG CLAUDE_VERSION
ARG DOLT_VERSION
ARG RUST_VERSION
ARG RUSTUP_VERSION
# Go matches the toolchain line in ../beads/go.mod; golangci-lint matches its CI.
ARG GO_VERSION
ARG GO_SHA256_AMD64
ARG GO_SHA256_ARM64
ARG GOLANGCI_LINT_VERSION
ARG TARGETARCH
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo
RUN apt-get update && apt-get install -y --no-install-recommends curl ripgrep tini \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install -g @openai/codex@${CODEX_VERSION} @anthropic-ai/claude-code@${CLAUDE_VERSION} \
    && chown -R ${AGENT_UID}:${AGENT_GID} /usr/local/lib/node_modules /usr/local/bin
# The build host may be arm64; a hardcoded x86_64 rustup-init dies under qemu
# because the arm64 rootfs has no /lib64/ld-linux-x86-64.so.2.
RUN case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
        amd64) rust_arch=x86_64-unknown-linux-gnu ;; \
        arm64) rust_arch=aarch64-unknown-linux-gnu ;; \
        *) echo "unsupported architecture" >&2; exit 1 ;; \
    esac \
    && curl -fsSLO "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/${rust_arch}/rustup-init" \
    && curl -fsSLO "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/${rust_arch}/rustup-init.sha256" \
    && sha256sum -c rustup-init.sha256 \
    && chmod +x rustup-init && ./rustup-init -y --profile minimal --default-toolchain "${RUST_VERSION}" \
    && rm rustup-init* \
    && chown -R ${AGENT_UID}:${AGENT_GID} "$RUSTUP_HOME" "$CARGO_HOME"
# Keep the Dolt CLI version aligned with the engine embedded in bd.
RUN arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && curl -fsSL "https://github.com/dolthub/dolt/releases/download/v${DOLT_VERSION}/dolt-linux-${arch}.tar.gz" \
        -o /tmp/dolt.tar.gz \
    && tar -xzf /tmp/dolt.tar.gz -C /tmp \
    && install -m 0755 "/tmp/dolt-linux-${arch}/bin/dolt" /usr/local/bin/dolt \
    && rm -rf /tmp/dolt.tar.gz "/tmp/dolt-linux-${arch}"
# Go toolchain for beads development in /beads (compose.beads.yaml).
# golangci-lint is built from source so it knows the go.mod language version.
RUN arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && case "$arch" in \
        amd64) go_sha="${GO_SHA256_AMD64}" ;; \
        arm64) go_sha="${GO_SHA256_ARM64}" ;; \
        *) echo "unsupported architecture" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://dl.google.com/go/go${GO_VERSION}.linux-${arch}.tar.gz" -o /tmp/go.tar.gz \
    && echo "${go_sha}  /tmp/go.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/go.tar.gz -C /usr/local \
    && rm /tmp/go.tar.gz \
    && GOBIN=/usr/local/bin GOPATH=/tmp/gopath GOCACHE=/tmp/gocache GOTOOLCHAIN=local \
        /usr/local/go/bin/go install "github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v${GOLANGCI_LINT_VERSION}" \
    && GOBIN=/usr/local/bin GOPATH=/tmp/gopath GOCACHE=/tmp/gocache GOTOOLCHAIN=local \
        CGO_ENABLED=1 GOFLAGS=-tags=gms_pure_go \
        /usr/local/go/bin/go install -trimpath -ldflags="-X main.Build=v${BD_VERSION}" \
        "github.com/steveyegge/beads/cmd/bd@v${BD_VERSION}" \
    && rm -rf /tmp/gopath /tmp/gocache
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
    PATH=/opt/agent-bin:/workspace/.venv/bin:/usr/local/cargo/bin:/usr/local/go/bin:/home/agent/go/bin:/usr/local/bin:/usr/bin:/bin \
    GOTOOLCHAIN=local \
    KI_DEV_AGENT_CONTAINER=1 \
    PYTHONPATH=/workspace/src
USER agent
WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/agent-entrypoint"]
CMD ["bash"]
