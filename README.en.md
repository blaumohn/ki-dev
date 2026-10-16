<p align="right"><a href="README.md">Deutsch</a> | English</p>

# ki-dev

**AI agents in a checkable workflow: build → review → correction, with
hard limits. What happens after an agent's result lives in TOML, not in
the prompt.**

For anyone who lets Claude or Codex work on real tasks and has to limit
time, tokens and money while doing so.

- **Workflow as data:** every loop is a back edge with a counter → [Example](#a-loop-is-an-edge-not-a-component)
- **Deterministic control:** same state + same event → same edge, no extra model call → [Components](#components)
- **Swappable roles:** Claude, Codex, a human or a mock per role → [Two commands](#two-commands)
- **Backed by tests:** no cycle without a human runs unbounded → [Test bench](#test-bench)
- **As of 2026-10-15 (`ab3c441`):** ✅ 6 proven · ❌ 1 specification red · ⬜ 3 open → [Test bench](#test-bench)

---

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

## Test bench

Tests are the specification here: red means specified, not built yet.

**Legend:** ✅ passed · ❌ red, expected (specification) · ⬜ not checked

Stages 1–4 describe, on a small task, what ki-dev is meant to do: fix
`add()` in `add.py`, checked by fixed tests `add(2, 3) == 5` and
`add(-1, 1) == 0`. Only what was actually run through the public CLI
counts; a missing check is shown as "not checked". The first six rows
check the workflow data and the executor from the inside.

| Capability | Status | Check it yourself | Contribute | Bead |
| --- | --- | --- | --- | --- |
| no unbounded cycle without a human; the whole state space is enumerated | ✅ passed | `.venv/bin/pytest -q tests/machine/test_reachability.py` | – | – |
| … visible in the data itself: every cycle has a counting edge | ✅ passed | `.venv/bin/pytest -q tests/test_flow_implement.py` | – | – |
| `PASSED` only via verified integration | ✅ passed | `.venv/bin/pytest -q tests/machine/test_reachability.py` | – | – |
| workflow and executor share one vocabulary (`ki_dev.fsm.bind` checks on import) | ✅ passed | `.venv/bin/pytest -q tests/test_flow_implement.py tests/test_fsm.py` | – | – |
| layers never import upwards (transitive, AST) | ✅ passed | `.venv/bin/pytest -q tests/test_schichten.py` | – | – |
| the messenger halts the executor, not the workflow | ✅ passed | `.venv/bin/pytest -q tests/test_runner_runtime.py tests/test_runner_cli.py` | – | – |
| stage 1 task: a run fixes `add()`; only `add.py` changes | ⬜ not checked: the mock worker only appends text to `MOCK.md`, a test executor that changes `add.py` is missing; the test oracles themselves are checked (stage 2) | – | write a spec test | unu, 1nf |
| stage 2 review: red tests + review `PASS` → no integration | ❌ red, expected: `ki-dev -f implement` integrates anyway (below) | `.venv/bin/pytest -q --runxfail tests/test_review_gate_cli.py` | build the gate in the executor; the test tells you when it is done | ek1 |
| stage 3 limits: context 85,000 at limit 80,000 → no further agent call, visible halt | ⬜ not checked: `mock` and `manual` measure nothing, the guards do not apply there; the guards of the old executor are tested only internally (`tests/test_context_guard.py`, `tests/test_quota_guard.py`, `tests/test_runner_safety.py`) | – | write a spec test | v5w, 1nf |
| stage 4 handoff: parent task, role and test command appear in the handoff to the agent | ⬜ not checked: no test | – | write a spec test | 76e |

Bead: short IDs from the project-internal Beads database (`ki-dev-ablauf-…`); a public journal will follow.

<!-- readme-script: readme-scripts/en/3-review-gate.sh -->
Stage 2 through the public CLI: `ki-dev -f implement` with a mock
worker and a mock review (`PASS`) against a throwaway repository with
`add.py` (wrong: `a - b`) and a fixed `test_add.py`. No provider
access; needs git and `bd` from `make setup`. The controls check the
test itself: the oracle is red for `a - b` and green for `a + b`; a
collection error does not count as a red test; green tests + PASS
integrate. The core case is red today and marked `xfail(strict=True)`;
`--runxfail` shows the failure:

```bash
.venv/bin/pytest -q --runxfail tests/test_review_gate_cli.py
```

```text
E   tests.test_review_gate_cli.IntegratedDespiteRedTests: 3e696bb -> d14aedd: Fast-forward integriert
FAILED tests/test_review_gate_cli.py::test_red_tests_and_review_pass_do_not_integrate
1 failed, 4 passed
```

Shortened; the hashes change on every run. The run integrated into
`main` despite red tests (ek1). Without `--runxfail` the
same command reports `4 passed, 1 xfailed`.
<!-- /readme-script -->

Everything at once:

```bash
.venv/bin/pytest -q && .venv/bin/ruff check .
```

As of 2026-10-15 (branch `dev` after `ab3c441`): 2740 passed,
1 expectedly red (`xfail`, stage 2), 1 skipped (Docker test, no Docker
in the test environment), 14 deselected (scaffold controls of the
requirement tests, `make spec-test`); ruff clean. `make demo` and the
test suite are also checked with mocks. Not checked: `make readme-check`
and runs with real providers (`claude`, `codex`); their acceptance is
pending.

### What the architecture is missing

Source: [executor architecture: what is missing (German)](docs/ausfuehrer-luecken.de.md)
(as of 2026-10-14) and the stage 2 finding.

| Property | today → target | Contribute | Bead |
| --- | --- | --- | --- |
| a review `PASS` does not override red tests | `ki-dev -f implement` integrates after a review `PASS` despite red `[[tests]]` → integration only with green checks | as in stage 2: build the gate until the test is green | ek1 |
| safety halt at context, quota and budget limits | Python guards in the old executor `flow_ops/implement/runtime.py` (`_context_guard`, `_quota_guard`, budget ledger), only for `-f implement` → measured by the adapter, compared as an edge in `runner/run.toml` (`measured` with guard `within_limits`), limit value in the profile | spec test for stage 3, then build edge and guard | ige.6.4.1 to .4 |
| one executor | `-f implement` drives the old executor, `step` the shared `runner/package.py`; its dispatch calls the executor without any safety check → `-f implement` and `step` on `runner/package.py`, old executor removed | move `-f implement` onto `runner/package.py` | ige.6.4.13, .14 |
| retry on process and protocol errors, halt note, finalization | only for `-f implement`: edges in `implement.toml`, effects in the old executor; the shared executor lacks them → scaffold (`run.toml`) or pattern with finalization | move the edges into the scaffold or pattern | ige.6.4.5, .6, .10 to .12 |
| round limits in the review pattern (`map`, `graph`, `materialize`) | only `implement.toml` counts rounds; the pattern's correction edge has no counter → package guards in the pattern | add a counter to the pattern's correction edge | ige.6.4.7, .8 |

Still to be mapped, without a test: session binding as workflow data
(`neu | wie:<zustand>`) and adaptive cuts by the controller
([target picture, German](docs/zielbild.de.md)).

---

## Components

The three components divide responsibility:

| Component | Defines | Contents / role |
| --- | --- | --- |
| `flow/*.toml` (`implement`, `map`, `graph`, …) | **What** may happen | Data: states, transitions, guards and actions |
| `runner/` | **How** the workflow executes | Formal answer → event → select edge (python-statemachine) → next input; one record per step, a halt ends the process |
| `adapter/` | **Who** handles the input | Connects Claude, Codex, a human (`manual`) or a simulation (`mock`) |

The executor (`runner/`) reads the workflow file and calls the appropriate
adapter. With `ki-dev -f implement BEAD`, this happens automatically.

`ki-dev -f FLOW step` is the same idea by hand: exactly one turn of a
workflow, stateless, carried on by a human as messenger.

Selecting edges, checking answer formats and comparing limits need no
extra model call; a domain review by a human or an AI is still needed.
Low resource use is a design goal, not a measured saving.

## A loop is an edge, not a component

Build, review, fix, review again is not a "loop" layer but a back edge in
the workflow. Guards decide when it ends; every back edge consumes a counter.
From [`src/ki_dev/flow/implement.toml`](src/ki_dev/flow/implement.toml):

```toml
# controller_step --fix [cond] / on--> target   (UML edge)

# correction budget spent → human (no target: the run halts,
# the workflow stays here)
[[statechart.states.active.states.controller_step.transitions]]
event = "fix"
cond = "checked_result"
unless = "changes_rounds_left"
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
edges and handles `raise`; the executor only knows guard and action
names, not the topology. A pause belongs to the run (`runner/run.toml`):
the workflow stays where it escalated.

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

## Limits, precisely

- **Protection only where something is measured:** limits apply only in
  `ki-dev -f implement` and only for executors that declare the
  measurement ([`adapter/executors.toml`](src/ki_dev/adapter/executors.toml)):
  `claude` measures context, quota and budget; `codex` quota and budget,
  **no context limit**; `mock` and `manual` measure nothing, no limit
  applies there, not even `max_agent_calls`.
- **Before the next call:** `runner/safety.py` checks call, token and
  cost limits *before the next* call; a single call can exceed
  `max_total_tokens`, cache reads count in full. Only Claude is bounded
  within a call (`--max-budget-usd`, `--max-turns`), Codex is not.
- **`step`:** measures no tokens (executor `manual`) and compares nothing
  with the repository; the human answers for the answers passed in. PASS
  in `implement_review` needs the preflight facts (guard `full_checks`,
  input from `implement.preflight`).
- **Access:** the access profile in a task is prompt text, not a lock;
  isolation comes from the [agent container](docker/agent/README.md).

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

## Background

### Why ki-dev

For my requirements on low-resource, deterministic control of AI
development workflows I did not find a suitable open-source solution I
could use. That is how ki-dev started. Related research (below) supports
the approach and informs further development.

The resource design: a supervising model that reads ten agent outputs of
10,000 tokens each once in full spends 100,000 input tokens before it
answers itself. ki-dev decides formal events, answer formats and limit
values in code; the full texts stay available as artifacts. What this
actually saves depends on model, cache and context selection and has
not been measured.

### Bootstrap problem

The work ki-dev grew out of did not run on ki-dev workflows: whole epics
were planned and implemented in a few chats with AI agents. The result
was repeated surprises and success reports even though explicitly given
main and architecture requirements had been skipped. The workflows meant
to prevent this are therefore built with the means they are meant to
replace. Until they carry the work, the rule applies by hand: cut tasks
to a size that fits an agent's context, make requirements explicit and
check them separately, as in the teaching stages above.

### After publication: V1

V1 completes the single workflows `map`, `graph`, `materialize` and
`implement`. In V1 the chain map → graph → materialize → implementation
is linked by hand, each workflow with its roles, reviews and halts; a
fully automated end-to-end chain is not a V1 goal. Example: `map` records
the requirement "protection before every agent call", `graph` orders
profile → measurement → guard → wiring, `materialize` cuts bounded tasks
with boundary-case acceptance, and the implementation checks on the new
executor: measured 85,000 at limit 80,000 → no agent call, logged safety
halt. Separate and optional later: AI-assisted calibration of workflows
and profiles, small local models.

### Research and related work

- [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/html/2503.13657v3)
  (Cemri et al., 2025) derives the failure taxonomy MAST from an
  empirical study, including premature termination (FM-3.1), no or
  incomplete verification (FM-3.2) and incorrect verification (FM-3.3).
  In its case studies, clearer roles, a changed workflow and an added
  check of the overall objective improved the success rate with the same
  model (at most +15.6 %), which still stayed low. Structured workflows
  and verification are thus an empirically supported approach; whether
  ki-dev prevents these failures has not been measured.
- [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
  (Anthropic, 2024) distinguishes workflows with predefined code paths
  from agents that direct their own path, and describes programmatic
  checks ("gates") between steps. ki-dev puts control on the workflow
  side; agents work inside a state.
- [Gas City](https://github.com/gastownhall/gascity) also works with
  Beads: a swappable `beads.Store` (bd, file, memory, exec;
  [beads.md](https://github.com/gastownhall/gascity/blob/main/engdocs/architecture/beads.md))
  and a controller that executes formulas as a graph of step and control
  beads ([nine-concepts.md](https://github.com/gastownhall/gascity/blob/main/engdocs/architecture/nine-concepts.md);
  both read on 2026-10-15). In both projects Beads remains the domain and
  state model of the work. No cost or feature comparison is made here.

The German [README](README.md) has the diagrams, the layout of `src/`,
the feature overview and the non-goals; background and target picture:
[docs/zielbild.de.md](docs/zielbild.de.md).
