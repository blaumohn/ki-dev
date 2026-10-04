"""Persistente Ack-Queue der Hook-Ereignisse in <journal>/.queue.db.

Adapter auf persist-queue SQLiteAckQueue mit JSON-Serializer. Jeder
Eintrag ist {event, issue_id, issue} oder, bei ungültiger Nutzlast,
{event, issue_id, reason} mit bereinigten Werten. Fehlgeschlagene
Einträge tragen ihren Grund in reason.

Mehrere Prozesse öffnen die Queue gleichzeitig: Hooks stellen ohne
Sperre ein, nur drain holt unter der Journal-Sperre ab. Deshalb
auto_resume=False; sonst gäbe jedes Öffnen den laufenden Eintrag eines
anderen drain wieder frei. Zurückgesetzt wird nur mit resume_unacked()
unter der Sperre. Die Zähler size/qsize hält persist-queue im Speicher
der Instanz; sie stimmen nur für eine frisch geöffnete Queue.

AUTOINCREMENT vergibt IDs nie neu, auch nicht nach prune_acked(); die
ID steht als Trailer im Commit und dient der Doppelprüfung.
persist-queue schaltet fest WAL ein (sqlbase._new_db_connection); über
virtiofs ist das ein offenes Prüfrisiko (README). Kein git, kein bd.

Erstanlage: Öffnen mehrere Prozesse eine noch fehlende Datei zugleich,
scheitert das PRAGMA journal_mode=WAL sofort mit "database is locked"
(ohne Busy-Wartezeit). Deshalb entsteht die Queue vollständig in einer
eigenen temporären Datei und wird per os.link atomar eingesetzt.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

import persistqueue.serializers.json as json_serializer
from persistqueue import SQLiteAckQueue
from persistqueue.exceptions import Empty
from persistqueue.sqlackqueue import AckStatus

QUEUE_FILE = ".queue.db"
BUSY_TIMEOUT = 5


@dataclass(frozen=True)
class Entry:
    queue_id: int
    record: dict

    @property
    def event(self) -> str:
        return self.record["event"]

    @property
    def issue_id(self) -> str:
        return self.record["issue_id"]

    @property
    def issue(self) -> dict | None:
        """None bei einem als ungültig eingestellten Eintrag."""
        return self.record.get("issue")


@dataclass(frozen=True)
class Failed:
    queue_id: int
    event: str
    issue_id: str
    reason: str


class QueueError(RuntimeError):
    """SQLite-Fehler der Queue, etwa belegt über BUSY_TIMEOUT hinaus."""


@contextmanager
def opened(journal: Path) -> Iterator[SQLiteAckQueue]:
    """Öffnet die Queue und schließt sie sicher.

    SQLite-Meldungen tragen keine Nutzlast und erscheinen im Grund.
    """
    try:
        if not (journal / QUEUE_FILE).exists():
            _create(journal)
        with closing(_connect(journal, QUEUE_FILE)) as handle:
            yield handle
    except sqlite3.Error as exc:
        raise QueueError(f"Warteschlange: {exc}") from exc


def _connect(journal: Path, file_name: str) -> SQLiteAckQueue:
    return SQLiteAckQueue(
        str(journal),
        db_file_name=file_name,
        auto_resume=False,
        timeout=BUSY_TIMEOUT,
        serializer=json_serializer,
    )


def _create(journal: Path) -> None:
    """Legt die Queue an; ein paralleler Erster gewinnt ohne Fehler.

    Beim Schließen der letzten Verbindung schreibt SQLite das WAL zurück
    und entfernt es; die eingesetzte Datei ist also vollständig.
    """
    temporary = f"{QUEUE_FILE}.{os.getpid()}.tmp"
    try:
        _connect(journal, temporary).close()
        with suppress(FileExistsError):
            os.link(journal / temporary, journal / QUEUE_FILE)
    finally:
        for suffix in ("", "-wal", "-shm"):
            (journal / f"{temporary}{suffix}").unlink(missing_ok=True)


def put(handle: SQLiteAckQueue, event: str, issue: dict) -> int:
    return handle.put(
        {"event": event, "issue_id": issue["id"], "issue": issue}
    )


def put_failed(
    handle: SQLiteAckQueue, event: str, issue_id: str, reason: str
) -> int:
    """Ungültige Nutzlast: nur bereinigte Angaben, keine Rohwerte.

    Holt ein drain den Eintrag vor ack_failed ab, erkennt er ihn am
    fehlenden issue und markiert ihn selbst.
    """
    queue_id = handle.put(
        {"event": event, "issue_id": issue_id, "reason": reason}
    )
    handle.ack_failed(id=queue_id)
    return queue_id


def resume_unacked(handle: SQLiteAckQueue) -> None:
    """Wiederanlauf: unbestätigte Einträge zurück auf bereit."""
    handle.resume_unack_tasks()


def claim_next(handle: SQLiteAckQueue) -> Entry | None:
    """Ältesten bereiten Eintrag als unbestätigt markieren und liefern.

    Nur unter der Journal-Sperre: persist-queue liest und markiert in
    zwei Schritten.
    """
    try:
        row = handle.get(block=False, raw=True)
    except Empty:
        return None
    return Entry(row["pqid"], row["data"])


def ack(handle: SQLiteAckQueue, queue_id: int) -> None:
    handle.ack(id=queue_id)


def release(handle: SQLiteAckQueue, queue_id: int) -> None:
    """Vorübergehender Fehler: Eintrag bleibt für den nächsten drain."""
    handle.nack(id=queue_id)


def ack_failed(
    handle: SQLiteAckQueue, entry: Entry, reason: str
) -> None:
    """Dauerhafter Fehler: Nutzlast und Grund bleiben, Queue läuft."""
    handle.update({**entry.record, "reason": reason}, id=entry.queue_id)
    handle.ack_failed(id=entry.queue_id)


def prune_acked(handle: SQLiteAckQueue) -> None:
    """Bestätigte Einträge löschen; die Spur liegt im Journal."""
    handle.clear_acked_data(max_delete=0, keep_latest=0)


def pending_count(handle: SQLiteAckQueue) -> int:
    """Bereite und unbestätigte Einträge; nur frisch geöffnet genau."""
    return handle.qsize() + handle.unack_count()


def failed_entries(handle: SQLiteAckQueue) -> list[Failed]:
    return [
        Failed(
            row["id"],
            row["data"]["event"],
            row["data"]["issue_id"],
            row["data"]["reason"],
        )
        for row in handle.queue()
        if str(row["status"]) == AckStatus.ack_failed
    ]
