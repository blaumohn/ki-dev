# Every run reads the profile at start, without `--profile` the profile
# `default`; ki-dev creates a separate session for each role on its
# first call. Continue in `app-work`:
#
# ```bash
mkdir -p .ki-dev/profiles       # profiles in the starting directory
cat >.ki-dev/profiles/default.toml <<'EOF'
workdir = "."                   # agents' worktree, ki-dev starts here
access_profile = "write"        # the worker may write here

[worker]                        # implements; history: Umsetzer
executor = "codex"
model = "gpt-6-luna"            # cheapest model of the CLI
effort = "low"

[review]                        # reviews, read-only
executor = "claude"
model = "haiku"                 # cheapest model of the CLI
effort = "low"

[[tests]]                       # the repo's tests; the flow runs them
name = "test_version"
argv = ["python3", "test_version.py"]

[limits]
changes_rounds = 2              # at most two correction rounds

[safety_limits]
max_agent_calls = 10            # agent calls in the whole run

[finalization]                  # where an accepted result goes
target_workdir = "../app"       # target repo with branch main
target_ref = "refs/heads/main"
commit_message = "Tests green, review PASS"  # for every task
EOF
# ```
#
# - `executor` can be swapped per role; available are `codex`,
#   `claude`, `mock` and `manual`
#   ([executors](docs/ausfuehrer.de.md#executoren), German).
# - `max_agent_calls` limits the agent calls of the whole run,
#   including retries after empty or invalid answers (default 6).
#   Per-call limits (time, cost, quota) have
#   [defaults](docs/ausfuehrer.de.md#verbrauchsschutz) (German).
