"""Echter bd-Ersatzprozess für den Beads-Lese-Adapter.

Das Skript gibt feste Rohbytes aus, damit Prozessgrenze, Frist und
Dekodierung wirklich durchlaufen werden. Zustand liegt in einer
JSON-Datei, jeder Aufruf wird mit Argumenten und Arbeitsverzeichnis
protokolliert.
"""

import json
import stat
import sys
from pathlib import Path

SCRIPT = """#!{python}
import json, os, sys, time
STATE = {state!r}
LOG = {log!r}
args = sys.argv[1:]
state = json.load(open(STATE))
with open(LOG, "a") as log:
    log.write(json.dumps({{"args": args, "cwd": os.getcwd()}}) + "\\n")
if state["hang"]:
    time.sleep(30)
graph = state["graph"]
if graph is not None:
    out = json.dumps([graph[args[2]]], ensure_ascii=False).encode()
else:
    out = bytes.fromhex(state["stdout_hex"])
sys.stdout.buffer.write(out)
sys.stderr.write(state["stderr"])
sys.exit(state["returncode"])
"""


class _State(dict):
    """Zustand mit Durchschreiben in die Datei des Skripts."""

    def __init__(self, owner, **values):
        super().__init__(values)
        self._owner = owner

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._owner._save()

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._owner._save()


class BdScript:
    def __init__(self, directory: Path, **values) -> None:
        self.script = directory / "bd"
        self._state_path = directory / "bd-state.json"
        self._log_path = directory / "bd-calls.jsonl"
        self.script.write_text(
            SCRIPT.format(
                python=sys.executable,
                state=str(self._state_path),
                log=str(self._log_path),
            )
        )
        self.script.chmod(self.script.stat().st_mode | stat.S_IXUSR)
        self.state = _State(
            self,
            stdout="",
            returncode=0,
            stderr="",
            hang=False,
            graph=None,
        )
        self.state.update(values)

    def _save(self) -> None:
        values = dict(self.state)
        stdout = values.pop("stdout")
        raw = stdout if isinstance(stdout, bytes) else stdout.encode()
        values["stdout_hex"] = raw.hex()
        self._state_path.write_text(json.dumps(values))

    def _entries(self) -> list[dict]:
        if not self._log_path.exists():
            return []
        lines = self._log_path.read_text().splitlines()
        return [json.loads(line) for line in lines]

    @property
    def calls(self) -> list[list[str]]:
        return [["bd", *entry["args"]] for entry in self._entries()]

    @property
    def cwds(self) -> list[str]:
        return [entry["cwd"] for entry in self._entries()]

    def break_interpreter(self) -> None:
        """Das Programm existiert, lässt sich aber nicht starten."""
        text = self.script.read_text().split("\n", 1)[1]
        self.script.write_text("#!/nicht/vorhanden/python\n" + text)

    def install(self, monkeypatch) -> None:
        from ki_dev.step import beads_reader

        # Plumbum sucht über sein beim Import erfasstes PATH; darum
        # den Adapter ausdrücklich auf das Skript zeigen lassen.
        monkeypatch.setattr(
            beads_reader, "BD_PROGRAM", str(self.script)
        )
