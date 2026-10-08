# check=skip=InvalidDefaultArgInFrom
# Prüfimage für make readme-check: nur die README-Voraussetzungen, sonst nichts.
# Kein bd und keine Projektabhängigkeiten; die installiert der README-Ablauf.
# Python-Image, Go-Version und Prüfsummen kommen aus src/ki_dev/tool-versions.json
# (Makefile, Ziel readme-check).
ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git make gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
ARG TARGETARCH
ARG GO_VERSION
ARG GO_SHA256_AMD64
ARG GO_SHA256_ARM64
RUN arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && case "$arch" in \
        amd64) go_sha="${GO_SHA256_AMD64}" ;; \
        arm64) go_sha="${GO_SHA256_ARM64}" ;; \
        *) echo "unsupported architecture" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://dl.google.com/go/go${GO_VERSION}.linux-${arch}.tar.gz" -o /tmp/go.tar.gz \
    && echo "${go_sha}  /tmp/go.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/go.tar.gz -C /usr/local \
    && rm /tmp/go.tar.gz
ENV PATH=/usr/local/go/bin:$PATH
# Nutzer setzt compose.readme-check.yaml (UID des Host-Nutzers, liest /repo).
