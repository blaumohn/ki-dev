# Worktree mode of scripts/agent-container; see docker/agent/README.md.
# Host and container share the path, so gitdir files, session folders and
# profile paths need no translation. Everything the host later executes or
# git reads as configuration stays read-only inside the container.

# A path Docker does not share with its VM arrives as an empty directory;
# without this check the agent would start and work in it.
WORKDIR_GUARD='if ! git rev-parse --git-dir >/dev/null; then
  echo "agent-container: Worktree $PWD ist im Container nicht nutzbar; liegt er in einem für Docker freigegebenen Ordner?" >&2
  exit 125
fi
exec "$@"'

set_workdir() {
  workdir="$(cd -- "$1" 2>/dev/null && pwd -P)" || usage_error "kein Verzeichnis: '$1'"
  git_common="$(git -C "$workdir" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" ||
    usage_error "kein Git-Worktree: '$workdir'"
  git_dir="$(git -C "$workdir" rev-parse --path-format=absolute --git-dir)"
  target_repo="$(dirname -- "$git_common")"
  if [[ "$workdir" == *:* || "$git_common" == *:* ]]; then
    usage_error "nicht unterstützter Pfad für --workdir: '$workdir'"
  fi
}

# Mount order does not matter: Docker sorts mounts by target depth.
add_workdir_args() {
  compose_files+=(-f "$repo_dir/compose.workdir.yaml")
  run_args+=(-w "$workdir")
  bind_rw "$workdir"
  bind_rw "$git_common"
  bind_ro "$workdir/.git"
  bind_ro "$git_common/config"
  bind_ro "$git_common/hooks"
  if [[ "$git_dir" != "$git_common" ]]; then
    bind_ro "$git_dir/commondir"
    bind_ro "$git_dir/gitdir"
  fi
  if [[ -d "$target_repo/.beads" ]]; then
    bind_rw "$target_repo/.beads"
    bind_ro "$target_repo/.beads/hooks"
    bind_ro "$target_repo/.beads/config.yaml"
  fi
}

bind_rw() {
  run_args+=(-v "$1:$1")
}

bind_ro() {
  if [[ -e "$1" ]]; then run_args+=(-v "$1:$1:ro"); fi
}

stop_container() {
  if [[ $# != 1 ]]; then usage_error "stop requires a container name"; fi
  # After Ctrl-C Compose removes the container too; rm then reports
  # "removal already in progress" for a moment. A missing container is fine.
  local attempt
  for attempt in 1 2 3 4 5; do
    if docker rm -f "$1" >/dev/null 2>&1; then return; fi
    sleep 1
  done
  docker rm -f "$1" >/dev/null
}
