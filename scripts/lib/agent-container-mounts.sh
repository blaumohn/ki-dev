# Mount options of scripts/agent-container: --mount-ro, --mount and mounts.

# Referenzordner benötigen weder Repo-Vertrag noch Abhängigkeits-Volumes.
add_ro_mount() {
  local source="$1" name existing
  if [[ ! -d "$source" ]]; then usage_error "kein Verzeichnis: '$source'"; fi
  source="$(cd -- "$source" && pwd -P)"
  if [[ "$source" == / || "$source" == *:* ]]; then
    usage_error "nicht unterstützter Pfad für --mount-ro: '$source'"
  fi
  name="${source##*/}"
  # Bash 3.2 behandelt leere Arrays bei nounset als ungebunden.
  for existing in ${ro_sources[@]+"${ro_sources[@]}"}; do
    if [[ "$existing" == "$source" ]]; then return; fi
    if [[ "${existing##*/}" == "$name" ]]; then
      usage_error "gleicher Ordnername bei --mount-ro: '$name'"
    fi
  done
  ro_sources+=("$source")
}

# Optional sibling checkouts, chosen per call from $mount_dir/NAME.yaml.
add_mounts() {
  local list="$1" names name mount_file
  if [[ ! "$list" =~ ^[a-z0-9-]+(,[a-z0-9-]+)*$ ]]; then
    usage_error "invalid mount list '$list'; expected NAME[,NAME...]"
  fi
  IFS=, read -r -a names <<< "$list"
  for name in "${names[@]}"; do
    mount_file="$(resolve_mount "$name")"
    if [[ " ${compose_files[*]} " != *" $mount_file "* ]]; then
      compose_files+=(-f "$mount_file")
      mount_files+=("$mount_file")
    fi
  done
}

# Exact name first, otherwise a unique prefix (like getopt_long options).
resolve_mount() {
  local name="$1" mount_file
  local matches=()
  if [[ -f "$mount_dir/$name.yaml" ]]; then
    echo "$mount_dir/$name.yaml"
    return
  fi
  for mount_file in "$mount_dir/$name"*.yaml; do
    if [[ -f "$mount_file" ]]; then matches+=("$mount_file"); fi
  done
  case "${#matches[@]}" in
    1) echo "${matches[0]}" ;;
    0) usage_error "unknown mount '$name' in $mount_dir; see: scripts/agent-container mounts" ;;
    *)
      matches=("${matches[@]##*/}")
      usage_error "ambiguous mount '$name': ${matches[*]%.yaml}"
      ;;
  esac
}

# Name, host source and container target of each mount file, read from its
# first source: and target:.
list_mounts() {
  local mount_file name source target
  local found=0
  echo "Mount files in $mount_dir:"
  if [[ ! -d "$mount_dir" ]]; then
    echo "  (directory missing; template: docker/agent/mount.example.yaml)"
    return
  fi
  for mount_file in "$mount_dir"/*.yaml; do
    if [[ ! -f "$mount_file" ]]; then continue; fi
    found=1
    name="${mount_file##*/}"
    source="$(awk '$1 == "source:" { print $2; exit }' "$mount_file")"
    target="$(awk '$1 == "target:" { print $2; exit }' "$mount_file")"
    printf '  %-26s %-26s <- %s\n' "${name%.yaml}" \
      "${target:-(no target)}" "${source:-(no source)}"
  done
  if [[ $found == 0 ]]; then
    echo "  (no mount files; template: docker/agent/mount.example.yaml)"
  fi
}
