"""Mermaid-Diagramme der Abläufe in README und Doku erzeugen.

Ersetzt jeden Block nach ``<!-- ki-dev flow show NAME [OPTION] -->``
durch die Ausgabe von ``ki-dev flow show``. --check meldet Abweichungen
ohne zu schreiben (Exit 1).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ki_dev.flow.diagram import diagram_markers, sync_diagrams
from ki_dev.flow.model import load_flow

ROOT = Path(__file__).resolve().parent.parent
FILES = (
    "README.md",
    "README.en.md",
    "docs/ausfuehrer.de.md",
    "docs/step.de.md",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="nur prüfen, nichts schreiben",
    )
    args = parser.parse_args()
    stale = []
    for name in FILES:
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        if not diagram_markers(text):
            continue
        synced = sync_diagrams(text, load_flow)
        if synced == text:
            continue
        stale.append(name)
        if not args.check:
            path.write_text(synced, encoding="utf-8")
            print(f"{name}: geschrieben")
    if args.check and stale:
        print(f"veraltet: {', '.join(stale)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
