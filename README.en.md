[Deutsch](README.md) · English

# ki-dev

**A Python command-line program for workflows with AI agents.**
You define in TOML who works, who reviews and when a human decides.
ki-dev runs these steps in a Git repository.

## Contents

- [Minimal example: a code change with review](#minimal-example)
- [Try it: run the example with real agents](#try-it)
- [Status: what works, what is missing](#status)
- [Extend it: custom flows and next work](#extend-it)
- [Contribute: help and check changes](#contribute)
- [License](#license)

## Minimal example

**The flow:** `implement` is a bundled flow for code changes. It connects
implementation, tests, review and correction. A task in
[Beads](https://github.com/steveyegge/beads) describes the particular change.

**The example task:** `add(a, b)` computes `a - b`; it should compute `a + b`.

**The assignment:** `worker` and `review` are this flow's roles.
The profile, a TOML file ([step 3](#3-save-the-profile)), fills them
with Codex and Claude Code; ki-dev creates a separate session for each
role.

A run goes like this:

1. The implementer (`worker`) works on the task.
2. ki-dev runs the tests from the profile.
3. The review receives the change and the test result and answers.
4. The answer determines which configured transition follows:

| Review answer | ki-dev's response |
|---|---|
| `fix` | Send findings to the implementer for correction; halt for a human when correction rounds are exhausted. |
| `PASS` | Prepare the final commit and fast-forward it into the target branch. |
| `decision` | Halt for a human decision. |

Transitions are defined in [TOML](docs/vertiefung.en.md#flow-rules);
Python executes them. The profile assigns roles and sets limits;
the task supplies the work and acceptance criteria.

> **Prototype:** So far, this one task has been exercised with real agents
> ([result](#5-check-the-result)). Failing tests do not yet prevent
> integration automatically. [Status and limits](#status)

## Try it

The five steps run one after another in the same terminal. You need:

- **ki-dev:** Python ≥ 3.12 with `venv` and `pip`, Git ≥ 2.32.
- **Tasks:** Beads (`bd`). `make setup` builds the
  [pinned version](src/ki_dev/tool-versions.json) with Bash, Make, Go and a
  C compiler; Go and C are needed only for this build.
- **Agents:** [Codex CLI](https://github.com/openai/codex) and
  [Claude Code](https://code.claude.com/docs), both signed in. The run
  calls real models and uses tokens; the profile picks the cheapest model
  of each CLI with effort `low`. Without model access, `make demo` shows
  the same flow with scripted answers
  ([demo](docs/vertiefung.en.md#demo-without-model-access)).

### 1. Set up

<!-- readme-script: readme-scripts/en/1-setup.sh -->
The first run needs network access and takes a few minutes to
build Beads.

```bash
git clone https://github.com/blaumohn/ki-dev.git ki-dev
cd ki-dev
make setup                          # venv with ki-dev and bd
export PATH="$PWD/.venv/bin:$PATH"  # ki-dev and bd for the steps below
```

> ✅ Run in an empty container · [test](tests/readme/test_1_setup.sh)
<!-- /readme-script -->

### 2. Create the task

<!-- readme-script: readme-scripts/en/3-auftrag.sh -->
In the same terminal as the setup. The commands create a throwaway
repo with the bug: `calc` holds the target branch `main`, the agents
work in the worktree `calc-work`. `bd create` stores problem, design
and acceptance criteria as the task; `implement` reads these fields.

```bash
cd "$(mktemp -d)"
git init -q -b main calc && cd calc  # throwaway repo
git config user.name calc  # identity for this throwaway repo only
git config user.email calc@example.invalid
cat >add.py <<'EOF'
def add(a, b):
    return a - b
EOF
cat >test_add.py <<'EOF'
from add import add

assert add(2, 3) == 5
EOF
printf '%s\n' .ki-dev/ .beads.gate.lock __pycache__/ \
  >>.git/info/exclude  # run data, Python cache
git add . && git commit -q -m "add()"
git worktree add -q -b work ../calc-work  # the agents' worktree
cd ../calc-work
bd init --quiet --prefix calc --stealth --non-interactive
BEAD="$(bd create "add() does not add" \
  --description "add(2, 3) returns -1" \
  --design "fix add.py; do not change test_add.py" \
  --acceptance "add(2, 3) == 5 and add(-1, 1) == 0" \
  --silent)"
echo "$BEAD"
```

> ✅ Run in an empty container · [test](tests/readme/test_3_auftrag.sh)

`$BEAD` is the task ID, e.g. `calc-7k2`.
<!-- /readme-script -->

### 3. Save the profile

<!-- readme-script: readme-scripts/en/4-rollen.sh -->
The profile fills the roles: Codex implements, Claude Code reviews.
Both use the cheapest model of their CLI with effort `low`; ki-dev
creates a separate session for each role on its first call.
Continue in `calc-work`:

```bash
mkdir -p .ki-dev/profiles       # profiles in the starting directory
cat >.ki-dev/profiles/default.toml <<'EOF'
workdir = "."                   # agents' worktree, ki-dev starts here
access_profile = "write"        # the worker may write here

[worker]                        # implements
executor = "codex"
model = "gpt-6-luna"
effort = "low"

[review]                        # reviews, read-only
executor = "claude"
model = "haiku"
effort = "low"

[[tests]]                       # runs each round, result to review
name = "test_add"
argv = ["python3", "test_add.py"]

[limits]
changes_rounds = 3              # at most three correction rounds

[finalization]                  # where an accepted result goes
target_workdir = "../calc"      # target repo with branch main
target_ref = "refs/heads/main"
commit_message = "Fix add()"
EOF
```

> ✅ Run in an empty container · [test](tests/readme/test_4_rollen.sh)

- `executor` can be swapped per role; available are `codex`,
  `claude`, `mock` and `manual`
  ([executors](docs/ausfuehrer.de.md#executoren), German).
- Per-call limits (time, cost, quota) have
  [defaults](docs/ausfuehrer.de.md#verbrauchsschutz) (German).
<!-- /readme-script -->

### 4. Start

<!-- readme-script: readme-scripts/en/5-starten.sh -->
Continue in `calc-work`. ki-dev now calls the agents; depending on
the model this takes seconds to minutes. With `-v`, ki-dev shows state
changes and agent output live.

```bash
ki-dev -f implement "$BEAD" --run-id add-fix  # profile default
```

> ⏳ Not checked: the first agent call needs logged-in agent CLIs; run up to there · [test](tests/readme/test_5_starten.sh)

The end state follows as JSON, after success with
`"status": "passed"`. If the run halts, `detail` names the reason;
`ki-dev -f implement resume add-fix` continues afterwards
([halting and resuming](docs/ausfuehrer.de.md), German).
<!-- /readme-script -->

### 5. Check the result

<!-- readme-script: readme-scripts/en/9-ergebnis.sh -->
Continue in `calc-work`. `history` summarizes the run from its saved
intermediate results; the target repo `calc` holds the final commit.

```bash
ki-dev -f implement history add-fix  # rounds, tests, review, finish
git -C ../calc log -1 --format=%s    # final commit on main
git -C ../calc show main:add.py      # corrected file on main
```

> ✅ Run with real agents · [test](tests/readme/test_9_ergebnis.sh)

```text
Lauf add-fix: passed nach 1 Runde
  Runde 1  Umsetzer  geändert: add.py
  Runde 1  Tests     test_add bestanden
  Runde 1  Review    PASS: AC1 per Lesen geprueft: add.py enthaelt jetzt `ret…
  Abschluss          Fast-forward integriert
Fix add()
def add(a, b):
    return a + b
```

ki-dev prints its messages in German: `Runde` is round, `Umsetzer`
the implementer, `geändert` changed, `bestanden` passed. The `Tests`
line is the result of `test_add.py`, which ki-dev runs before the
review. If the review answers `fix`, another round follows with the
finding.
<!-- /readme-script -->

[↑ Contents](#contents)

## Status

- **With real agents:** The minimal example ran with Codex (`gpt-6-luna`)
  and Claude Code (`haiku`) in one round up to the commit on `main`
  ([result](#5-check-the-result),
  [event log](docs/beispiele/echtlauf/9-ergebnis.events.jsonl)).
  A correction round with real agents has not been observed yet.
- **With scripted answers:** The flow completes correction, review and
  integration into `main` ([demo test](tests/readme/test_8_demo.sh)).
- **Integration gate:** `PASS` can trigger integration despite failing tests.
  The planned test gate will prevent this
  ([requirement test](tests/test_review_gate_cli.py)).
- **Usage:** `implement` checks limits before every call; a new session is
  measured from its first answer. Measurement and enforced stopping during
  a call are missing, as is context measurement for Codex
  ([usage protection](docs/ausfuehrer.de.md#verbrauchsschutz), German).
- **Planning:** `map`, `graph` and `materialize` are advanced manually with
  `step`. A human also chains flows and selects tasks
  ([planning example](docs/vertiefung.en.md#planning)).

[↑ Contents](#contents)

## Extend it

**Custom flows** define roles, steps and transitions in TOML, with domain
operations added in Python. ki-dev loads a custom package directory
through `KI_DEV_FLOW_PATH`.
[Create a package](docs/ablaufpakete.de.md#paket-außerhalb-des-gerüsts) (German)

**Shared mechanics:** The runner starts operations, saves results and
resumes runs after a halt. Executors connect it to agents or humans.
[Architecture with sources](docs/vertiefung.en.md#architecture)

**Next work:** A test gate, a shared runner for implementation and planning,
and enforced usage protection.
[Architecture work](docs/ausfuehrer-luecken.de.md) · [Direction](docs/zielbild.de.md)

Why control flow lives in code, and the research behind this choice:
[Design decision](docs/vertiefung.en.md#design-decision).

[↑ Contents](#contents)

## Contribute

Two starting points with a verifiable outcome:

- **Add a test gate:** Prevent integration when tests fail;
  use the [requirement test](tests/test_review_gate_cli.py) without `xfail`
  as the acceptance check.
- **Enforce round limits for planning:** In `map`, `graph` and `materialize`,
  make another `fix` halt for a human once the round limit is exhausted.

<!-- readme-script: readme-scripts/en/7-entwickeln.sh -->
In the folder `ki-dev` from the [setup](#1-set-up):

```bash
make test          # pytest and ruff
make spec-test     # requirement tests, red results are allowed
make readme-check  # Docker check; updates README and deep dive
```

> ⏳ Not checked: developer commands; make readme-check is this run itself · [test](tests/readme/test_7_entwickeln.sh)
<!-- /readme-script -->

**Edit documentation:** Commands and explanations live in
[`readme-scripts/`](readme-scripts), translations in
[`readme-scripts/en/`](readme-scripts/en).
`.venv/bin/python scripts/render-readme.py` updates the README and the
deep dive. `make readme-check` needs Docker with Compose and writes status
and output from that run directly below each corresponding command block.
`make readme-live` runs the example with real agents (uses tokens) and
sets status and output of step 5.
[Guidelines](docs/readme-leitlinie.de.md) (German)

For your own development runs:
[install ki-dev separately from the source tree being edited](docs/vertiefung.en.md#runtime-installation).

Questions, ideas, collaboration: open an issue or contact
[@blaumohn](https://github.com/blaumohn).

[↑ Contents](#contents)

## License

[MIT](LICENSE)
