# By hand, without agents, in the folder `ki-dev` from
# [setup](README.en.md#1-set-up):
#
# ```bash
POLICIES="$PWD/docs/policies"  # ki-dev's guidelines, for the handoffs
cd "$(mktemp -d)" && git init -q  # throwaway repo with a Beads project
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
  --silent)"  # mapping task with a source
cat >verdict.json <<'EOF'  # the review's verdict as a file
{"event": "fix", "detail": "Section 2 is not mapped",
 "requirement_ref": "AC1"}
EOF
ki-dev flow show map            # the flow as Mermaid
ki-dev -f map step "$BEAD" map  # handoff to the mapping agent
ki-dev -f map step "$BEAD" map.review map.review=verdict.json
# ```
#
# The second `step` reads the verdict `fix` from `verdict.json` and prints
# the handoff to the correction (German), above without the line with the
# bead ID.
