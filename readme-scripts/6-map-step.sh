# Ohne Agenten von Hand durchspielen, im ki-dev-Klon begonnen: ein
# Wegwerf-Repo mit Beads-Projekt, darin die Leitlinien von ki-dev (die
# Übergaben von `map` tragen die Leitlinien des Ziel-Repos aus
# `docs/policies/`), ein Kartierungsauftrag mit Quelle (`source_refs`) und
# das Urteil des Reviews als Datei.
#
# ```bash
export PATH="$PWD/.venv/bin:$PATH"
POLICIES="$PWD/docs/policies"
cd "$(mktemp -d)" && git init -q
bd init --quiet --prefix calc --stealth --non-interactive
mkdir docs && cp -r "$POLICIES" docs/
BEAD="$(bd create "Map the notes on add()" \
  --description "Source map of notes.md" \
  --acceptance "1. Every section of notes.md is mapped" \
  --metadata '{"handoff": {"source_refs": ["notes.md"]}}' \
  --silent)"
cat >verdict.json <<'EOF'
{"event": "fix", "detail": "Section 2 is not mapped", "requirement_ref": "AC1"}
EOF
ki-dev flow show map
ki-dev -f map step "$BEAD" map
ki-dev -f map step "$BEAD" map.review map.review=verdict.json
# ```
#
# `flow show` gibt den Ablauf als Mermaid aus (oben), der erste `step` die
# Übergabe an den Kartierungsagenten. Der zweite nimmt das Urteil `fix`
# zurück und gibt die Übergabe an die Korrektur aus, hier ohne die Zeile
# mit der Bead-ID.
