# Play it through by hand, without agents, in the folder `ki-dev` from
# [step 0](#0-set-up-try-it-without-agents): a throwaway repo with a Beads
# project, a mapping task with a source (`source_refs`) and the review's
# verdict as a file.
#
# ```bash
POLICIES="$PWD/docs/policies"  # ki-dev's guidelines, for the handoffs
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
# `flow show` prints the flow as Mermaid (above), the first `step` the
# handoff to the mapping agent. The second returns the verdict `fix` and
# prints the handoff to the correction (German), here without the line
# with the bead ID.
