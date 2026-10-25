"""Kommentar-Journal: bd-Kommentare auslagern, abschließen, prüfen.

Zwischenlösung bis ki-dev-ablauf-dg9e. ``comments export`` schreibt je
Vorgang mit Kommentaren ``comments/<ID>.json`` ins Journal, committet
und löscht erst danach die Kommentare in bd
(scripts/bd-clear-comments.sh). Jeder Eintrag trägt den Einbau-Zustand
open oder incorporated; nur ``mark-incorporated`` schließt ab. ``lint``
meldet Kommentare in bd und vertragswidrige (von Hand bearbeitete)
Dateien. Ausgaben nennen IDs und Anzahlen, keine Kommentartexte.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path

from plumbum import local
from plumbum.commands.processes import (
    CommandNotFound,
    ProcessExecutionError,
    ProcessTimedOut,
)

from ki_dev.beads_journal.comments_contract import (
    COMMAND,
    COMMENTS,
    FIELDS,
    INCORPORATED,
    LABEL,
    OPEN,
    bd_comments,
    comment_file,
    labelled,
    load,
    open_count,
)
from ki_dev.beads_journal.contract import PayloadError, is_issue_id
from ki_dev.beads_journal.git import GitError, run_git
from ki_dev.beads_journal.journal import (
    NO_AUTO_MAINTENANCE,
    JournalError,
    is_active,
    locked,
    restore_file,
    write_atomic,
)

README = "README.md"
CLEAR_SCRIPT = Path("scripts/bd-clear-comments.sh")
CLEAR_TIMEOUT = 120
BD_TIMEOUT = 30
_README_TEXT = (
    files(__package__)
    .joinpath("comments-readme.md")
    .read_text(encoding="utf-8")
)


def add_parser(commands: argparse._SubParsersAction) -> None:
    parser = commands.add_parser(
        "comments",
        help="bd-Kommentare ins Journal auslagern und abschließen",
    )
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser(
        "export",
        help="Kommentare aus bd ins Journal committen, dann in bd "
        "löschen",
    )
    mark = actions.add_parser(
        "mark-incorporated",
        help="ausgelagerte Einträge eines Vorgangs als eingebaut "
        "abschließen",
    )
    mark.add_argument("issue_id")
    mark.add_argument(
        "comment_ids", nargs="*", help="Vorgabe: alle Einträge"
    )
    actions.add_parser(
        "lint",
        help="Exit 1 bei Kommentaren in bd oder vertragswidriger "
        "Datei; offene Einträge als Hinweis",
    )


def run(
    root: Path,
    journal: Path,
    arguments: argparse.Namespace,
    export_rows: Callable[[Path], list[dict]],
    bd_program: str,
) -> int:
    if not is_active(journal):
        raise JournalError(
            f"{journal}: nicht eingerichtet (kein Marker); zuerst: "
            ".venv/bin/python -m ki_dev.beads_journal init"
        )
    rows = export_rows(root)
    if arguments.action == "export":
        return run_export(root, journal, rows, bd_program)
    if arguments.action == "mark-incorporated":
        return run_mark(
            root,
            journal,
            rows,
            bd_program,
            (arguments.issue_id, arguments.comment_ids),
        )
    return run_lint(journal, rows)


def run_export(
    root: Path, journal: Path, rows: list[dict], bd_program: str
) -> int:
    """Erst committen, dann Label setzen und in bd löschen."""
    pending = bd_comments(rows)
    with locked(journal):
        _write_readme(journal)
        added = {
            issue_id: _store(journal, issue_id, entries)
            for issue_id, entries in pending.items()
        }
    for issue_id in sorted(pending):
        print(
            f"{issue_id}: {len(pending[issue_id])} in bd, "
            f"{added[issue_id]} neu ausgelagert"
        )
    unlabelled = sorted(set(pending) - labelled(rows))
    if unlabelled:
        _external(
            root,
            [bd_program, "label", "add", *unlabelled, LABEL],
            BD_TIMEOUT,
        )
    if pending:
        _clear(root, sorted(pending))
    print(f"In bd gelöscht: {len(pending)} Vorgänge")
    return _report_files(journal)


def run_mark(
    root: Path,
    journal: Path,
    rows: list[dict],
    bd_program: str,
    target: tuple[str, list[str]],
) -> int:
    """Prüft vor dem Schreiben; Label erst ohne offene Einträge."""
    issue_id, comment_ids = target
    path = _checked_target(journal, rows, issue_id)
    still_open = _incorporate_file(journal, path, comment_ids)
    if not still_open and issue_id in labelled(rows):
        _external(
            root,
            [bd_program, "label", "remove", issue_id, LABEL],
            BD_TIMEOUT,
        )
    if still_open:
        print(_open_hint(issue_id))
    return 0


def run_lint(journal: Path, rows: list[dict]) -> int:
    remaining = bd_comments(rows)
    for issue_id in sorted(remaining):
        count = len(remaining[issue_id])
        print(f"{issue_id}: {count} Kommentare in bd")
    if remaining:
        print(f"Auslagern: {COMMAND} export")
    broken = _report_files(journal)
    return 1 if remaining or broken else 0


def _checked_target(
    journal: Path, rows: list[dict], issue_id: str
) -> Path:
    if not is_issue_id(issue_id):
        raise JournalError(
            "ungültige Vorgangs-ID; offene Vorgänge: "
            f"bd list --label {LABEL}"
        )
    remaining = bd_comments(rows).get(issue_id)
    if remaining:
        raise JournalError(
            f"{issue_id}: bd hat noch {len(remaining)} Kommentare; "
            f"zuerst: {COMMAND} export"
        )
    path = comment_file(journal, issue_id)
    if not path.is_file():
        raise JournalError(
            f"{COMMENTS}/{issue_id}.json fehlt; zuerst: "
            f"{COMMAND} export"
        )
    return path


def _incorporate_file(
    journal: Path, path: Path, comment_ids: list[str]
) -> int:
    """Setzt Einträge auf incorporated; Zahl der noch offenen."""
    issue_id = path.stem
    with locked(journal):
        record = load(journal, path)
        changed = _incorporate(record, issue_id, comment_ids)
        if changed:
            _save(
                journal,
                path,
                record,
                f"comments {issue_id}: {changed} eingebaut",
            )
    still_open = open_count(record)
    print(f"{issue_id}: {changed} eingebaut, {still_open} offen")
    return still_open


def _incorporate(
    record: dict, issue_id: str, comment_ids: list[str]
) -> int:
    entries = record["comments"]
    unknown = sorted(
        set(comment_ids) - {entry["id"] for entry in entries}
    )
    if unknown:
        raise JournalError(
            f"{issue_id}: Kommentar-ID unbekannt: "
            f"{', '.join(unknown)}; alle Einträge: "
            f"{COMMAND} mark-incorporated {issue_id}"
        )
    selected = set(comment_ids) or {entry["id"] for entry in entries}
    changed = 0
    for entry in entries:
        if entry["id"] in selected and entry["state"] != INCORPORATED:
            entry["state"] = INCORPORATED
            changed += 1
    return changed


def _store(journal: Path, issue_id: str, entries: list[dict]) -> int:
    """Hängt unbekannte Kommentare als open an; Bestehendes bleibt."""
    path = comment_file(journal, issue_id)
    record = (
        load(journal, path)
        if path.exists()
        else {"issue_id": issue_id, "comments": []}
    )
    known = {entry["id"] for entry in record["comments"]}
    added = 0
    for entry in entries:
        if entry["id"] not in known:
            known.add(entry["id"])
            record["comments"].append(
                {**{key: entry[key] for key in FIELDS}, "state": OPEN}
            )
            added += 1
    if added:
        _save(
            journal,
            path,
            record,
            f"comments {issue_id}: {added} ausgelagert",
        )
    return added


def _save(
    journal: Path, path: Path, record: dict, message: str
) -> None:
    text = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    _commit_file(journal, path, text, message)


def _write_readme(journal: Path) -> None:
    path = journal / COMMENTS / README
    if path.is_file() and path.read_text(encoding="utf-8") == (
        _README_TEXT
    ):
        return
    _commit_file(journal, path, _README_TEXT, f"{COMMENTS}: {README}")


def _commit_file(
    journal: Path, path: Path, text: str, message: str
) -> None:
    """Schreibt und committet nur diesen Pfad; Fehler nimmt ihn zurück.

    Ein Rest im Arbeitsbaum ließe den nächsten export glauben, die
    Kommentare seien schon committet, und sie in bd löschen.
    """
    path.parent.mkdir(exist_ok=True)
    previous = (
        path.read_text(encoding="utf-8") if path.exists() else None
    )
    relative = str(path.relative_to(journal))
    try:
        write_atomic(path, text)
        run_git(journal, "add", "--", relative)
        run_git(
            journal,
            "commit",
            "--no-verify",
            "-q",
            "-m",
            message,
            "--",
            relative,
            config=NO_AUTO_MAINTENANCE,
        )
    except (GitError, OSError):
        restore_file(journal, path, previous)
        raise


def _clear(root: Path, issue_ids: list[str]) -> None:
    try:
        _external(
            root, [str(root / CLEAR_SCRIPT), *issue_ids], CLEAR_TIMEOUT
        )
    except JournalError as exc:
        raise JournalError(
            f"Löschen in bd fehlgeschlagen ({exc}) für "
            f"{', '.join(issue_ids)}; Journal-Commits bleiben. "
            f"Erneut: {COMMAND} export"
        ) from None


def _external(root: Path, command: list[str], timeout: int) -> None:
    """Startet command im Projekt-Repo; Meldung ohne Ausgabe."""
    program = Path(command[0]).name
    label = f"{program} {command[1]}" if program == "bd" else program
    try:
        with local.cwd(root):
            local[command[0]][command[1:]].run(
                retcode=0, timeout=timeout
            )
    except CommandNotFound as exc:
        raise JournalError(f"{label}: nicht gefunden") from exc
    except ProcessTimedOut as exc:
        raise JournalError(f"{label}: über {timeout} s") from exc
    except ProcessExecutionError as exc:
        raise JournalError(f"{label}: Exit {exc.retcode}") from exc


def _report_files(journal: Path) -> int:
    """Offene Einträge als Hinweis; Zahl vertragswidriger Dateien."""
    broken = 0
    for path in sorted((journal / COMMENTS).glob("*.json")):
        try:
            record = load(journal, path)
        except PayloadError as exc:
            print(exc)
            broken += 1
            continue
        if open_count(record):
            print(
                f"{path.stem}: {open_count(record)} offen. "
                + _open_hint(path.stem)
            )
    return broken


def _open_hint(issue_id: str) -> str:
    return (
        "Einbauen nach Bedarf, dann: "
        f"{COMMAND} mark-incorporated {issue_id}"
    )
