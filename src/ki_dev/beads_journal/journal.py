"""Journal-Repo: Issue-Dateien schreiben und je Ereignis committen.

Alle Schreibzugriffe laufen unter einer flock-Sperre auf
<journal>/.lock; das Betriebssystem gibt sie frei, wenn bd den Hook nach
seiner Frist tötet. Jeder Commit trägt den Trailer Journal-Event mit
der Queue-ID seines Ereignisses (Ablauf in drain.py). Eine verspätete
Nutzlast (updated_at in ganzen Sekunden älter als in
der Datei) überschreibt nichts und ergibt einen leeren Commit mit
Vermerk.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock, Timeout

from ki_dev.beads_journal.contract import PayloadError, check_issue
from ki_dev.beads_journal.git import GitError, run_git
from ki_dev.beads_journal.queue import QUEUE_FILE
from ki_dev.beads_journal.timestamps import timestamp

MARKER = ".beads-journal"
ISSUES = "issues"
LOCK = ".lock"
ERRORS_LOG = ".errors.log"
LOCK_TIMEOUT = 5
TRAILER = "Journal-Event"
# git commit stößt sonst gc --auto bzw. maintenance run --auto an,
# standardmäßig losgelöst (gc.autoDetach). Diese Wartung überlebte den
# Hook und die Journal-Sperre; der Wiederanlauf hielte ihre noch aktive
# packed-refs.lock für verwaist und löschte sie.
NO_AUTO_MAINTENANCE = {"gc.auto": "0", "maintenance.auto": "false"}
_GITIGNORE = f"{LOCK}\n{ERRORS_LOG}\n{QUEUE_FILE}*\n{ISSUES}/.*.tmp\n"
_MARKER_TEXT = "Beads-Journal von ki-dev; siehe README.md.\n"
_README = """\
# Beads-Journal

Je Änderung an einem Beads-Vorgang ein Commit, geschrieben von den
bd-Hooks on_create, on_update und on_close. `issues/<ID>.json` enthält
die letzte Hook-Nutzlast des Vorgangs. Löschungen und Kommentartexte
fehlen.

Sitzungsangaben in lesbaren Quellen-Beads sind interne Hinweise,
z. B. `Claude-Sitzung …b1d0d`. Neue Quellen-Beads verwenden einen unter
den vorhandenen Quellen-Sitzungen eindeutigen UUID-Suffix ab fünf
Hex-Zeichen. Die Transkripte sind dadurch nicht öffentlich archiviert.
Technische `source_key`-Werte und konkrete Dateipfade behalten ihre
vollständige ID. Vor Veröffentlichung auch die Journal-Historie prüfen:
ältere Revisionen können vollständige IDs enthalten.

Commit-Nachricht: `<Ereignis> <ID>: <Titel> [<Status>]`; ` (verspätet)`
markiert eine ältere Nutzlast, die die Datei nicht überschrieben hat.
Zeilenumbrüche in Titel und Status werden im Betreff zu Leerzeichen;
die Issue-Datei behält den Originaltext.

```bash
# offene Vorgänge als Tabelle
jq -r 'select(.status != "closed") | [.id, .status, .title] | @tsv' \\
  issues/*.json

# Verlauf eines Vorgangs
git log -p -- issues/<ID>.json

# Ereignisse der letzten Woche
git log --since=1.week --format='%ad %s' --date=short
```

Einrichtung im Projekt-Repo: `python -m ki_dev.beads_journal init`
(optional `--path P`); `status` arbeitet zuerst die Warteschlange ab
und zeigt dann Ort, Commits, offene und fehlgeschlagene Einträge sowie
die Fehlerzahl; `drain` arbeitet nur ab. Ohne `.beads-journal` bleibt
der Hook inaktiv. Voraussetzung: git >= 2.32 (`commit --trailer`).

