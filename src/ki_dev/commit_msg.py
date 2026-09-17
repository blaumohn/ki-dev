"""Prueft die erste Commit-Zeile auf ``<Titel> (<Beads-ID>)...``.

Beispiel einer gueltigen Zeile::

    feat: Python-CLI ergaenzen (ki-dev-ablauf-8dd.1)

Bei mehreren betroffenen Issues folgt je Issue eine eigene,
vollstaendig praefigierte Klammer, z. B.::

    chore: xf2 und cbo schliessen
    (ki-dev-ablauf-xf2) (ki-dev-ablauf-cbo)

Kind-IDs mit Punkt (``ki-dev-ablauf-8dd.1``) sind zulaessig. Der als
``commit-msg`` installierte Git-Hook ruft dieses Modul als Skript auf.

Grund fuer den Zwang zu diesem Format: Beads-Integration. `bd orphans`
erkennt referenzierte Issues ueber ``re.FindAllString`` mit dem Muster
``\\(<praefix>-[a-z0-9.]+\\)`` -- jede ID braucht also eine eigene,
vollstaendige Klammer. Ein kommagetrenntes Kurzformat wie
``(ki-dev-ablauf-xf2, cbo)`` matcht dieses Muster nicht und verknuepft
gar kein Issue; das wurde per `bd orphans` an Testissues empirisch
bestaetigt (Kommaformat: 0 erkannt, Klammer-je-ID: beide erkannt).
"""

import re
import sys

ISSUE_PREFIX = "ki-dev-ablauf"
_EXAMPLE = f"feat: Python-CLI ergaenzen ({ISSUE_PREFIX}-8dd.1)"
_MULTI_EXAMPLE = (
    f"chore: xf2 und cbo in Beads schliessen "
    f"({ISSUE_PREFIX}-xf2) ({ISSUE_PREFIX}-cbo)"
)
_WHY = (
    "Grund: Beads-Integration -- bd orphans erkennt referenzierte "
    r"Issues ueber das Muster \(<praefix>-[a-z0-9.]+\), angewendet "
    "mit FindAllString auf die ganze Zeile. Jede Beads-ID braucht "
    "daher eine eigene, vollstaendige Klammer; ein Klammerausdruck "
    "mit mehreren IDs (z. B. kommagetrennt) verknuepft kein Issue."
)

_SUFFIX = r"[0-9a-z]+(?:\.[0-9]+)*"
_ID = re.compile(rf"{re.escape(ISSUE_PREFIX)}-{_SUFFIX}")
_ID_GROUP = rf"\({_ID.pattern}\)"
_ID_GROUPS = re.compile(rf"{_ID_GROUP}(?: {_ID_GROUP})*")
_SUBJECT = re.compile(
    rf"^(?P<title>\S.*?) (?P<ids>{_ID_GROUPS.pattern})$"
)
_TRAILING_PARENS = re.compile(r"\(([^()]*)\)\s*$")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Aufruf: commit_msg <nachrichtendatei>", file=sys.stderr)
        return 2
    return check_commit_message_file(args[0])


def check_commit_message_file(path: str) -> int:
    subject = _read_subject(path)
    problem = validate_subject(subject)
    if problem is None:
        return 0
    _reject(subject, problem)
    return 1


def validate_subject(subject: str) -> str | None:
    line = subject.strip()
    if not line:
        return _repair_hint("Die Betreffzeile ist leer.")
    if _SUBJECT.fullmatch(line):
        return None
    return _repair_hint(_diagnose(line))


def _diagnose(line: str) -> str:
    trailing = _TRAILING_PARENS.search(line)
    if trailing is not None:
        return _diagnose_parentheses(trailing.group(1))
    if _ID.search(line) is not None:
        return 'Die Beads-ID steht nicht als " (<Beads-ID>)" am Ende.'
    return "Am Zeilenende fehlt die Beads-ID in Klammern."


def _diagnose_parentheses(content: str) -> str:
    if _ID.fullmatch(content):
        return 'Vor der Klammer "(" fehlt genau ein Leerzeichen.'
    if "," in content:
        return (
            f'Der Klammerausdruck "({content})" fasst mehrere IDs '
            "kommagetrennt zusammen -- bd orphans erkennt das nicht. "
            "Jede Beads-ID braucht eine eigene Klammer, z. B. "
            f"({ISSUE_PREFIX}-a) ({ISSUE_PREFIX}-b)."
        )
    if content.startswith(ISSUE_PREFIX):
        return f'Die Beads-ID "{content}" ist fehlerhaft geschrieben.'
    return (
        f'Der Klammerausdruck "({content})" am Zeilenende ist keine '
        "gueltige Beads-ID."
    )


def _repair_hint(problem: str) -> str:
    return (
        f"{problem}\n"
        'Erwartet wird: "<Titel> (<Beads-ID>)[ (<Beads-ID>)...]".\n'
        f"Beispiel: {_EXAMPLE}\n"
        f"Beispiel mit mehreren Issues: {_MULTI_EXAMPLE}\n"
        f"Kind-IDs mit Punkt sind erlaubt, z. B. "
        f"{ISSUE_PREFIX}-8dd.1.\n"
        f"{_WHY}"
    )


def _read_subject(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.readline().rstrip("\n")


def _reject(subject: str, problem: str) -> None:
    print("Commit abgelehnt: ungueltige Betreffzeile.", file=sys.stderr)
    print(f"  {subject!r}", file=sys.stderr)
    print(problem, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
