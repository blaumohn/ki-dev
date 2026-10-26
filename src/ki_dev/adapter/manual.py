"""Adapter ``manual``: der Mensch als Bote zwischen ki-dev und einer
Agentensitzung.

Der Bote trägt die Eingabe, die ki-dev sonst selbst an Claude oder
Codex schicken würde, in eine Sitzung seiner Wahl und legt deren
formale Antwort zurück. Er entscheidet nichts: die Antwort durchläuft
dieselbe Prüfung wie bei jedem anderen Adapter (z. B. das JSON-Urteil
des Reviews). Entscheider ist der Mensch nur in den Zuständen der Art
``wait`` des Ablaufs, nicht hier.

Zwei Transporte, dieselbe Übergabe (:func:`send`), gewählt über den
Executor-Namen (``executor = "manual"`` bzw. ``"inbox"``, siehe
``adapter/executors.toml``): die Konsole (:class:`Console`) gibt die
Eingabe auf stdout aus und liest die Antwort von stdin (Ende mit
Strg-D, begrenzt gelesen); der Posteingang (:class:`Inbox`) legt sie
als Datei im Laufverzeichnis ab. Fehlt die Antwort noch (leere
Konsoleneingabe, keine Antwortdatei), meldet der Adapter
:class:`~ki_dev.adapter.contract.AnswerPending`.
"""

from __future__ import annotations

import codecs
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from ki_dev.adapter.contract import (
    AnswerPending,
    ReviewRequest,
    TurnPrompt,
    WorkReport,
    WorkRequest,
    parse_work_report,
)
from ki_dev.adapter.executors import ExecutorSpec, Measure

NAME = "manual"
# Transporte des Boten; beide messen nichts.
CONSOLE = "console"
INBOX = "inbox"
CAPABILITIES: frozenset[Measure] = frozenset()
STDIN_WORD = "-"
# Obergrenze einer Konsolenantwort; länger ist ein Transportfehler.
ANSWER_MAX_CHARS = 200_000
RESUME_HINT = "dann `ki-dev -f implement resume RUN_ID` aufrufen"


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


def _silent(_text: str) -> None:
    pass


@dataclass(frozen=True)
class Console:
    """Konsole: Eingabe auf stdout, Antwort aus Datei oder stdin;
    ``notice`` rahmt die Eingabe für den Menschen (stderr)."""

    write: Callable[[str], None]
    stdin: Callable[[], BinaryIO]
    notice: Callable[[str], None] = _silent

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
    """Eingabe an den Boten: dieselbe Übergabe für jeden Ablauf, nur
    die Transportart unterscheidet sich."""
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

    transport: Transport
    role: str
    spec: ExecutorSpec

    def work(self, request: WorkRequest) -> WorkReport:
        return parse_work_report(self._relay(request))

    def review(self, request: ReviewRequest) -> str:
        return self._relay(request)

    def ask(self, request: TurnPrompt) -> str:
        return self._ask(request.key, request.prompt)

    def _relay(self, request: WorkRequest | ReviewRequest) -> str:
        return self._ask(request.attempt_id, request.prompt)

    def _ask(self, attempt: str, prompt: str) -> str:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
        # Je Versuch eine eigene Datei: nach einem Protokollfehler
        # wartet der neue Versuch auf eine neue Antwort, statt die
        # abgewiesene erneut zu lesen.
        key = f"{attempt}-{self.role}-{digest}"
        if isinstance(self.transport, Console):
            return _ask_console(self.transport, key, prompt)
        return _ask_inbox(self.transport, key, prompt)


def _ask_console(console: Console, key: str, prompt: str) -> str:
    console.notice(f"── Eingabe {key} (stdout) ──")
    send(console, key, prompt)
    console.notice("── formale Antwort einfügen, Ende mit Strg-D ──")
    text = console.receive(STDIN_WORD, ANSWER_MAX_CHARS, "Antwort")
    if len(text) > ANSWER_MAX_CHARS:
        raise TransportReadError(
            f"Antwort länger als {ANSWER_MAX_CHARS} Zeichen"
        )
    if not text.strip():
        raise AnswerPending(
            f"keine Antwort zu {key}; {RESUME_HINT}"
        )
    return text


def _ask_inbox(inbox: Inbox, key: str, prompt: str) -> str:
    text = inbox.receive(key)
    if text is not None:
        return text
    send(inbox, key, prompt)
    raise AnswerPending(
        f"Eingabe {inbox.ask(key)} in eine Sitzung tragen, Antwort "
        f"nach {inbox.answer(key)} legen, {RESUME_HINT}"
    )