Jeder Hook legt sein Ereignis zuerst in die Warteschlange `.queue.db`
und arbeitet sie dann unter der Sperre `.lock` ab. Die Commits folgen
der Eingangsreihenfolge der Warteschlange; der Trailer
`Journal-Event: <Queue-ID>` verhindert Doppel-Commits nach einem
Abbruch. Ist die Sperre belegt (5 s), bleibt das Ereignis in der
Warteschlange; der Halter oder der nächste Hook bzw. `status`
committet es. Nach einem Abbruch (bd beendet Hooks nach 10 s) setzt der
nächste Lauf unbestätigte Einträge zurück und entfernt verwaiste
Sperrdateien (`.git/index.lock`, `.git/HEAD.lock`,
`.git/packed-refs.lock`, `.git/refs/**/*.lock`); automatische
git-Wartung ist für Journal-Commits abgeschaltet, damit keine
losgelöste Wartung eine dieser Sperren noch hält. Ungültige
Nutzlasten werden als fehlgeschlagen vermerkt, ohne Rohwerte;
Git-Fehler lassen das Ereignis in der Warteschlange. Gründe stehen in
`.errors.log`, mit `#<Queue-ID>` wie in `status`. `.queue.db` gehört
zum Journal: Wer sie löscht, verliert offene Einträge, und neue
Queue-IDs gelten fälschlich als schon committet.

"Verspätet" zählt in ganzen Sekunden von `updated_at`; innerhalb
derselben Sekunde bleiben Vertauschungen unerkannt.

Kein gleichzeitiger bd-Betrieb auf Host und Container: flock-Sperren
über virtiofs sind dafür unzuverlässig. Die Warteschlange
(persist-queue) läuft fest im WAL-Modus; nach einem Abbruch bleiben
`.queue.db-wal` und `-shm` liegen. Ob ein anschließender Wechsel
zwischen Host und Container über virtiofs sauber weiterläuft, ist
ungeprüft. Keine manuellen
Git-Schreibzugriffe im Journal, solange Hooks laufen können. Das
Journal wird lokal geführt; ein Push ist ein getrennter Schritt.

Vor einer Veröffentlichung:

```bash
# alle Revisionen prüfen; Exit 1 bei Befunden
python -m ki_dev.beads_journal audit
# index.md schreiben und committen
python -m ki_dev.beads_journal index
```

