# Im ki-dev-Klon nach [Ausprobieren](#ausprobieren-ohne-agenten): `bd`
# liegt im Projekt-venv, der Auftrag entsteht in einem Wegwerf-Repo mit
# eigenem Beads-Projekt.
#
# ```bash
export PATH="$PWD/.venv/bin:$PATH"
cd "$(mktemp -d)" && git init -q
bd init --quiet --prefix calc --stealth --non-interactive
BEAD="$(bd create "add() does not add" \
  --description "add(2, 3) returns -1" \
  --design "fix add.py; do not change test_add.py" \
  --acceptance "add(2, 3) == 5 and add(-1, 1) == 0" \
  --silent)"
echo "$BEAD"
# ```
#
# `$BEAD` ist die ID des Auftrags, etwa `calc-7k2`; Schritt 4 nutzt sie.
