<p align="right"><a href="README.md">Deutsch</a> | English</p>

# ki-dev

**Agent work as a declarative workflow: states and transitions live in
TOML, an executor drives them, adapters talk to Claude, Codex or a human.**

The AI writes code and judges results. What happens next (another
correction round, a halt for a decision, a verified integration) is neither
in the prompt nor in Python code; it is in the workflow.

The three components divide responsibility:

| Component | Defines | Contents / role |
| --- | --- | --- |
| `flow/implement.toml`, `flow/planning.toml` | **What** may happen | Data: states, transitions, guards and actions |
| `runner/` | **How** the workflow executes | Formal answer → event → select edge (python-statemachine) → next input; one record per step, a halt ends the process |
| `adapter/` | **Who** handles the input | Connects Claude, Codex, a human (`manual`) or a simulation (`mock`) |

The executor (`runner/`) reads the workflow file and calls the appropriate
adapter. With `ki-dev -f implement BEAD`, this happens automatically.

`ki-dev -f FLOW step` is the same idea by hand: exactly one turn of a
workflow, stateless, carried on by a human as messenger.

## A loop is an edge, not a component

Build, review, fix, review again is not a "loop" layer but a back edge in
the workflow. Guards decide when it ends; every back edge consumes a counter.
From [`src/ki_dev/flow/implement.toml`](src/ki_dev/flow/implement.toml):

```toml
# controller_step --fix [cond] / on--> target   (UML edge)

# correction budget spent → human
[[statechart.states.active.states.controller_step.transitions]]
event = "fix"
cond = "checked_result"
unless = "changes_rounds_left"
target = "paused_interactive"
on = [{ raise = { event = "escalation.changes_rounds_exhausted" } }]

# otherwise: next round, counter +1
[[statechart.states.active.states.controller_step.transitions]]
event = "fix"
cond = "checked_result"
target = "worker_step_prepare"
on = ["begin_correction", "drop_result"]
```

`[statechart]` is the native format of
[python-statemachine](https://python-statemachine.readthedocs.io/)
(SCXML semantics). Transitions are tried in file order, the first match
wins, no match means the event is not allowed there. The library selects
edges and handles history (where a pause resumes) and `raise`; the
executor only knows guard and action names, not the topology.

## Try it in a minute

<!-- readme-script: readme-scripts/en/1-setup.sh -->
Offline, with mock adapters. Prerequisites: Python ≥ 3.12 (with `venv`),
git ≥ 2.32, make, Go and a C compiler. `make setup` creates the venv,
ki-dev and [Beads](https://github.com/steveyegge/beads) `bd` (version from
`src/ki_dev/tool-versions.json`) inside the project and changes nothing
outside it. `$REPLACE_WITH_REPOSITORY_URL` stands for the clone address of
this repository; it is fixed once the repository is published.

```bash
git clone "$REPLACE_WITH_REPOSITORY_URL" ki-dev
cd ki-dev
make setup
make demo
```

```text
{
  "run_id": "demo",
  "status": "passed",
  "phase": "passed",
  "round_id": 2,
  "detail": null,
  "operation_id": null
}

8ef6356 Geprüfter Abschluss (Demo)
5c02782 start
```

The mock reviewer answers `fix` (verdict `CHANGES`), then `PASS`: the run
takes the back edge once (`round_id: 2`), freezes the reviewed result and
fast-forwards it into `main`. The demo script creates the bead and the
profile (`profil.toml`) itself.
<!-- /readme-script -->

## Two commands

```bash
ki-dev -f implement BEAD                   # drive a bead to the next halt
ki-dev -f implement BEAD --adapter manual  # you relay prompts via stdout/stdin
ki-dev -f implement resume -v RUN_ID       # continue; transitions live
ki-dev -f map step BEAD map.review         # one turn by hand, stateless
```

`-f NAME` searches like `make -f`: `./NAME.toml`, `$KI_DEV_FLOW_PATH`, then
the bundled package. The bead supplies the task, the profile
(`.ki-dev/profiles/default.toml`, `--profile NAME`) roles, checks and limits.

| Adapter | Profile per role | Who answers |
| --- | --- | --- |
| `claude`, `codex` | `executor = "codex"`, `session_id`, `model`, `effort` | prepared agent session |
| `manual` | `executor = "manual"` | you: prompt on stdout, answer on stdin |
| `mock` | `executor = "mock"`, `answers = ["fix", "PASS"]` | scripted answers |

With `manual` an empty answer halts the **executor** (`awaiting_input`), not
the workflow; `resume` asks again. The human thus has two separate roles:
messenger (adapter) and decider (states of kind `wait`).

## What the tests prove

| Claim | Evidence |
| --- | --- |
| no unbounded cycle without a human | `tests/machine/test_reachability.py` enumerates the state space |
| … visible in the data itself | `tests/test_flow_implement.py`: every cycle has a counting edge |
| `PASSED` only via verified integration | `tests/machine/test_reachability.py` |
| layers never import upwards | `tests/test_schichten.py` (transitive, AST) |
| README diagrams match the workflows | `tests/test_flow_implement.py`, `tests/test_flow_planning.py` |

## Limits, precisely

- `runner/safety.py` checks call, token and cost limits *before the next*
  call; a single call can exceed `max_total_tokens`, cache reads count in
  full. Only Claude is bounded within a call (`--max-budget-usd`,
  `--max-turns`), Codex is not. `step` (adapter manual) measures no tokens.
- The access profile in a task is prompt text, not a lock; isolation comes
  from the [agent container](docker/agent/README.md).
- `step` compares nothing with the repository; the human answers for
  the answers passed in. PASS in `implement_review` needs the preflight
  facts (guard `full_checks`, input from `implement.preflight`).

## Installation

Prerequisites and setup: see [above](#try-it-in-a-minute); the `Makefile`
is short and readable.

<!-- readme-script: readme-scripts/en/2-runtime.sh -->
For development on ki-dev: separate runtime venv and a symlink in
`~/.local/bin` (honors XDG_DATA_HOME).
Finish active and paused runs before each update.
Details: [self-development runbook (German)](docs/self-development.de.md).

```bash
make setup-runtime
export PATH="$HOME/.local/bin:$PATH"
ki-dev --help
```
<!-- /readme-script -->

```bash
make test           # pytest and ruff
make readme-check   # README setup in a throwaway container (needs Docker)
```

Or the agent container with bd, Codex and Claude Code:
`./scripts/agent-container shell` ([docker/agent/README.md](docker/agent/README.md)).

The German [README](README.md) has the diagrams, the layout of `src/` and
the open points; background and target picture:
[docs/zielbild.de.md](docs/zielbild.de.md).
