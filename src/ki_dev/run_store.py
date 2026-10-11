"""Abbruchsichere, laufgebundene Nachweise eines Bauablaufs."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, cast

RECORD_FILE = "record.json"


class RunStoreError(RuntimeError):
    """Persistierte Laufdaten fehlen oder widersprechen sich."""


@dataclass(frozen=True)
class RunStore:
    """Kleine atomare Ablage eines Laufs: Datensatz und Nachweise."""

    root: Path
    run_id: str

    def __post_init__(self) -> None:
        if (
            not self.run_id.strip()
            or Path(self.run_id).name != self.run_id
        ):
            raise ValueError(
                "run_id muss ein einzelner nichtleerer Pfadname sein"
            )

    @property
    def run_dir(self) -> Path:
        return self.root / self.run_id

    @property
    def record_path(self) -> Path:
        """Datensatz des Laufs: Maschinenstände und Laufdaten."""
        return self.run_dir / RECORD_FILE

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "manifest.json"

    def initialize(self, manifest: dict[str, object]) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._write_once(self.manifest_path, manifest)

    def load_manifest(self) -> dict[str, object]:
        value = self._load_json(self.manifest_path)
        if not isinstance(value, dict):
            raise RunStoreError("manifest.json ist kein JSON-Objekt")
        return value

    def save_record(self, value: object) -> None:
        """Datensatz atomar ersetzen (je Schritt)."""
        replace_json(self.record_path, value)

    def load_record(self) -> object | None:
        """Gespeicherter Datensatz; ``None``, wenn der Lauf fehlt."""
        if not self.record_path.exists():
            return None
        return self._load_json(self.record_path)

    def write_artifact(self, operation_id: str, value: object) -> None:
        path = self.run_dir / "artifacts" / f"{operation_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_once(path, value)

    def load_artifact(self, operation_id: str) -> object | None:
        path = self.run_dir / "artifacts" / f"{operation_id}.json"
        if not path.exists():
            return None
        return self._load_json(path)

    def write_message(self, message_id: str, value: object) -> None:
        path = self.run_dir / "messages" / f"{message_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_once(path, value)

    def write_handoff(self, handoff_id: str, value: object) -> None:
        path = self.run_dir / "handoff" / f"{handoff_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_once(path, value)

    def load_messages(self) -> list[dict[str, object]]:
        """Persistierte Review-Nachrichten in Entstehungsreihenfolge.

        Nachrichtendateinamen kodieren Runde und Sequenz
        (``r0002-review-a0000.json``); die Sortierung nach Dateiname
        liefert damit die tatsaechliche zeitliche Reihenfolge.
        """
        directory = self.run_dir / "messages"
        if not directory.exists():
            return []
        messages: list[dict[str, object]] = []
        for path in sorted(directory.glob("*.json")):
            value = self._load_json(path)
            if not isinstance(value, dict):
                raise RunStoreError(
                    f"Nachricht ist kein Objekt: {path}"
                )
            messages.append(cast(dict[str, object], value))
        return messages

    def append_event(self, record: dict[str, object]) -> bool:
        """Zeile an ``events.jsonl`` anhängen, sofern ``line`` neuer
        ist als die letzte; ``False`` heißt: schon geschrieben
        (Wiederholung nach Absturz)."""
        path = self.run_dir / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            lines = handle.read().splitlines()
            last = json.loads(lines[-1])["line"] if lines else 0
            if cast(int, record["line"]) <= last:
                return False
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return True

    def load_events(self) -> list[dict[str, object]]:
        path = self.run_dir / "events.jsonl"
        if not path.exists():
            return []
        return [
            cast(dict[str, object], json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
        ]

    def acquire_writer(self) -> IO[str]:
        """Einziger Schreiber dieses Laufs; frei mit ``close()`` des
        Rückgabewerts (auch beim Prozessende)."""
        self.root.mkdir(parents=True, exist_ok=True)
        handle = (self.root / f".{self.run_id}.lock").open("a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise RunStoreError(
                f"Lauf {self.run_id} wird bereits von einem anderen "
                "Aufruf gefahren"
            ) from None
        return handle

    @contextmanager
    def usage_lock(self):
        """One lock for reservations, results and evidence across
        local runs."""
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / ".usage.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def write_usage(self, call_id: str, value: dict) -> None:
        if (
            not call_id
            or Path(call_id).name != call_id
            or call_id in {".", ".."}
        ):
            raise RunStoreError("ungueltiger Aufrufbezug")
        digest = hashlib.sha256(_canonical_json(value)).hexdigest()
        self._write_once(
            self.run_dir / "usage" / call_id / f"{digest}.json", value
        )

    def load_usage(self, call_id: str) -> list[dict]:
        return [self._load_json(path) for path in sorted(
            (self.run_dir / "usage" / call_id).glob("*.json")
        )]

    def _write_once(self, path: Path, value: object) -> None:
        encoded = _canonical_json(value)
        if path.exists():
            if path.read_bytes() != encoded:
                raise RunStoreError(
                    "persistierter Eintrag widerspricht Wiederholung: "
                    f"{path}"
                )
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            # Atomic create-if-absent: competing writers must never
            # overwrite an immutable artifact after both passed the
            # existence check.
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != encoded:
                    raise RunStoreError(
                        "persistierter Eintrag widerspricht "
                        f"Wiederholung: {path}"
                    ) from None
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _load_json(path: Path) -> object:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RunStoreError(f"Laufnachweis fehlt: {path}") from exc
        except json.JSONDecodeError as exc:
            raise RunStoreError(
                f"ungueltiger Laufnachweis: {path}"
            ) from exc


def replace_json(path: Path, value: object) -> None:
    """``value`` als JSON atomar nach ``path`` schreiben: temporäre
    Datei im selben Verzeichnis, ``fsync``, ``os.replace``. Ein Abbruch
    davor lässt den bisherigen Inhalt stehen."""
    encoded = _canonical_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _canonical_json(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise RunStoreError(
            "Laufnachweis ist nicht JSON-serialisierbar"
        ) from exc
    return (text + "\n").encode()
