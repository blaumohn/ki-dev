"""Nächste Nachricht nach einer Korrektur (``handoff --next-turn``).

Reine Empfängerwahl und Rendering plus die zwei kleinen I/O-Grenzen
dieser Funktion: die Grenze ``feedback_max_chars`` aus
``pyproject.toml`` und die ausdrücklich angegebene Rückmeldung (Datei
oder stdin). Der Vorlauf selbst bleibt in ``handoff_preflight``; die
Ablaufsteuerung steht in ``handoff_cli``. Keine Dateiablage, kein
Zustand zwischen Aufrufen, keine Beads-Notizen.
"""

from __future__ import annotations

import codecs
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from ki_dev.config_sources import ConfigSource
from ki_dev.handoff import (
    NONEMPTY_TEXT_SCHEMA,
    HandoffIssue,
    ReviewTarget,
)
from ki_dev.handoff_preflight import (
    CONFIG_FILE,
    PreflightConfigError,
    PreflightReport,
    read_toml,
    render_report_lines,
)

CONFIG_TABLE = "tool.ki-dev.handoff"
CONFIG_KEY = "feedback_max_chars"
DEFAULT_FEEDBACK_MAX_CHARS = 600
CONFIG_SOURCE = ConfigSource(
    "handoff --next-turn", str(CONFIG_FILE), CONFIG_TABLE, CONFIG_FILE
)

STDIN_WORD = "-"

_TABLE_KEYS = tuple(CONFIG_TABLE.split("."))

_KEY_PATH = (*_TABLE_KEYS, CONFIG_KEY)
_LIMIT_RULE = "muss eine positive ganze Zahl sein"


def _nested_schema(keys: tuple[str, ...]) -> dict:
    """Optionale, verschachtelte Tabellen bis zum Grenzwert; jede
    vorhandene Ebene muss eine Tabelle sein."""
    if not keys:
        return {"type": "integer", "exclusiveMinimum": 0}
    return {
        "type": "object",
        "properties": {keys[0]: _nested_schema(keys[1:])},
    }


_CONFIG_SCHEMA = _nested_schema(_KEY_PATH)


class NextTurnInputError(ValueError):
    """Aufruf, Konfiguration oder Rückmeldung ungültig (Exit 2)."""


class FeedbackReadError(RuntimeError):
    """Rückmeldung nicht lesbar (Exit 1); nennt nie den Textinhalt."""


def load_feedback_max_chars(project_root: Path) -> int:
    """Grenze für die Rückmeldung; fehlende Angabe ist der Standard.

    Eine fehlende Datei, Tabelle oder ein fehlender Schlüssel ist keine
    Konfiguration im Sinne eines Fehlers (das Ziel braucht dann keine
    ``pyproject.toml``); ein vorhandener, aber ungültiger Wert, eine
    falsch typisierte Tabelle oder ungültiges TOML wird abgelehnt.
    """
    path = project_root / CONFIG_FILE
    if not path.exists():
        return DEFAULT_FEEDBACK_MAX_CHARS
    try:
        document = read_toml(path)
    except PreflightConfigError as exc:
        raise NextTurnInputError(
            f"Konfiguration ungültig: {exc}"
        ) from exc
    try:
        Draft202012Validator(_CONFIG_SCHEMA).validate(document)
    except ValidationError as exc:
        raise NextTurnInputError(
            f"Konfiguration ungültig: {_diagnosis(exc)}"
        ) from exc
    table: object = document
    for key in (*_TABLE_KEYS, CONFIG_KEY):
        if not isinstance(table, dict) or key not in table:
            return DEFAULT_FEEDBACK_MAX_CHARS
        table = table[key]
    # jsonschema lässt 600.0 als integer zu; "ganze Zahl" meint hier
    # den TOML-Typ Integer.
    if isinstance(table, float):
        raise NextTurnInputError(
            f"Konfiguration ungültig: {_diagnosis_path(_KEY_PATH)} "
            f"{_LIMIT_RULE}"
        )
    return cast(int, table)


def _diagnosis(error: ValidationError) -> str:
    """Feldpfad und feste Regelbeschreibung, nie der Rohwert."""
    path = tuple(str(part) for part in error.absolute_path)
    if path == _KEY_PATH:
        return f"{_diagnosis_path(path)} {_LIMIT_RULE}"
    return f"{_diagnosis_path(path)} muss eine Tabelle sein"


def _diagnosis_path(path: tuple[str, ...]) -> str:
    return ".".join(path)


def read_feedback(
    source: str, limit: int, stdin: Callable[[], BinaryIO]
) -> str:
    """Rückmeldung aus Datei oder stdin (``-``) lesen und prüfen.

    Datei und stdin laufen durch denselben UTF-8-Leser, der höchstens
    ``limit + 1`` Zeichen liest und dekodiert (``_read_limited``).
    Zeichen zählen unverändert (auch Leerraum und Zeilenumbrüche); es
    wird nie gekürzt. ``stdin`` ist ein Lieferant, damit ohne diese
    Angabe kein stdin angefasst wird.
    """
    try:
        if source == STDIN_WORD:
            text = _read_limited(stdin(), limit)
        else:
            # Ungepuffert: auch die Datei wird nicht über die
            # Zeichengrenze hinaus gelesen.
            with open(source, "rb", buffering=0) as stream:
                text = _read_limited(stream, limit)
    except UnicodeDecodeError as exc:
        raise FeedbackReadError(
            "Rückmeldung ist kein gültiges UTF-8"
        ) from exc
    except OSError as exc:
        raise FeedbackReadError(
            "Rückmeldung nicht lesbar: "
            f"{exc.strerror or type(exc).__name__}"
        ) from exc
    _check_feedback(text, limit)
    return text


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


