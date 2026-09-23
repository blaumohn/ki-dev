"""Reiner Kern für geprüfte Arbeitsübergaben (ki-dev handoff)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Step(StrEnum):
    MAP = "map"
    GRAPH = "graph"
    MATERIALIZE = "materialize"
    BUILD = "build"
    REVIEW = "review"


@dataclass(frozen=True)
class HandoffIssue:
    """Normalisierte Bead-Rohwerte; Typen prüft validate_handoff."""

    id: object = None
    title: object = None
    description: object = None
    design: object = None
    acceptance_criteria: object = None
    source_refs: object = None


class HandoffInvalidError(ValueError):
    """Bead erfüllt die formalen Pflichtfelder des Schritts nicht."""

    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


_TEXT_FIELDS = ("id", "title", "description")
_BUILD_FIELDS = ("acceptance_criteria", "design")
_SOURCE_REFS_PATH = "metadata.handoff.source_refs"
_REFS_STEPS = {Step.MAP, Step.GRAPH, Step.MATERIALIZE}
_CONTRACT_STEPS = {Step.BUILD, Step.REVIEW}


def validate_handoff(
    issue: HandoffIssue, step: Step
) -> tuple[str, ...]:
    """Formale Lücken als Feldpfade; leer heißt vollständig."""
    problems = [
        name
        for name in _TEXT_FIELDS
        if not _is_text(getattr(issue, name))
    ]
    if step in _REFS_STEPS:
        problems += _source_ref_problems(issue.source_refs)
    if step in _CONTRACT_STEPS:
        problems += [
            name
            for name in _BUILD_FIELDS
            if not _is_text(getattr(issue, name))
        ]
    return tuple(problems)


def render_handoff(issue: HandoffIssue, step: Step) -> str:
    """Kopierbarer Klartext; lehnt formal unvollständige Beads ab."""
    problems = validate_handoff(issue, step)
    if problems:
        raise HandoffInvalidError(problems)
    lines = [
        f"Schritt: {step.value}",
        f"Bead: {_line(issue.id)} - {_line(issue.title)}",
        "",
        *_COMMON,
        "",
        *_ROLES[step],
    ]
    if step in _REFS_STEPS:
        lines += ["", "Quellenreferenzen (unaufgelöst):"]
        lines += [f"- {_line(ref)}" for ref in issue.source_refs]
    lines += ["", _NEXT[step]]
    return "\n".join(lines) + "\n"


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _source_ref_problems(refs: object) -> list[str]:
    if not isinstance(refs, list) or not refs:
        return [_SOURCE_REFS_PATH]
    return [
        f"{_SOURCE_REFS_PATH}[{index}]"
        for index, ref in enumerate(refs)
        if not _is_text(ref)
    ]


def _line(value: object) -> str:
    """Einzeilig ohne Steuerzeichen (auch ANSI-Escapes)."""
    text = "".join(
        " " if ch.isspace() else ch
        for ch in str(value)
        if ch.isprintable() or ch.isspace()
    )
    return " ".join(text.split())


_COMMON = (
    "Die Beads-ID ist im gemeinsamen Arbeitsbaum die Übergabe. Lies",
    "AGENTS.md, den geltenden Auftrag und den tatsächlichen",
    "Arbeitsstand gezielt. Melde konkrete fehlende Voraussetzungen,",
    "statt zu raten.",
)

_ROLES = {
    Step.MAP: (
        "Rolle: Kartierungsagent.",
        "Lies die referenzierten Rohnotizen abschnittsweise und",
        "erstelle Quellenkarten-Beads mit Themen und genauen",
        "Fundstellen. Führe die Abschnittsabdeckung (kartiert /",
        "begründet irrelevant /",
        "offen). Bewahre Einschränkungen, Widersprüche und offene",
        "Fragen. Die Karte ersetzt die Originalquellen nicht.",
        "Hinterlasse bei Kontextende den aktuellen Stand und den",
        "nächsten unbearbeiteten Abschnitt in Beads. Erstelle noch",
        "keine Executor-Aufträge.",
    ),
    Step.GRAPH: (
        "Rolle: Auflösungsagent.",
        "Nutze die Karte und lies gezielt Originalstellen nach.",
        "Materialisiere dünne Vorgänge mit Ergebnis, Schnittstellen,",
        "Quellenbezügen und echten Abhängigkeiten; noch keine",
        "vollständigen Executor-Aufträge. Du verantwortest den",
        "fachlichen Zuschnitt und meldest unentscheidbare Konflikte.",
    ),
    Step.MATERIALIZE: (
        "Rolle: Materialisierungsagent.",
        "Löse genau diesen dünnen Vorgang ausführungsreif auf. Finde",
        "den Kontext selbst über Karten-/Graphreferenzen und",
        "Code-Einstiege. Schreibe den aktuellen Auftrag mit Ziel und",
        "Umfang, Schnittstellen, Prüfanweisungen und Abnahmekriterien;",
        "übernimm relevante ADR-Festlegungen in den Auftrag. Gib zu",
        "große Vorgänge als begründeten Teilungsvorschlag zurück.",
        "Schreibe keine Historie als Nachtragsstapel in die",
        "Beschreibung.",
    ),
    Step.BUILD: (
        "Rolle: Bau-Agent.",
        "Setze genau diesen materialisierten Bead um (description,",
        "design, acceptance_criteria), führe gezielte",
        "Entwicklungstests aus, schreibe Tests und untersuche Fehler.",
        "Kein pauschales Test-, Typprüfer- oder Werkzeugverbot: Ein",
        "deterministischer Vorlauf übernimmt nach dieser Sitzung",
        "lediglich mechanisches Linting/Formatieren und die",
        "abschließenden Prüfungen; das entlastet dich nur davon.",
        "Melde kurz Ergebnis, Prüfungen und Blocker. Durchsuche",
        "keine allgemeinen ADR-Sammlungen, um den Auftrag zu",
        "rekonstruieren; melde konkrete Vertragslücken zurück.",
    ),
    Step.REVIEW: (
        "Rolle: Review-Agent in frischer, getrennter Sitzung.",
        "Bilde zuerst dein eigenes Urteil anhand der geltenden",
        "description, design und acceptance_criteria, des",
        "tatsächlichen Diffs und des beigefügten Prüfberichts. Diese",
        "Übergabe hat bereits einen deterministischen Vorlauf",
        "ausgeführt (Korrekturen und Prüfungen); starte selbst keine",
        "Formatter, Linter, Typprüfer oder Tests. Der Bericht nennt",
        "nur seinen Zeitpunkt und belegt keinen unveränderten",
        "Quellstand; diese Zuordnung verantwortet der Mensch.",
        "Lesen von Dateien, Diff,",
        "Anforderungen und Prüfbericht bleibt erlaubt. Beurteile",
        "Testqualität und Abdeckung; melde fehlende oder",
        "unzureichende Nachweise als Befund, ohne dafür selbst",
        "Tests zu starten.",
        "Verwende notes, comments, Selbsteinschätzungen des",
        "Bau-Agenten und frühere Reviews vor diesem Urteil nicht als",
        "Bewertungsinput.",
        "Ausgabe: PASS | CHANGES | NEEDS_DECISION; bei CHANGES je",
        "Befund kurz mit Anforderungs- oder Codebezug. Du hast keine",
        "automatische Autorität gegenüber dem Bau-Agenten und",
        "schließt nichts automatisch.",
    ),
}

_NEXT = {
    Step.MAP: "Hinweis für den Menschen: danach getrennte "
    "Kartenprüfung in eigener Sitzung starten.",
    Step.GRAPH: "Hinweis für den Menschen: danach je dünnem Vorgang "
    "den Schritt materialize starten.",
    Step.MATERIALIZE: "Hinweis für den Menschen: danach die "
    "Ausführungsreife getrennt prüfen lassen.",
    Step.BUILD: "Hinweis für den Menschen: danach eine getrennte "
    "Review-Sitzung mit dem Schritt review starten.",
    Step.REVIEW: "Hinweis für den Menschen: Schließen und weitere "
    "Schritte entscheidest du selbst.",
}