`audit` prüft Commit-Nachrichten und jede je eingefügte Zeile auf
Verweise in lokale Ablagen (`.local`), absolute Pfade, Mailadressen
und Zugangsdaten und nennt nur Revision, Datei und Kategorie.
Löschen oder Ignorieren bereinigt keine Historie; ob neu begonnen,
umgeschrieben oder veröffentlicht wird, entscheidet der Mensch.
`index` schreibt `index.md` (eine Zeile je Vorgang, nach ID sortiert,
mit Stand und Code-Commit), gleicht gegen `bd export` ab und
kennzeichnet Dateien, deren Vorgang in der Datenbank fehlt, mit
„nicht in DB“. Die Datenbank bleibt unverändert; nichts wird
zurückimportiert.
"""


class JournalError(RuntimeError):
    """Journal nicht beschreibbar: Sperre fehlt oder Ordner belegt."""


class LockBusy(JournalError):
    """Sperre belegt; offene Einträge bleiben in der Warteschlange."""


def is_active(journal: Path) -> bool:
    return (journal / MARKER).is_file()


def initialize(
    journal: Path, issues: list[dict], identity: dict[str, str]
) -> None:
    """Legt das Journal an und committet einmalig den bd-Export.

    identity sind git-config-Schlüssel (user.name, user.email) für die
    Commits im Journal; der Marker entsteht zuletzt im selben Commit.
    """
    if is_active(journal):
        raise JournalError(f"{journal} ist bereits eingerichtet")
    if journal.exists() and any(journal.iterdir()):
        raise JournalError(
            f"{journal} ist nicht leer (Rest eines Abbruchs?); "
            "leeren oder anderen --path wählen"
        )
    (journal / ISSUES).mkdir(parents=True, exist_ok=True)
    with locked(journal):
        run_git(journal, "init", "-q", "-b", "main")
        for key, value in identity.items():
            run_git(journal, "config", key, value)
        (journal / ".gitignore").write_text(
            _GITIGNORE, encoding="utf-8"
        )
        (journal / "README.md").write_text(_README, encoding="utf-8")
        for issue in issues:
            _write_atomic(
                _issue_file(journal, issue["id"]), _normalize(issue)
            )
        (journal / MARKER).write_text(_MARKER_TEXT, encoding="utf-8")
        try:
            run_git(journal, "add", "-A")
            run_git(
                journal,
                "commit",
                "--no-verify",
                "-q",
                "-m",
                f"init: {len(issues)} Issues aus bd export",
                config=NO_AUTO_MAINTENANCE,
            )
        except (GitError, OSError):
            (journal / MARKER).unlink()
            raise


def log_error(
    journal: Path,
    event: str,
    issue_id: str,
    reason: str,
    queue_id: int | None = None,
) -> None:
    """Hängt eine Zeile an .errors.log; ohne Rohwerte der Nutzlast.

    Mit Queue-ID beginnt der Grund mit #<ID>, wie in status.
    """
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    entry = "" if queue_id is None else f"#{queue_id} "
    line = f"{stamp} {entry}{event} {issue_id}: {reason}\n"
    with (journal / ERRORS_LOG).open("a", encoding="utf-8") as log:
        log.write(line)


def io_error(error: OSError) -> JournalError:
    """Dateifehler ohne Pfad und Meldungstext (tragen evtl. Inhalte)."""
    return JournalError(
        f"Dateizugriff fehlgeschlagen (errno={error.errno})"
    )


@contextmanager
def locked(journal: Path) -> Iterator[None]:
    lock = FileLock(journal / LOCK, timeout=LOCK_TIMEOUT)
    try:
        lock.acquire()
    except Timeout as exc:
        raise LockBusy(
            f"Sperre nicht binnen {LOCK_TIMEOUT} s erhalten"
        ) from exc
    try:
        yield
    finally:
        lock.release()


def commit_event(
    journal: Path, event: str, issue: dict, queue_id: int
) -> None:
    """Schreibt issues/<ID>.json und committet mit Queue-ID-Trailer.

    Nur unter locked() aufrufen. Ein Fehler nimmt die Datei zurück,
    damit sie nicht in den nächsten Commit gerät.
    """
    target = _issue_file(journal, issue["id"])
    late = _is_late(issue, target)
    previous = (
        target.read_text(encoding="utf-8") if target.exists() else None
    )
    try:
        if not late:
            _write_atomic(target, _normalize(issue))
            run_git(
                journal, "add", "--", str(target.relative_to(journal))
            )
        run_git(
            journal,
            "commit",
            "--allow-empty",
            "--no-verify",
            "-q",
            "-m",
            commit_message(event, issue, late),
            "--trailer",
            f"{TRAILER}: {queue_id}",
            config=NO_AUTO_MAINTENANCE,
        )
    except (GitError, OSError):
        if not late:
            # Verworfenes Ereignis nicht in den nächsten Commit tragen.
            _restore_issue(journal, target, previous)
        raise


def _restore_issue(
    journal: Path, target: Path, previous: str | None
) -> None:
    if previous is None:
        target.unlink(missing_ok=True)
    else:
        _write_atomic(target, previous)
    run_git(
        journal,
        "reset",
        "-q",
        "HEAD",
        "--",
        str(target.relative_to(journal)),
    )


def commit_message(event: str, issue: dict, late: bool) -> str:
    """Einzeiliger Betreff; issues/<ID>.json behält den Originaltext.

    Ein Zeilenumbruch in Titel oder Status ergäbe Absätze, die git als
    Trailer liest; ein eingeschleustes "Journal-Event: 2" ließe die
    Doppelprüfung den echten Eintrag 2 ohne Commit bestätigen.
    """
    title = _one_line(issue["title"])
    message = (
        f"{event} {issue['id']}: {title} [{_one_line(issue['status'])}]"
    )
    return f"{message} (verspätet)" if late else message


def _one_line(text: str) -> str:
    return " ".join(
        part.strip() for part in text.splitlines() if part.strip()
    )


def _is_late(issue: dict, target: Path) -> bool:
    if not target.is_file():
        return False
    try:
        stored = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PayloadError("gespeichertes Issue: kein JSON") from exc
    check_issue(stored, ["gespeichertes Issue"])
    return _whole_second(issue["updated_at"]) < _whole_second(
        stored["updated_at"]
    )


def _whole_second(value: str) -> datetime:
    """updated_at ohne Sekundenbruchteile.

    Nur die create-Nutzlast trägt Bruchteile aus dem Speicher; spätere
    Ereignisse liefern die Sekunde aus der DB. Fehlende Bruchteile
    dürfen kein Ereignis verspätet machen; innerhalb derselben Sekunde
    entscheidet die Sperrreihenfolge.
    """
    seconds, _ = timestamp(value)
    return seconds


def _issue_file(journal: Path, issue_id: str) -> Path:
    return journal / ISSUES / f"{issue_id}.json"


def _normalize(issue: dict) -> str:
    return (
        json.dumps(issue, sort_keys=True, indent=2, ensure_ascii=False)
        + "\n"
    )


def _write_atomic(target: Path, text: str) -> None:
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
