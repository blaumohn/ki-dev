# The profile fills the roles: Codex implements, Claude Code reviews.
# Both use the cheapest model of their CLI with effort `low`; ki-dev
# creates a separate session for each role on its first call.
# Continue in `calc-work`:
#
# ```bash
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
# ```
#
# - `executor` can be swapped per role; available are `codex`,
#   `claude`, `mock` and `manual`
#   ([executors](docs/ausfuehrer.de.md#executoren), German).
# - Per-call limits (time, cost, quota) have
#   [defaults](docs/ausfuehrer.de.md#verbrauchsschutz) (German).
