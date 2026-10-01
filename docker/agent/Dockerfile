# check=skip=InvalidDefaultArgInFrom
# Base images have no defaults on purpose: scripts/agent-container passes them
# from src/ki_dev/tool-versions.json, the single source for all versions.
ARG NODE_IMAGE
ARG PYTHON_IMAGE
FROM ${NODE_IMAGE} AS node
FROM ${PYTHON_IMAGE}
# Version ARGs are declared right before their step, ordered from rarely to
# frequently changed, so a version bump only rebuilds the layers after it.
ARG AGENT_UID=1000
ARG AGENT_GID=1000
ARG TARGETARCH
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo
RUN apt-get update && apt-get install -y --no-install-recommends curl ripgrep tini lsof \
    && rm -rf /var/lib/apt/lists/*
# The build host may be arm64; a hardcoded x86_64 rustup-init dies under qemu
# because the arm64 rootfs has no /lib64/ld-linux-x86-64.so.2.
ARG RUSTUP_VERSION
ARG RUST_VERSION
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
ARG DOLT_VERSION
RUN arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && curl -fsSL "https://github.com/dolthub/dolt/releases/download/v${DOLT_VERSION}/dolt-linux-${arch}.tar.gz" \
        -o /tmp/dolt.tar.gz \
    && tar -xzf /tmp/dolt.tar.gz -C /tmp \
    && install -m 0755 "/tmp/dolt-linux-${arch}/bin/dolt" /usr/local/bin/dolt \
    && rm -rf /tmp/dolt.tar.gz "/tmp/dolt-linux-${arch}"
# Go toolchain for beads development in /beads (compose.beads.yaml).
# Go matches the toolchain line in ../beads/go.mod; golangci-lint matches its CI.
# golangci-lint is built from source so it knows the go.mod language version.
ARG GO_VERSION
ARG GO_SHA256_AMD64
ARG GO_SHA256_ARM64
ARG GOLANGCI_LINT_VERSION
# Cache mounts keep Go modules and build cache across builds, outside the image.
RUN --mount=type=cache,target=/tmp/gopath/pkg/mod \
    --mount=type=cache,target=/tmp/gocache \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
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
        /usr/local/go/bin/go install "github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v${GOLANGCI_LINT_VERSION}"
ARG BD_VERSION
RUN --mount=type=cache,target=/tmp/gopath/pkg/mod \
    --mount=type=cache,target=/tmp/gocache \
    GOBIN=/usr/local/bin GOPATH=/tmp/gopath GOCACHE=/tmp/gocache GOTOOLCHAIN=local \
        CGO_ENABLED=1 GOFLAGS=-tags=gms_pure_go \
        /usr/local/go/bin/go install -trimpath -ldflags="-X main.Build=v${BD_VERSION}" \
        "github.com/steveyegge/beads/cmd/bd@v${BD_VERSION}"
RUN (getent group ${AGENT_GID} || groupadd -g ${AGENT_GID} agent) \
    && useradd -m -u ${AGENT_UID} -g ${AGENT_GID} -s /bin/bash agent
# Agent CLIs change most often, so they come last among the tool layers.
# Only the npm-managed files are handed to the agent user, not dolt/bd/golangci-lint.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
ARG CODEX_VERSION
ARG CLAUDE_VERSION
# Package caches live in the BuildKit builder, one id per package manager;
# they never enter the image and are not visible at container runtime.
RUN --mount=type=cache,id=npm,target=/root/.npm,sharing=locked \
    ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install -g @openai/codex@${CODEX_VERSION} @anthropic-ai/claude-code@${CLAUDE_VERSION} \
    && chown -R ${AGENT_UID}:${AGENT_GID} /usr/local/lib/node_modules \
    && chown ${AGENT_UID}:${AGENT_GID} /usr/local/bin \
    && chown -h ${AGENT_UID}:${AGENT_GID} /usr/local/bin/node /usr/local/bin/npm \
        /usr/local/bin/codex /usr/local/bin/claude
COPY project /opt/project
RUN --mount=type=cache,id=pip,target=/root/.cache/pip,sharing=locked \
    python -m venv /workspace/.venv \
    && /workspace/.venv/bin/pip install hatchling '/opt/project[test]' \
    && mkdir -p /home/agent/.claude /home/agent/.codex \
    && chown -R ${AGENT_UID}:${AGENT_GID} /workspace /home/agent
# Bind targets of the download caches (compose.yaml). Created here so a fresh
# home (--fresh) does not get root-owned parents from Docker.
RUN mkdir -p /home/agent/.npm /home/agent/.cache/pip /home/agent/.cache/go-build \
        /home/agent/go/pkg/mod /home/agent/go/bin \
    && chown -R ${AGENT_UID}:${AGENT_GID} /home/agent
# access/ and model/ are bind targets; generated/ stays container-only.
RUN mkdir -p /opt/agent-settings/access /opt/agent-settings/model \
        /opt/agent-settings/generated \
    && chown ${AGENT_UID}:${AGENT_GID} /opt/agent-settings/generated \
    && chmod 700 /opt/agent-settings/generated
# Empty, agent-owned slots: each repo dependency volume is also mounted on one
# slot, so Docker copies this owner into a new volume instead of leaving it to
# root. The slot count is SEED_SLOTS in src/ki_dev/agent_dev_volumes.py.
RUN for slot in 0 1 2 3 4 5 6 7; do mkdir -p "/opt/agent-volume-seed/$slot"; done \
    && chown -R ${AGENT_UID}:${AGENT_GID} /opt/agent-volume-seed
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
