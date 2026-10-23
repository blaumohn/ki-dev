#!/usr/bin/env bash
# Installiert die geprüften Agenten-CLIs (Codex, Claude Code) in den
# Versionen aus src/ki_dev/tool-versions.json nach .venv/bin. Globale
# Installationen bleiben unverändert; die Anmeldung (~/.codex,
# ~/.claude) teilen sich beide. ki-dev startet nur diese Versionen
# (adapter/executors/base.py).
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
bin="$repo/.venv/bin"
prefix="$repo/.venv/agents"

fail() { printf '%s\n' "$*" >&2; exit 1; }

[[ -x "$bin/python" ]] || fail "Zuerst make setup ausführen (.venv fehlt)."
command -v npm >/dev/null ||
  fail "npm fehlt: Node.js mit npm installieren (https://nodejs.org)."

# Aufruf aus dem Makefile mit CODEX_VERSION und CLAUDE_VERSION.
(( $# == 2 )) || fail "Aufruf: $0 CODEX_VERSION CLAUDE_VERSION"
codex="$1" claude="$2"

installed() {
  [[ -x "$bin/codex" && -x "$bin/claude" ]] &&
    [[ "$("$bin/codex" --version)" == "codex-cli $codex" ]] &&
    [[ "$("$bin/claude" --version)" == "$claude (Claude Code)" ]]
}

if ! installed; then
  npm install --prefix "$prefix" --save-exact --no-fund --no-audit \
    --loglevel=error \
    "@openai/codex@$codex" "@anthropic-ai/claude-code@$claude"
  ln -sf "../agents/node_modules/.bin/codex" "$bin/codex"
  ln -sf "../agents/node_modules/.bin/claude" "$bin/claude"
  installed || fail "Installierte Agenten-CLIs melden andere Versionen."
fi
printf 'codex %s und claude %s in %s\n' "$codex" "$claude" "$bin"