def _check_feedback(text: str, limit: int) -> None:
    """Leer/Leerraum und Überlänge deklarativ prüfen (Diagnose ohne
    Rohwert)."""
    schema = {**NONEMPTY_TEXT_SCHEMA, "maxLength": limit}
    for error in Draft202012Validator(schema).iter_errors(text):
        if error.validator == "maxLength":
            raise NextTurnInputError(
                f"Rückmeldung überschreitet {limit} Zeichen "
                f"({CONFIG_TABLE}.{CONFIG_KEY}); keine Kürzung, bitte "
                "kürzen"
            )
        raise NextTurnInputError("Rückmeldung ist leer")


_RE_REVIEW_FOCUS = {
    ReviewTarget.BUILD: (
        "Prüfe die Korrekturen und die davon betroffenen Kriterien "
        "samt Regressionen fachlich anhand von Diff und Prüfbericht. "
        "Grüne Tests sind kein Review-PASS."
    ),
    ReviewTarget.MAP: (
        "Prüfe fachlich, ob die Korrekturen die früheren Befunde "
        "beheben und bei Quellenabdeckung, Fundstellen und bewahrten "
        "Einschränkungen keine neuen Abweichungen entstanden sind."
    ),
    ReviewTarget.GRAPH: (
        "Prüfe fachlich, ob die Korrekturen die früheren Befunde "
        "beheben und bei Abdeckung, Zuschnitt und Abhängigkeiten der "
        "Vorgänge keine neuen Abweichungen entstanden sind."
    ),
    ReviewTarget.MATERIALIZE: (
        "Prüfe fachlich, ob die Korrekturen die früheren Befunde "
        "beheben und bei Ausführungsreife, Schnittstellen und "
        "Abnahmekriterien keine neuen Abweichungen entstanden sind."
    ),
}

_REVIEW_RULES = (
    "Starte selbst keine Prüfwerkzeuge oder Folgemodelle; du hast "
    "keine automatische Autorität gegenüber dem Schreibagenten und "
    "schließt nichts automatisch."
)

_VERDICT = "Ausgabe: PASS | CHANGES | NEEDS_DECISION."

_HUMAN_NOTE = (
    "Hinweis für den Menschen: Empfänger, Befundkontext und Quellstand "
    "verantwortest du; Schließen und weitere Schritte entscheidest du "
    "selbst."
)

_FEEDBACK_HEADER = (
    "Rückmeldung des Schreibagenten (unbestätigte Aussage, nicht "
    "geprüft; kein Beleg"
)
_FEEDBACK_REVIEW_TAIL = ", erst nach eigenem Urteil heranziehen"

_REPAIR_REQUEST = (
    "Bitte die gemeldeten Fehler beheben. Melde anschließend nur "
    "zurück, was aus Diff und Prüfergebnissen nicht hervorgeht, etwa "
    "offene Entscheidungen oder Hindernisse."
)


def render_review_turn(
    issue: HandoffIssue,
    target: ReviewTarget,
    report: PreflightReport | None,
    feedback: str | None,
) -> str:
    """Folgenachricht an die bisherige, vom Schreibagenten getrennte
    Review-Sitzung (keine neue Voll-Übergabe mit Rollentext).

    ``report`` liegt nur beim Prüfgegenstand build vor (bestandener
    Vorlauf); map/graph/materialize gehen ohne Code-Vorlauf zur
    erneuten, phasengerechten Prüfung.
    """
    lines = [
        "Empfänger: Review-Agent (bisherige, vom Schreibagenten "
        "getrennte Sitzung)",
        f"Reviewziel: {target.value}",
        f"Bead: {_one_line(issue.id)} - {_one_line(issue.title)}",
        "",
        f"Erneute Prüfung nach Korrekturen: {_RE_REVIEW_FOCUS[target]} "
        f"{_REVIEW_RULES} {_VERDICT}",
    ]
    if report is not None:
        lines += ["", *render_report_lines(report)]
    lines += _feedback_lines(feedback, _FEEDBACK_REVIEW_TAIL)
    lines += ["", _HUMAN_NOTE]
    return "\n".join(lines) + "\n"


def render_repair_turn(
    issue: HandoffIssue,
    finding: str,
    limit: int,
    feedback: str | None,
) -> str:
    """Nachricht an den Bau-Agenten, wenn der Vorlauf scheitert.

    ``finding`` ist der unveränderte Befund des Vorlaufs (jeder Befehl
    mit Status; bei Artefaktfehler ohne Artefaktverweis).
    """
    lines = [
        "Empfänger: Bau-Agent (Vorlauf fehlgeschlagen)",
        f"Bead: {_one_line(issue.id)} - {_one_line(issue.title)}",
        "",
        f"{_REPAIR_REQUEST} Die Rückmeldung darf höchstens {limit} "
        "Zeichen lang sein.",
        "",
        finding,
    ]
    lines += _feedback_lines(feedback)
    lines += [
        "",
        "Hinweis für den Menschen: danach erneut `ki-dev handoff "
        "BEAD_ID --step review --next-turn` ausführen (optional mit "
        "`--feedback-file DATEI|-`).",
    ]
    return "\n".join(lines) + "\n"


def _feedback_lines(feedback: str | None, tail: str = "") -> list[str]:
    if feedback is None:
        return []
    quoted = [
        f"| {_one_line(line)}".rstrip()
        for line in feedback.splitlines()
    ]
    return ["", f"{_FEEDBACK_HEADER}{tail}):", *quoted]


def _one_line(value: object) -> str:
    """Ohne Steuerzeichen (auch ANSI-Escapes) und ohne Zeilenumbruch."""
    return "".join(
        " " if ch.isspace() else ch
        for ch in str(value)
        if ch.isprintable() or ch.isspace()
    ).strip()
