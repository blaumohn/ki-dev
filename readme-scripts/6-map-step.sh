# Für dieses separate Beispiel im ki-dev-Klon beginnen
# ([Einrichtung](README.md#1-einrichten)); ki-dev und bd sind im PATH:
#
# ```bash
POLICIES="$PWD/docs/policies"  # Leitlinien für Übergaben
cd "$(mktemp -d)" && git init -q  # Wegwerf-Repo mit Beads-Projekt
bd init --quiet --prefix calc --stealth --non-interactive
mkdir docs && cp -r "$POLICIES" docs/
cat >notes.md <<'EOF'
1. add(2, 3) should return 5.
2. add(-1, 1) should return 0.
EOF
BEAD="$(bd create "Map the notes on add()" \
  --description "Source map of notes.md" \
  --acceptance "1. Every section of notes.md is mapped" \
  --metadata '{"handoff": {"source_refs": ["notes.md"]}}' \
  --silent)"  # Kartierungsauftrag mit Quelle
cat >verdict.json <<'EOF'  # Urteil des Reviews als Datei
{"event": "fix", "detail": "Section 2 is not mapped",
 "requirement_ref": "AC1"}
EOF
ki-dev flow show map            # Ablauf als Mermaid
ki-dev -f map step "$BEAD" map  # Übergabe an den Kartierungsagenten
ki-dev -f map step "$BEAD" map.review map.review=verdict.json
# ```
#
# Der zweite `step` liest das Urteil `fix` aus `verdict.json` und gibt die
# Übergabe an die Korrektur aus, oben ohne die Zeile mit der Bead-ID.
