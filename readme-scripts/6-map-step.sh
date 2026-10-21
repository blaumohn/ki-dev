# Von Hand, ohne Agenten, im Ordner `ki-dev` aus
# [Schritt 0](#0-einrichten-ohne-agenten-ausprobieren):
#
# ```bash
POLICIES="$PWD/docs/policies"  # Leitlinien von ki-dev, für die Übergaben
cd "$(mktemp -d)" && git init -q  # Wegwerf-Repo mit Beads-Projekt
bd init --quiet --prefix calc --stealth --non-interactive
mkdir docs && cp -r "$POLICIES" docs/
BEAD="$(bd create "Map the notes on add()" \
  --description "Source map of notes.md" \
  --acceptance "1. Every section of notes.md is mapped" \
  --metadata '{"handoff": {"source_refs": ["notes.md"]}}' \
  --silent)"  # Kartierungsauftrag mit Quelle
cat >verdict.json <<'EOF'  # Urteil des Reviews als Datei
{"event": "fix", "detail": "Section 2 is not mapped", "requirement_ref": "AC1"}
EOF
ki-dev flow show map            # Ablauf als Mermaid, wie oben
ki-dev -f map step "$BEAD" map  # Übergabe an den Kartierungsagenten
ki-dev -f map step "$BEAD" map.review map.review=verdict.json
# ```
#
# Der zweite `step` liest das Urteil `fix` aus `verdict.json` und gibt die
# Übergabe an die Korrektur aus, oben ohne die Zeile mit der Bead-ID.
