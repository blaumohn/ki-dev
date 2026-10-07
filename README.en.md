<p align="right"><a href="README.md">Deutsch</a> | English</p>

---

# ki-dev

**A deterministic orchestrator for AI-assisted development and project work
in small teams.**

The machine keeps state, role order, step boundaries and evidence of change.
The AI writes code and judges results.

> **Status: active development.** Usable today is `ki-dev step`, the same
> workflow driven by hand. The automated loop (`ki-dev loop`) comes next.
> The German [README](README.md) is the full reference.

## Installation

Requires Python ≥ 3.12, git ≥ 2.32 and [Beads](https://github.com/steveyegge/beads)
`bd` **1.3.0** (release build). `go install` needs Go and a C compiler
(CGO for embedded Dolt).

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
CGO_ENABLED=1 go install -tags gms_pure_go github.com/steveyegge/beads/cmd/bd@v1.3.0
```

Or use the agent container, which ships bd, Codex and Claude Code:
`./scripts/agent-container shell` ([docker/agent/README.md](docker/agent/README.md)).

## `ki-dev step`: the workflow by hand

`ki-dev step` prints a short, validated handoff for each step. You paste it
into a Claude or Codex session and pass the answer on. Every rule that should
later run automatically is tried by hand first. The command never starts an
agent.

```bash
ki-dev step BEAD --step map           # map raw notes into a source map
ki-dev step BEAD --step graph         # derive thin tasks
ki-dev step BEAD --step materialize   # make one task ready to build
ki-dev step BEAD --step build         # implement it
ki-dev step BEAD --step review        # separate review after a deterministic preflight
ki-dev step BEAD --step review --next-turn --decision-file answer.json
```

Each phase has its own states, declared as data in
[`src/ki_dev/step-flow.toml`](src/ki_dev/step-flow.toml) and checked by tests
(every state reaches the end). Review findings carry a class:

| Class | Verdict | Next |
| --- | --- | --- |
| `fix` | `CHANGES` | the same writer fixes it |
| `quelle` (source) | `NEEDS_DECISION` | planning session, then extend the **existing** map |
| `entscheidung` (decision) | `NEEDS_DECISION` | the human decides |

A build review ends with one JSON object, the same contract the loop uses:
`{"action": "CHANGES", "detail": "…", "requirement_ref": "AC2"}`.
`--decision-file` validates it, binds it to an acceptance criterion and
prints the message for the next recipient. A partial preflight
(`--preflight-args`, `--preflight-skip`) allows an interim review but never
a PASS.

## Direction

Named stages instead of version numbers. Only the order **step → loop** is
fixed:

- **step**: the workflow by hand (today).
- **loop**: sessions connected automatically, independent of the phase.

Topics without a fixed order or date: **declarative workflows** (flows as
data; `step-flow.toml` is a first approach) and a **state/event interface**
for run state and events.

## Sessions as sources

```bash
ki-dev session show SESSION_ID --agent claude --pager      # read-only, Rich output
ki-dev session transcript SESSION_ID --agent claude --title 'Topic'
ki-dev session export SESSION_ID --agent codex --format markdown
```

`transcript` and `ki-dev step map … --title …` write one dated JSONL snapshot
(`.local/var/transcripts/YYMMDDTHH_title_sid8.jsonl`, not versioned); `show`
and `export` write nothing. Search is not available yet.

Details, design rationale and non-goals: [README.md](README.md) (German).
