"""AGENTS.md und CLAUDE.md in diesem Klon schreibschützen.

Git transportiert keinen Schreibschutz (nur das Ausführungsbit): Nach
jedem frischen Klon einmal ausführen. Die Dateien sind im Repository
leer; der Einstiegskontext kommt aus ``ki-dev handoff`` (Bead-Form und
``local``). Standard setzt 0444, aber nur auf leere Dateien; ``--check``
prüft leer und schreibgeschützt, ohne etwas zu ändern (Exit 1 bei
Abweichung). Schutz aufheben: ``chmod u+w AGENTS.md CLAUDE.md``.
"""

from __future__ import annotations

import argparse
import stat
import sys
from pathlib import Path

FILES = ("AGENTS.md", "CLAUDE.md")
READ_ONLY = 0o444


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="nur prüfen, nichts ändern",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Projektwurzel (Standard: Elternverzeichnis von scripts/)",
    )
    args = parser.parse_args()
    problems = []
    for name in FILES:
        problems += _handle(args.root / name, name, args.check)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


def _handle(path: Path, name: str, check: bool) -> list[str]:
    """Abweichungen einer Datei; ändert nur bei ``check`` False und
    leerer Datei den Modus."""
    try:
        info = path.stat()
    except OSError as exc:
        return [f"{name}: nicht lesbar ({type(exc).__name__})"]
    if info.st_size:
        return [
            f"{name}: nicht leer ({info.st_size} Bytes); Einstiegstext "
            "gehört nach docs/policies/*.de.yaml. Mit "
            f"`git checkout -- {name}` zurücksetzen, nicht schützen."
        ]
    if not check:
        path.chmod(READ_ONLY)
        return []
    if stat.S_IMODE(info.st_mode) & 0o222:
        return [f"{name}: nicht schreibgeschützt"]
    return []


if __name__ == "__main__":
    sys.exit(main())
