<p align="right"><a href="README.md">Deutsch</a> | English</p>

# ki-dev

**Agent work as a declarative workflow: states and transitions live in
TOML, an executor drives them, adapters talk to Claude, Codex or a human.**

The AI writes code and judges results. What happens next (another
correction round, a halt for a decision, a verified integration) is neither
in the prompt nor in Python code; it is in the workflow.

```text
 flow/delivery.toml · planning.toml     WHAT  states, transitions, guards, actions      data
        │ read by
  runner/           ki-dev run      HOW   formal answer → event → guard              LangGraph:
        │ calls                           → edge action → next input                 checkpoint, halt
 adapter/  claude · codex · manual · mock                                           WHO
```

`ki-dev step` is the same idea by hand: exactly one transition of the
planning workflow, carried on by a human as messenger.

## A loop is an edge, not a component

Build, review, fix, review again is not a "loop" layer but a back edge in
the workflow. Guards decide when it ends; every back edge consumes a counter.
From [`src/ki_dev/flow/delivery.toml`](src/ki_dev/flow/delivery.toml):

```toml
# controller_step --fix [cond] / actions--> target   (UML edge)

[[transition]]                     # correction budget spent → human
source = "controller_step"
event = "fix"
cond = ["checked_result", "!changes_rounds_left"]
escalation = "changes_rounds_exhausted"
target = "paused_interactive"

[[transition]]                     # otherwise: next round, counter +1
source = "controller_step"
event = "fix"
cond = ["checked_result"]
actions = ["begin_correction", "drop_result"]
target = "worker_step_prepare"
```

Keys and semantics follow UML state machines and SCXML (`source`,
`event`, `cond`, `actions`, `target`, `@history` as `<history>`). Candidates are tried in file
order, the first matching guard wins, no match means the event is not
allowed there.

## Try it in a minute

Offline, with mock adapters (needs `git` and `bd`):

```bash
scripts/demo-mock-lauf.sh
```

```text
{ "run_id": "demo", "status": "passed", "phase": "passed", "round_id": 2, … }
8ef6356 Geprüfter Abschluss (Demo)
5c02782 start
```

The mock reviewer answers `fix` (verdict `CHANGES`), then `PASS`: the run takes the back
edge once, freezes the reviewed result and fast-forwards it into `main`.

## Two commands

```bash
ki-dev run --config lauf.json      # drive the build workflow to the next halt
ki-dev run resume RUN_ID           # continue after a halt
ki-dev step BEAD --step review     # one planning transition by hand
```

| Adapter | Config per role | Who answers |
| --- | --- | --- |
| `claude`, `codex` | `{"executor": "codex", "session_id": "…", "model": "…", "effort": "high"}` | prepared agent session |
| `manual` | `{"executor": "manual"}` | you carry the input into a session |
| `mock` | `{"executor": "mock", "answers": ["fix", "PASS"]}` | scripted answers |

With `manual` the **executor** halts (`awaiting_input`), not the workflow:
the run stays in its state and continues after the answer file appears.
The human thus has two separate roles: messenger (adapter) and decider
(states of kind `wait`).

## What the tests prove

| Claim | Evidence |
| --- | --- |
| no unbounded cycle without a human | `tests/machine/test_reachability.py` enumerates the state space |
| … visible in the data itself | `tests/test_flow_delivery.py`: every cycle has a counting edge |
| `PASSED` only via verified integration | `tests/machine/test_reachability.py` |
| layers never import upwards | `tests/test_schichten.py` (transitive, AST) |
| README diagrams match the workflows | `tests/test_flow_delivery.py`, `tests/test_flow_planning.py` |

## Installation

Python ≥ 3.12, git ≥ 2.32, [Beads](https://github.com/steveyegge/beads) `bd`
**1.3.0**:

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
CGO_ENABLED=1 go install -tags gms_pure_go github.com/steveyegge/beads/cmd/bd@v1.3.0
.venv/bin/pytest -q && .venv/bin/ruff check .
```

Or the agent container with bd, Codex and Claude Code:
`./scripts/agent-container shell` ([docker/agent/README.md](docker/agent/README.md)).

The German [README](README.md) has the diagrams, the layout of `src/` and
the open points; background and target picture:
[docs/zielbild.de.md](docs/zielbild.de.md).
