#!/usr/bin/env bash
# Installation aktualisiert bewusst einen einzelnen Betriebsstand.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
runtime="${XDG_DATA_HOME:-$HOME/.local/share}/ki-dev/venv"
link="$HOME/.local/bin/ki-dev"
python=${KI_DEV_SETUP_PYTHON:-python3}

fail() { printf '%s\n' "$*" >&2; exit 1; }

# Eigene Kopie: Arbeitsbaum und Merges ändern den Launcher laufender Läufe
# nicht. Der Austausch per Umbenennen trifft kein gerade laufendes Skript.
install_launcher() {
  local target="${XDG_DATA_HOME:-$HOME/.local/share}/ki-dev/agent-container"
  local staging="$target.neu"
  rm -rf -- "$staging"
  mkdir -p "$staging/scripts" "$staging/docker"
  cp "$repo"/compose.yaml "$repo"/compose.beads.yaml "$repo"/compose.fresh.yaml \
    "$repo"/compose.workdir.yaml "$staging/"
  cp "$repo/scripts/agent-container" "$staging/scripts/"
  cp -R "$repo/scripts/lib" "$staging/scripts/"
  cp -R "$repo/docker/agent-settings" "$staging/docker/"
  rm -rf -- "$target"
  mv -- "$staging" "$target"
}

[[ "$runtime" == /* ]] || fail 'XDG_DATA_HOME muss ein absoluter Pfad sein.'
if [[ -e "$link" || -L "$link" ]]; then
  [[ -L "$link" && $(readlink "$link") == "$runtime/bin/ki-dev" ]] ||
    fail "Vorhandenes $link gehört nicht zu dieser Installation."
fi

# Auch Symlink-Pfade dürfen die Betriebsinstallation nicht ins Repo legen.
"$python" -I - "$runtime" "$repo" <<'PY'
from pathlib import Path
import sys

if sys.version_info < (3, 12):
    sys.exit("Python >= 3.12 erforderlich.")
runtime, repo = map(lambda value: Path(value).resolve(), sys.argv[1:])
if runtime == repo or repo in runtime.parents:
    sys.exit("Betriebsinstallation muss außerhalb des Quellrepos liegen.")
PY

if [[ ! -e "$runtime" ]]; then
  "$python" -I -m venv "$runtime"
elif [[ ! -f "$runtime/pyvenv.cfg" || ! -x "$runtime/bin/python" ]]; then
  fail "Vorhandenes $runtime ist kein venv."
fi

printf '%s\n' 'Runtime-Update: aktive und pausierte ki-dev-Läufe müssen vorher abgeschlossen sein.' >&2
# Ein lokales Paket wird auch bei unveränderter Versionsnummer neu gebaut
# und installiert. Kein -e: Arbeitsbaumänderungen wirken erst nach Update.
"$runtime/bin/python" -I -m pip install --upgrade "$repo"
# Isolierter Einstieg: auch geerbtes PYTHONPATH darf kein Arbeitsrepo laden.
"$runtime/bin/python" -I - "$runtime" <<'PY'
from pathlib import Path
import shlex
import sys

runtime = Path(sys.argv[1])
entry = runtime / "bin/ki-dev"
entry.write_text(
    "#!/bin/sh\nunset PYTHONPATH PYTHONHOME\nexec "
    + shlex.quote(str(runtime / "bin/python"))
    + " -I -c 'from ki_dev.cli import main; main()' \"$@\"\n"
)
entry.chmod(0o755)
PY
install_launcher
mkdir -p "$HOME/.local/bin"
if [[ ! -L "$link" ]]; then
  ln -s "$runtime/bin/ki-dev" "$link"
fi
printf 'Installiert: %s\nPATH muss %s enthalten.\n' "$link" "$HOME/.local/bin"
