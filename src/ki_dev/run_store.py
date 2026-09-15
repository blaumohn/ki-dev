"""Abbruchsichere, laufgebundene Nachweise fuer den Bau--Review-Loop."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


class RunStoreError(RuntimeError):
    """Persistierte Laufdaten fehlen oder widersprechen sich."""


@dataclass(frozen=True)
class RunStore:
    """Kleine atomare Ablage neben dem LangGraph-Checkpoint."""

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
    def checkpoint_path(self) -> Path:
        return self.run_dir / "checkpoints.sqlite"

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
            os.replace(temporary, path)
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
