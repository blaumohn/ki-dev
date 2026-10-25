#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: scripts/bd-clear-comments.sh <issue-id>[=<comment-id>,...] ...

Entfernt alle Kommentare der angegebenen bd-Vorgaenge (bd issues), mit
=<comment-id>,... nur diese Kommentare des Vorgangs. Die zweite Form
nutzt 'comments export' (ki_dev.beads_journal): ein Kommentar, der nach
dessen bd export entsteht, bleibt so in bd.

bd selbst bietet nur 'bd comment'/'bd comments add' zum Hinzufuegen von
Kommentaren, aber keinen Befehl zum Loeschen. Dieses Skript greift daher
direkt auf die zugrunde liegende Dolt-Datenbank zu und exportiert
anschliessend .beads/issues.jsonl neu, damit der Dateiexport wieder mit
der Datenbank uebereinstimmt.
EOF
  exit 1
}

[ "$#" -ge 1 ] || usage

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

command -v bd >/dev/null 2>&1 || { echo "Fehler: 'bd' nicht im PATH gefunden." >&2; exit 1; }
command -v dolt >/dev/null 2>&1 || { echo "Fehler: 'dolt' nicht im PATH gefunden." >&2; exit 1; }

dolt_show="$(bd dolt show 2>&1)" || {
  echo "Fehler: 'bd dolt show' fehlgeschlagen:" >&2
  printf '%s\n' "$dolt_show" >&2
  exit 1
}
data_dir="$(printf '%s\n' "$dolt_show" | sed -n 's/^ *Data: *//p')"
db_name="$(printf '%s\n' "$dolt_show" | sed -n 's/^ *Database: *//p')"
[ -n "$data_dir" ] && [ -n "$db_name" ] || {
  echo "Fehler: Dolt-Datenverzeichnis/-Datenbank konnte nicht aus 'bd dolt show' ermittelt werden." >&2
  exit 1
}
db_path="$data_dir/$db_name"
[ -d "$db_path" ] || { echo "Fehler: Dolt-Datenverzeichnis nicht gefunden: $db_path" >&2; exit 1; }

sql_escape() {
  printf '%s' "$1" | sed "s/'/''/g"
}

any_failed=0
any_deleted=0

for arg in "$@"; do
  issue_id="${arg%%=*}"
  only=""
  if [ "$issue_id" != "$arg" ]; then
    ids="${arg#*=}"
    [ -n "$ids" ] || { echo "Fehler: keine Kommentar-IDs in '$arg'." >&2; exit 1; }
    only=" AND id IN ("
    sep=""
    IFS=, read -r -a id_list <<<"$ids"
    for comment_id in "${id_list[@]}"; do
      only="$only$sep'$(sql_escape "$comment_id")'"
      sep=", "
    done
    only="$only)"
  fi

  if ! bd show "$issue_id" >/dev/null 2>&1; then
    echo "Warnung: Vorgang '$issue_id' nicht gefunden, ueberspringe." >&2
    any_failed=1
    continue
  fi

  esc_id="$(sql_escape "$issue_id")"
  before="$(dolt --data-dir "$db_path" sql -r csv \
    -q "SELECT COUNT(*) AS n FROM comments WHERE issue_id = '$esc_id'$only;" | tail -n1)"

  if [ "$before" = "0" ]; then
    echo "Info: '$issue_id' hat keine Kommentare, nichts zu tun."
    continue
  fi

  dolt --data-dir "$db_path" sql \
    -q "DELETE FROM comments WHERE issue_id = '$esc_id'$only;"
  echo "OK: $before Kommentar(e) von '$issue_id' entfernt."
  any_deleted=1
done

if [ "$any_deleted" -eq 1 ]; then
  echo "Exportiere aktualisierten Stand nach .beads/issues.jsonl ..."
  bd export -o .beads/issues.jsonl
fi

exit "$any_failed"
