"""Leitlinien-Markdown aus docs/policies/*.de.yaml erzeugen.

Standard schreibt abweichende Seiten; --check meldet Abweichungen
ohne zu schreiben (Exit 1). Quellenfehler: Exit 1 (fehlend/unlesbar)
oder 2 (ungültiges YAML/Vertrag).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ki_dev.step.guidelines import GuidelineContractError
from ki_dev.step.guidelines_source import (
    GuidelineSourceError,
    sync_guideline_documents,
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
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Projektwurzel (Standard: aktuelles Verzeichnis)",
    )
    args = parser.parse_args()
    try:
        drift = sync_guideline_documents(args.root, check=args.check)
    except GuidelineSourceError as exc:
        print(f"Leitlinienquelle nicht lesbar: {exc}", file=sys.stderr)
        return 1
    except GuidelineContractError as exc:
        for problem in exc.problems:
            print(f"{exc.source}: {problem}", file=sys.stderr)
        return 2
    for path in drift:
        state = "weicht ab" if args.check else "geschrieben"
        print(f"{path}: {state}")
    return 1 if args.check and drift else 0


if __name__ == "__main__":
    sys.exit(main())
