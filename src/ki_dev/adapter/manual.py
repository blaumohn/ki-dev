"""Adapter ``manual``: der Mensch als Bote zwischen ki-dev und einer
Agentensitzung.

Der Bote trägt die Eingabe, die ki-dev sonst selbst an Claude oder
Codex schicken würde, in eine Sitzung seiner Wahl und legt deren
formale Antwort zurück. Er entscheidet nichts: die Antwort durchläuft
dieselbe Prüfung wie bei jedem anderen Adapter (z. B. das JSON-Urteil
des Reviews). Entscheider ist der Mensch nur in den Zuständen der Art
``wait`` des Ablaufs, nicht hier.

Zwei Transportarten, dieselbe Übergabe (:func:`send`): der Posteingang
(:class:`Inbox`, ``ki-dev run``) legt die Eingabe als Datei ab; die
Konsole (:class:`Console`, ``ki-dev step``) gibt sie auf stdout aus.
Fehlt die Antwort noch, schreibt der Adapter die Eingabe in den
Posteingang und meldet :class:`ManualInputPending`. Das ist ein Halt des
Ausführers, kein Ablaufzustand: der Lauf bleibt im selben Zustand, die
Operation bleibt offen und läuft nach ``ki-dev run resume`` mit der
Antwort weiter. Bei der Konsole liefert der Aufruf die Antwort selbst
(Datei oder stdin, begrenzt gelesen).
"""

from __future__ import annotations

import codecs
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from ki_dev.adapter.contract import (
    ReviewRequest,
    WorkReport,
    WorkRequest,
)

NAME = "manual"
STDIN_WORD = "-"


class ManualInputPending(Exception):
    """Die Eingabe liegt bereit; die Antwort des Boten fehlt noch."""

    def __init__(self, ask: Path, answer: Path) -> None:
        self.ask = ask
        self.answer = answer
        super().__init__(
            f"Eingabe {ask} in eine Sitzung tragen, Antwort nach "
            f"{answer} legen, dann `ki-dev run resume` aufrufen"
        )


class TransportReadError(RuntimeError):
    """Antwort des Boten nicht lesbar; nennt nie den Textinhalt."""


@dataclass(frozen=True)
class Inbox:
    """Posteingang: Eingabe und Antwort als Dateien."""

    directory: Path

    def ask(self, key: str) -> Path:
        return self.directory / f"{key}.input.md"

    def answer(self, key: str) -> Path:
        return self.directory / f"{key}.answer.md"

    def receive(self, key: str) -> str | None:
        """Die Antwort, sobald sie nichtleer vorliegt."""
        path = self.answer(key)
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
        return text if text.strip() else None


@dataclass(frozen=True)
class Console:
    """Konsole: Eingabe auf stdout, Antwort aus Datei oder stdin."""

    write: Callable[[str], None]
    stdin: Callable[[], BinaryIO]

    def receive(self, source: str, limit: int, what: str) -> str:
        """Höchstens ``limit + 1`` Zeichen UTF-8 aus Datei oder stdin
        (``-``); ``what`` benennt die Eingabe in Diagnosen, die nie
        Textinhalt enthalten."""
        try:
            if source == STDIN_WORD:
                return _read_limited(self.stdin(), limit)
            # Ungepuffert: auch die Datei wird nicht über die
            # Zeichengrenze hinaus gelesen.
            with open(source, "rb", buffering=0) as stream:
                return _read_limited(stream, limit)
        except UnicodeDecodeError as exc:
            raise TransportReadError(
                f"{what} ist kein gültiges UTF-8"
            ) from exc
        except OSError as exc:
            raise TransportReadError(
                f"{what} nicht lesbar: "
                f"{exc.strerror or type(exc).__name__}"
            ) from exc


Transport = Inbox | Console


def send(transport: Transport, key: str, prompt: str) -> None:
    """Eingabe an den Boten: dieselbe Übergabe für ``ki-dev run`` und
    ``ki-dev step``, nur die Transportart unterscheidet sich."""
    if isinstance(transport, Inbox):
        transport.directory.mkdir(parents=True, exist_ok=True)
        transport.ask(key).write_text(prompt, encoding="utf-8")
    else:
        transport.write(prompt)


def _read_limited(stream: BinaryIO, limit: int) -> str:
    """Höchstens ``limit + 1`` Zeichen lesen, ohne vorauszulesen.

    Jedes Zeichen hat mindestens ein Byte; je Runde werden deshalb nur
    so viele Bytes angefordert, wie noch Zeichen fehlen. Bytes hinter
    dem Zeichen ``limit + 1`` werden weder gelesen noch dekodiert, ein
    dortiger UTF-8-Fehler verdeckt also keine Überlänge. Ohne
    Zeilenumbruch-Übersetzung: CRLF zählt als zwei Zeichen.
    """
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    parts: list[str] = []
    missing = limit + 1
    while missing > 0:
        chunk = stream.read(missing)
        if not chunk:
            parts.append(decoder.decode(b"", final=True))
            break
        part = decoder.decode(chunk)
        parts.append(part)
        missing -= len(part)
    return "".join(parts)


@dataclass(frozen=True)
class ManualRelay:
    """Bau- und Review-Rolle über einen menschlichen Boten."""

    inbox: Path
    role: str

    def work(self, request: WorkRequest) -> WorkReport:
        return WorkReport(self._relay(request))

    def review(self, request: ReviewRequest) -> str:
        return self._relay(request)

    def _relay(self, request: WorkRequest | ReviewRequest) -> str:
        prompt = request.prompt
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
        # Je Versuch eine eigene Datei: nach einem Protokollfehler
        # wartet der neue Versuch auf eine neue Antwort, statt die
        # abgewiesene erneut zu lesen.
        key = f"{request.attempt_id}-{self.role}-{digest}"
        inbox = Inbox(self.inbox)
        text = inbox.receive(key)
        if text is not None:
            return text
        send(inbox, key, prompt)
        raise ManualInputPending(inbox.ask(key), inbox.answer(key))
