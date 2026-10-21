# Continue in `calc-work`:
#
# ```bash
mkdir -p .ki-dev/profiles       # ki-dev looks for profiles where it starts
cat >.ki-dev/profiles/default.toml <<'EOF'
workdir = "."                   # agents' worktree, ki-dev starts here
access_profile = "write"

[worker]                        # implements
executor = "codex"              # executor from the scaffold
session_id = "019a…"            # put your Codex session here
model = "gpt-5.6-terra"
effort = "high"

[review]                        # reviews, in its own session
executor = "claude"
session_id = "b3f1…"            # put your Claude Code session here
model = "sonnet"
effort = "high"

[[tests]]                       # runs each round, result goes to review
name = "test_add"
argv = ["python3", "test_add.py"]

[limits]
changes_rounds = 3              # then ki-dev asks a human

[finalization]                  # where an accepted result goes
target_workdir = "../calc"      # repo from step 2
target_ref = "refs/heads/main"
commit_message = "Fix add()"
data_mode = "file_proposal"
EOF
# ```
