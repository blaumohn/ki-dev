"""Reiner Kern für geprüfte Arbeitsübergaben (ki-dev step)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator

from ki_dev.handoff_limit import check_base_length

if TYPE_CHECKING:
    from ki_dev.handoff_guidelines import GuidelineSection


class Step(StrEnum):
    MAP = "map"
    GRAPH = "graph"
    MATERIALIZE = "materialize"
    BUILD = "build"
    REVIEW = "review"


class ReviewTarget(StrEnum):
    """Prüfgegenstand von ``Step.REVIEW``; nur dieser wertet es aus.

    Fehlt ``review_target`` bei ``Step.REVIEW``, bleibt das
    Verhalten die bisherige Build-Review (Rückwärtskompatibilität
    von ``--step review`` ohne ``--review-of``).
    """

    MAP = "map"
    GRAPH = "graph"
    MATERIALIZE = "materialize"
    BUILD = "build"


@dataclass(frozen=True)
class HandoffIssue:
    """Normalisierte Bead-Rohwerte; Typen prüft validate_handoff."""

    id: object = None
    title: object = None
    description: object = None
    design: object = None
    acceptance_criteria: object = None
    source_refs: object = None
    epic_context: tuple[tuple[str, str], ...] = ()


class HandoffInvalidError(ValueError):
    """Bead erfüllt die formalen Pflichtfelder des Schritts nicht."""

    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


_SOURCE_REFS_PATH = "metadata.handoff.source_refs"
_REFS_STEPS = {Step.MAP, Step.GRAPH, Step.MATERIALIZE}
_CONTRACT_STEPS = {Step.BUILD}
# Ein fehlender review_target bei Step.REVIEW bleibt die bisherige
# Build-Review (Rückwärtskompatibilität von --step review ohne
# --review-of).
_REVIEW_TARGET_REFS = {
    ReviewTarget.MAP,
    ReviewTarget.GRAPH,
    ReviewTarget.MATERIALIZE,
}
_REVIEW_TARGET_CONTRACT = {
    None,
    ReviewTarget.MATERIALIZE,
    ReviewTarget.BUILD,
}


def _needs_refs(step: Step, review_target: ReviewTarget | None) -> bool:
    if step is Step.REVIEW:
        return review_target in _REVIEW_TARGET_REFS
    return step in _REFS_STEPS


def _needs_contract(
    step: Step, review_target: ReviewTarget | None
) -> bool:
    if step is Step.REVIEW:
        return review_target in _REVIEW_TARGET_CONTRACT
    return step in _CONTRACT_STEPS


# Gemeinsame Schema-Bausteine (Technikleitlinie: Draft202012Validator,
# einmal je Regel definiert und wiederverwendet). metadata/handoff
# bleiben rein deklarativ: source_refs ist eine nichtleere Liste
# nichtleerer Texte, unabhängig vom internen HandoffIssue-Feldnamen.
NONEMPTY_TEXT_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "pattern": r"\S",
}

_SOURCE_REFS_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "items": NONEMPTY_TEXT_SCHEMA,
}

_BASE_PROPERTIES = {
    "id": NONEMPTY_TEXT_SCHEMA,
    "title": NONEMPTY_TEXT_SCHEMA,
    "description": NONEMPTY_TEXT_SCHEMA,
}
_BASE_REQUIRED = ("id", "title", "description")

_CONTRACT_PROPERTIES = {
    "acceptance_criteria": NONEMPTY_TEXT_SCHEMA,
    "design": NONEMPTY_TEXT_SCHEMA,
}
_CONTRACT_REQUIRED = ("acceptance_criteria", "design")

_REFS_PROPERTIES = {
    "metadata": {
        "type": "object",
        "required": ["handoff"],
        "properties": {
            "handoff": {
                "type": "object",
                "required": ["source_refs"],
                "properties": {"source_refs": _SOURCE_REFS_SCHEMA},
            },
        },
    },
}
_REFS_REQUIRED = ("metadata",)


def _issue_schema(*, needs_refs: bool, needs_contract: bool) -> dict:
    properties = dict(_BASE_PROPERTIES)
    required = list(_BASE_REQUIRED)
    if needs_contract:
        properties |= _CONTRACT_PROPERTIES
        required += _CONTRACT_REQUIRED
    if needs_refs:
        properties |= _REFS_PROPERTIES
        required += _REFS_REQUIRED
    return {
        "type": "object",
        "required": required,
        "properties": properties,
    }


# Die vier (step, review_target)-Verträge reduzieren sich auf zwei
# Booleans (_needs_refs/_needs_contract); die Varianten werden beim
# Laden einmal zusammengesetzt statt je Aufruf neu gebaut.
_ISSUE_SCHEMAS = {
    (needs_refs, needs_contract): _issue_schema(
        needs_refs=needs_refs, needs_contract=needs_contract
    )
    for needs_refs in (False, True)
    for needs_contract in (False, True)
}

# Reihenfolge der Feldpfade in der Ausgabe, unabhängig von der
# (undefinierten) Reihenfolge, in der Draft202012Validator Fehler über
# mehrere properties hinweg liefert. Geschlüsselt über das erste
# Pfadsegment der rohen jsonschema-Fehlerpfade (vor dem Formatieren).
_FIELD_RANK = {
    "id": 0,
    "title": 1,
    "description": 2,
    "metadata": 3,
    "acceptance_criteria": 4,
    "design": 5,
}


def validate_handoff(
    issue: HandoffIssue,
    step: Step,
    review_target: ReviewTarget | None = None,
) -> tuple[str, ...]:
    """Formale Lücken als Feldpfade; leer heißt vollständig.

    ``review_target`` wirkt nur bei ``step is Step.REVIEW``: er wählt,
    welcher Prüfgegenstand (map/graph/materialize/build) benötigt wird.
    Für andere Schritte wird er ignoriert.
    """
    refs = _needs_refs(step, review_target)
    contract = _needs_contract(step, review_target)
    schema = _ISSUE_SCHEMAS[(refs, contract)]
    validator = Draft202012Validator(schema)
    paths = {
        tuple(error.absolute_path)
        for error in validator.iter_errors(_issue_payload(issue))
    }
    ordered = sorted(paths, key=_path_sort_key)
    return tuple(_field_path(path) for path in ordered)


def _issue_payload(issue: HandoffIssue) -> dict:
    """HandoffIssue als Schema-Instanz; nur zur Validierung gebildet."""
    return {
        "id": issue.id,
        "title": issue.title,
        "description": issue.description,
        "acceptance_criteria": issue.acceptance_criteria,
        "design": issue.design,
        "metadata": {"handoff": {"source_refs": issue.source_refs}},
    }


def _path_sort_key(path: tuple) -> tuple[int, int]:
    """Sortiert die rohen jsonschema-Pfade vor dem Formatieren:
    zuerst nach Feld (Reihenfolge wie im bisherigen Vertrag), innerhalb
    von source_refs zusätzlich nach Listenindex."""
    index = path[3] if len(path) > 3 else -1
    return (_FIELD_RANK[path[0]], index)


def _field_path(path: tuple) -> str:
    """jsonschema-Fehlerpfad in den bisherigen Feldpfad übersetzen."""
    if path[:3] == ("metadata", "handoff", "source_refs"):
        if len(path) == 3:
            return _SOURCE_REFS_PATH
        return f"{_SOURCE_REFS_PATH}[{path[3]}]"
    return str(path[0])


def render_handoff(
    issue: HandoffIssue,
    step: Step,
    review_target: ReviewTarget | None = None,
    guidelines: Sequence[GuidelineSection] = (),
    base_max_chars: int | None = None,
) -> str:
    """Basisübergabe, danach der gesonderte Leitlinienblock; die Grenze
    gilt nur für die Basis (``None``: ungeprüft)."""
    base = render_base_handoff(
        issue, step, review_target, max_chars=base_max_chars
    )
    return base + render_guideline_block(guidelines)


def render_base_handoff(
    issue: HandoffIssue,
    step: Step,
    review_target: ReviewTarget | None = None,
    *,
    reading_hint: str | None = None,
    max_chars: int | None = None,
) -> str:
    """Kopierbarer Klartext ohne Leitlinien; lehnt formal
    unvollständige Beads ab.

    ``reading_hint`` (Sitzungsimport) gehört zur Basis. Mit
    ``max_chars`` wird der gerenderte Text einschließlich Hinweis und
    abschließendem Zeilenumbruch gezählt; Übergröße wird abgelehnt,
    nie gekürzt.
    """
    problems = validate_handoff(issue, step, review_target)
    if problems:
        raise HandoffInvalidError(problems)
    text = "\n".join(_base_lines(issue, step, review_target)) + "\n"
    if reading_hint is not None:
        text += f"\n{reading_hint}\n"
    if max_chars is not None:
        fields = _variable_fields(
            issue, step, review_target, reading_hint
        )
        check_base_length(text, max_chars, fields)
    return text


def _base_lines(
    issue: HandoffIssue, step: Step, review_target: ReviewTarget | None
) -> list[str]:
    lines = [f"Schritt: {step.value}"]
    if step is Step.REVIEW:
        effective_target = review_target or ReviewTarget.BUILD
        lines.append(f"Reviewziel: {effective_target.value}")
    lines += [
        f"Bead: {_line(issue.id)} - {_line(issue.title)}",
        "",
        *_COMMON,
        "",
        *_roles(step, review_target),
    ]
    if issue.epic_context:
        lines += [
            "",
            "Die Epic-Hinweise vermitteln Ziel, Zusammenhang und",
            "begründende Entscheidungen des Elternvorhabens. Nutze",
            "diesen Kontext für eine dazu passende Lösung deiner",
            "Teilaufgabe. Melde Widersprüche zum konkreten Auftrag.",
        ]
    for epic_id, epic_context in issue.epic_context:
        lines += [
            "",
            f"Epic-Hinweis ({_line(epic_id)}):",
            _line(epic_context),
        ]
    if _needs_refs(step, review_target):
        lines += ["", "Quellenreferenzen (unaufgelöst):"]
        lines += [f"- {_line(ref)}" for ref in issue.source_refs]
    lines += ["", _NEXT[step]]
    return lines


def ensure_base_fits(
    issue: HandoffIssue,
    step: Step,
    review_target: ReviewTarget | None,
    max_chars: int,
) -> None:
    """Basisgrenze prüfen, ohne den Text zu verwenden (vor einem
    Vorlauf, der Dateien ändern kann)."""
    render_base_handoff(issue, step, review_target, max_chars=max_chars)


def _variable_fields(
    issue: HandoffIssue,
    step: Step,
    review_target: ReviewTarget | None,
    reading_hint: str | None,
) -> list[tuple[str, int]]:
    """Zeichenanteile der veränderlichen Basisteile, ohne Rohwerte."""
    fields = [
        ("id", len(_line(issue.id))),
        ("title", len(_line(issue.title))),
    ]
    for index, (epic_id, context) in enumerate(issue.epic_context):
        size = len(_line(epic_id)) + len(_line(context))
        fields.append((f"epic_context[{index}]", size))
    if _needs_refs(step, review_target):
        for index, ref in enumerate(issue.source_refs):
            fields.append((f"source_refs[{index}]", len(_line(ref))))
    if reading_hint is not None:
        fields.append(("Lesehinweis", len(reading_hint)))
    return fields


def render_guideline_block(
    guidelines: Sequence[GuidelineSection],
) -> str:
    """Gesonderter Kontextblock nach allen Basisteilen; leer ohne
    Abschnitte. Regeltexte bleiben unverändert (Markdown,
    Zeilenumbrüche) und werden weder gekürzt noch zur Basis gezählt."""
    if not guidelines:
        return ""
    lines = ["", *_GUIDELINE_INTRO]
    for section in guidelines:
        lines += [
            "",
            f"--- {_line(section.source)}#{_line(section.id)} ---",
            section.text,
        ]
    return "\n".join(lines) + "\n"


def _roles(
    step: Step, review_target: ReviewTarget | None
) -> tuple[str, ...]:
    if step is not Step.REVIEW:
        return _ROLES[step]
    return _REVIEW_ROLES[review_target or ReviewTarget.BUILD]


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
    "den Bead selbst (`bd show BEAD_ID`), den geltenden Auftrag und",
    "den tatsächlichen Arbeitsstand gezielt. Melde konkrete fehlende",
    "Voraussetzungen, statt zu raten.",
)

_GUIDELINE_INTRO = (
    "LEITLINIEN (mitgeliefert; gesonderter Block nach der Übergabe)",
    "Diese Regeltexte gelten für diesen Schritt. Wende sie direkt",
    "an; lies ihre Quelldokumente dafür nicht erneut vollständig.",
    "Jeder Abschnitt nennt YAML-Quelle und Abschnitts-ID.",
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
}

# Je Step.REVIEW-Prüfgegenstand ein eigener Rollentext: Nur die
# Build-Review hat einen vorgeschalteten deterministischen Vorlauf
# (Diff, Prüfbericht) aus handoff_preflight; das dort behauptete
# Ergebnis existiert für map/graph/materialize nicht und darf ihnen
# nicht unterstellt werden. Alle vier verbieten trotzdem eigene
# Prüfwerkzeuge und Folgemodellaufrufe.
_REVIEW_ROLES = {
    ReviewTarget.MAP: (
        "Rolle: Review-Agent in frischer, getrennter Sitzung",
        "(Kartenprüfung).",
        "Bilde zuerst dein eigenes Urteil aus den referenzierten",
        "Rohquellen und der erstellten Karte; nicht aus notes,",
        "comments oder früheren Reviews. Prüfe Quellenabdeckung,",
        "genaue Fundstellen sowie bewahrte Einschränkungen,",
        "Widersprüche und offene Fragen; werte eine erfundene",
        "Entscheidung der Karte als Befund. Starte selbst keine",
        "Prüfwerkzeuge oder Folgemodelle.",
        "Ausgabe: PASS | CHANGES | NEEDS_DECISION; bei CHANGES oder",
        "NEEDS_DECISION je Befund mit Quellenbezug, konkreter",
        "Abweichung und betroffenem Abschnitt. Du hast keine",
        "automatische Autorität gegenüber dem Kartierungsagenten und",
        "schließt nichts automatisch; unentscheidbare Konflikte gehen",
        "an den Menschen.",
    ),
    ReviewTarget.GRAPH: (
        "Rolle: Review-Agent in frischer, getrennter Sitzung",
        "(Graphprüfung).",
        "Bilde zuerst dein eigenes Urteil aus Karte, Originalquellen",
        "und den angelegten dünnen Vorgängen; nicht aus notes,",
        "comments oder früheren Reviews. Prüfe, ob alle relevanten",
        "Anforderungen abgedeckt sind, die Vorgänge sinnvoll begrenzt",
        "bleiben, Abhängigkeiten echt bestehen und keine",
        "unbeauftragte Umfangserweiterung oder stillschweigende",
        "Entscheidung vorliegt. Starte selbst keine Prüfwerkzeuge",
        "oder Folgemodelle.",
        "Ausgabe: PASS | CHANGES | NEEDS_DECISION; bei CHANGES oder",
        "NEEDS_DECISION je Befund mit Quellenbezug, konkreter",
        "Abweichung und betroffenem Vorgang. Du hast keine",
        "automatische Autorität gegenüber dem Auflösungsagenten und",
        "schließt nichts automatisch; unentscheidbare Konflikte gehen",
        "an den Menschen.",
    ),
    ReviewTarget.MATERIALIZE: (
        "Rolle: Review-Agent in frischer, getrennter Sitzung",
        "(Materialisierungsprüfung).",
        "Bilde zuerst dein eigenes Urteil gegen die ursprünglichen,",
        "bestätigten Nutzeranforderungen und Quellen, nicht nur",
        "gegen einen möglicherweise fehlerhaften Bead; nicht aus",
        "notes, comments oder früheren Reviews. Gleiche Rollen,",
        "Modalität (darf/muss/darf nicht), Geltungsbereich,",
        "Nicht-Ziele, Schnittstellen, konkrete Prüfaufträge und",
        "messbare Abnahmekriterien ab. Unterscheide bestätigte",
        "Entscheidungen von Umsetzungsvorschlägen und offenen",
        "Produktfragen. Eine fehlende Quelle ist NEEDS_DECISION;",
        "formal gefüllte Felder allein rechtfertigen kein PASS.",
        "Benenne Übergröße, widersprüchliche Nachträge und nötige",
        "Teilung mit betroffenem Abschnitt. Starte selbst keine",
        "Prüfwerkzeuge oder Folgemodelle.",
        "Ausgabe: PASS | CHANGES | NEEDS_DECISION; bei CHANGES oder",
        "NEEDS_DECISION je Befund mit Quellenbezug, konkreter",
        "Abweichung und betroffenem Abschnitt. Du hast keine",
        "automatische Autorität gegenüber dem Materialisierungsagenten",
        "und schließt nichts automatisch; unentscheidbare Konflikte",
        "gehen an den Menschen.",
    ),
    ReviewTarget.BUILD: (
        "Rolle: Review-Agent in frischer, getrennter Sitzung.",
        "Bilde zuerst dein eigenes Urteil anhand der geltenden",
        "description, design und acceptance_criteria, des",
        "tatsächlichen Diffs und des beigefügten Prüfberichts. Diese",
        "Übergabe hat bereits einen deterministischen Vorlauf",
        "ausgeführt (Korrekturen und Prüfungen); starte selbst keine",
        "Formatter, Linter, Typprüfer oder Tests, auch keine",
        "Prüfwerkzeuge oder Folgemodelle. Der Bericht nennt",
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
    "Kartenprüfung mit `ki-dev step BEAD_ID --step review "
    "--review-of map` starten (BEAD_ID des erstellten Karten-Beads).",
    Step.GRAPH: "Hinweis für den Menschen: danach die angelegten "
    "dünnen Vorgänge mit `ki-dev step BEAD_ID --step review "
    "--review-of graph` prüfen lassen (BEAD_ID je dünnem Vorgang); "
    "erst danach je Vorgang materialize starten.",
    Step.MATERIALIZE: "Hinweis für den Menschen: danach die "
    "Ausführungsreife mit `ki-dev step BEAD_ID --step review "
    "--review-of materialize` getrennt prüfen lassen.",
    Step.BUILD: "Hinweis für den Menschen: danach eine getrennte "
    "Review-Sitzung mit `ki-dev step BEAD_ID --step review` "
    "starten.",
    Step.REVIEW: "Hinweis für den Menschen: Schließen und weitere "
    "Schritte entscheidest du selbst.",
}
