"""Gefaketer bd-Prozess: echtes Skript, Zustand in einer JSON-Datei."""

import json
import os
import stat
import sys
from pathlib import Path

SCRIPT = """#!{python}
import json, sys, time
STATE = {state!r}
args = sys.argv[1:]
state = json.load(open(STATE))
state["calls"].append(args)
command = "show" if "show" in args else args[0]

def save():
    json.dump(state, open(STATE, "w"))

if state.get("hang") == command:
    save()
    time.sleep(30)
if state.get("fail_on") == command:
    save()
    sys.stdout.write(state["secret"])
    sys.stderr.write(state["secret"])
    sys.exit(3)
if command == "list":
    print(json.dumps(state["rows"]))
elif command == "create":
    meta = json.loads(args[args.index("--metadata") + 1])
    if not state.get("create_nothing"):
        state["rows"].append(
            {{
                "id": "t-%d" % (len(state["rows"]) + 1),
                "title": args[1],
                "description": args[args.index("--description") + 1],
                "status": state.get("status", "open"),
                "metadata": meta,
            }}
        )
    print("t-%d" % len(state["rows"]))
elif command == "show":
    bead_id = args[args.index("show") + 1]
    print(json.dumps([r for r in state["rows"] if r["id"] == bead_id]))
save()
"""


class FakeBd:
    def __init__(self, directory: Path, secret: str) -> None:
        self.state_path = directory / "bd-state.json"
        self.script = directory / "bd"
        self.script.write_text(
            SCRIPT.format(
                python=sys.executable, state=str(self.state_path)
            )
        )
        self.script.chmod(self.script.stat().st_mode | stat.S_IXUSR)
        self.set(rows=[], calls=[], secret=secret)

    def set(self, **changes) -> None:
        state = self.get() if self.state_path.exists() else {}
        self.state_path.write_text(json.dumps(state | changes))

    def get(self) -> dict:
        return json.loads(self.state_path.read_text())

    @property
    def rows(self) -> list[dict]:
        return self.get()["rows"]

    def commands(self) -> list[str]:
        return [
            "show" if "show" in call else call[0]
            for call in self.get()["calls"]
        ]

    def install(self, monkeypatch) -> None:
        from ki_dev import beads_reader, beads_source

        # Plumbum sucht ueber sein beim Import erfasstes PATH; darum
        # beide Adapter ausdruecklich auf das Skript zeigen lassen.
        for adapter in (beads_source, beads_reader):
            monkeypatch.setattr(adapter, "BD_PROGRAM", str(self.script))
        monkeypatch.setenv(
            "PATH",
            f"{self.script.parent}{os.pathsep}{os.environ['PATH']}",
        )
