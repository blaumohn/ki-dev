# Im ki-dev-Klon nach [Ausprobieren](#ausprobieren-ohne-agenten): `bd`
# liegt im Projekt-venv. Ein Wegwerf-Repo `calc` mit dem Bug, daneben der
# Arbeits-Worktree `calc-work` der Agenten mit eigenem Beads-Projekt und
# dem Profil aus Schritt 2. `.ki-dev/` (Profil, Läufe) und die
# Beads-Sperrdatei bleiben außerhalb von git: ki-dev verlangt saubere
# Worktrees.
#
# ```bash
export PATH="$PWD/.venv/bin:$PATH"
PROFILE="$PWD/docs/beispiele/default.toml"
cd "$(mktemp -d)" && git init -q -b main calc && cd calc
git config user.name calc && git config user.email calc@example.invalid
printf 'def add(a, b):\n    return a - b\n' >add.py
printf 'from add import add\n\nassert add(2, 3) == 5\n' >test_add.py
printf '.ki-dev/\n.beads.gate.lock\n' >>.git/info/exclude
git add . && git commit -q -m "add()"
git worktree add -q -b work ../calc-work && cd ../calc-work
mkdir -p .ki-dev/profiles && cp "$PROFILE" .ki-dev/profiles/default.toml
bd init --quiet --prefix calc --stealth --non-interactive
BEAD="$(bd create "add() does not add" \
  --description "add(2, 3) returns -1" \
  --design "fix add.py; do not change test_add.py" \
  --acceptance "add(2, 3) == 5 and add(-1, 1) == 0" \
  --silent)"
echo "$BEAD"
# ```
#
# `$BEAD` ist die ID des Auftrags, etwa `calc-7k2`; Schritt 4 nutzt sie im
# selben Terminal, in `calc-work`.
