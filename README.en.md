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

Named stages instead of version numbers:

1. **step**: the workflow by hand (today).
2. **loop**: sessions connected automatically, independent of the phase.
3. **declarative workflows**: flows as data; `step-flow.toml` is the first
   precursor.
4. **state/event interface**: run state and events behind one interface.

Details, design rationale and non-goals: [README.md](README.md) (German).
