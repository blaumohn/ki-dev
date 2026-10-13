
import pytest

from ki_dev.ops.context.bead_input import (
    BeadInput,
    BeadInputInvalidError,
)
from tests.turn_helpers import (
    HANDOFF_STATES,
    WRITE_STATES,
    render_handoff,
    validate_for,
)

REFS = ["docs/design/a.md#L12-L40", "bd:karte"]


def _issue(**changes):
    values = {
        "id": "x-1",
        "title": "Titel",
        "description": "Beschreibung mit GEHEIMER-DUMP",
        "design": "Design-Text",
        "acceptance_criteria": "AC-Text",
        "source_refs": REFS,
    }
    return BeadInput(**(values | changes))


@pytest.mark.parametrize("step", HANDOFF_STATES)
def test_complete_issue_is_valid_for_every_step(step):
    assert validate_for(_issue(), step) == ()


@pytest.mark.parametrize("step", HANDOFF_STATES)
@pytest.mark.parametrize("field", ["id", "title", "description"])
@pytest.mark.parametrize("bad", [None, "", "  ", 3, ["x"]])
def test_common_fields_must_be_nonempty_strings(step, field, bad):
    assert validate_for(_issue(**{field: bad}), step) == (field,)


@pytest.mark.parametrize(
    "step", ["map", "graph", "materialize"]
)
@pytest.mark.parametrize("bad", [None, [], "a.md", [""], {"a": 1}])
def test_source_refs_required_for_map_graph_materialize(step, bad):
    problems = validate_for(_issue(source_refs=bad), step)
    assert problems[0].startswith("metadata.handoff.source_refs")


def test_source_ref_problem_names_the_index():
    problems = validate_for(
        _issue(source_refs=["ok", " ", 7]), "map"
    )
    assert problems == (
        "metadata.handoff.source_refs[1]",
        "metadata.handoff.source_refs[2]",
    )


@pytest.mark.parametrize("step", ["implement", "implement.review"])
def test_build_review_need_no_metadata(step):
    assert validate_for(_issue(source_refs=None), step) == ()


@pytest.mark.parametrize("step", ["implement", "implement.review"])
@pytest.mark.parametrize("field", ["acceptance_criteria", "design"])
@pytest.mark.parametrize("bad", [None, "", 5])
def test_build_review_require_contract_fields(step, field, bad):
    assert validate_for(_issue(**{field: bad}), step) == (field,)


@pytest.mark.parametrize(
    "step", ["map", "graph", "materialize"]
)
def test_map_graph_materialize_need_no_design_or_ac(step):
    issue = _issue(design=None, acceptance_criteria=None)
    assert validate_for(issue, step) == ()


def test_all_problems_are_reported_together():
    issue = BeadInput()
    assert validate_for(issue, "implement") == (
        "id",
        "title",
        "description",
        "acceptance_criteria",
        "design",
    )


@pytest.mark.parametrize("step", HANDOFF_STATES)
def test_render_is_deterministic_plain_and_dump_free(step):
    first = render_handoff(_issue(), step)
    assert first == render_handoff(_issue(), step)
    assert f"Schritt: {step.rpartition('.')[2]}" in first
    assert "Bead: x-1 - Titel" in first
    assert "\x1b" not in first
    assert "GEHEIMER-DUMP" not in first
    assert "Design-Text" not in first
    assert "AC-Text" not in first
    assert first.endswith("\n")


def test_render_roles_are_distinct():
    roles = {s: render_handoff(_issue(), s) for s in HANDOFF_STATES}
    assert "Kartierungsagent" in roles["map"]
    assert "Abschnittsabdeckung" in roles["map"]
    assert "Auflösungsagent" in roles["graph"]
    assert "dünne Vorgänge" in roles["graph"]
    assert "Materialisierungsagent" in roles["materialize"]
    assert "ausführungsreif" in roles["materialize"]
    assert "Umsetzer" in roles["implement"]
    assert "Review-Agent" in roles["implement.review"]
    assert (
        "PASS oder die stärkste Befundklasse"
        in roles["implement.review"]
    )


def test_source_refs_only_in_reference_steps():
    for step in ("map", "graph", "materialize"):
        text = render_handoff(_issue(), step)
        assert "- docs/design/a.md#L12-L40\n- bd:karte\n" in text
    for step in ("implement", "implement.review"):
        assert "docs/design/a.md" not in render_handoff(_issue(), step)


def test_review_hands_no_notes_or_self_assessment_to_reviewer():
    text = render_handoff(_issue(), "implement.review")
    assert "nicht als Bewertungsinput" in " ".join(text.split())
    assert "GEHEIMER-DUMP" not in text


def test_successor_is_only_a_human_hint():
    for step in HANDOFF_STATES:
        assert "Hinweis für den Menschen:" in render_handoff(
            _issue(), step
        )


def test_title_control_characters_and_newlines_are_flattened():
    text = render_handoff(
        _issue(title="A\x1b[31mB\nC\t[bold]D"), "implement"
    )
    assert "\x1b" not in text
    assert "Bead: x-1 - A[31mB C [bold]D\n" in text


def test_render_refuses_invalid_issue():
    with pytest.raises(BeadInputInvalidError) as info:
        render_handoff(_issue(design=None), "implement")
    assert info.value.problems == ("design",)


def test_core_imports_no_cli_or_process_modules():
    """Prozesse startet ki-dev über Plumbum (Technikleitlinie);
    ``subprocess`` selbst lädt schon python-statemachine über
    ``asyncio``, ohne etwas zu starten."""
    import subprocess
    import sys

    code = (
        "import sys, ki_dev.runner.turns,"
        " ki_dev.ops.context.bead_input;"
        "bad = {'typer', 'rich', 'plumbum',"
        " 'ki_dev.ops.context.beads_reader'};"
        "sys.exit(int(bool(bad & set(sys.modules))))"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_build_may_test_review_may_not():
    """Build darf gezielt testen (kein pauschales Werkzeugverbot);
    Review startet selbst keine Prüfwerkzeuge, darf aber lesen und
    Testqualität/Abdeckung beurteilen (AC1/AC2)."""
    build = " ".join(render_handoff(_issue(), "implement").split())
    review = " ".join(
        render_handoff(_issue(), "implement.review").split()
    )

    assert "gezielte Entwicklungstests" in build
    assert "Kein pauschales Test-, Typprüfer- oder Werkzeugverbot" in (
        build
    )
    assert "Starte keine Formatter, Linter" not in build

    assert "starte selbst keine Formatter, Linter" in review
    assert "Typprüfer oder Tests" in review
    assert "Lesen von Dateien, Diff" in review
    assert "bleibt erlaubt" in review
    assert "Testqualität und Abdeckung" in review
    assert "Prüfbericht" in review


@pytest.mark.parametrize("step", HANDOFF_STATES)
def test_every_step_includes_epic_context_with_origin(step):
    context = (
        "Wir erproben manuelle Übergaben vor der Automatisierung. "
        "Der Mensch startet die Sitzungen."
    )
    issue = _issue(
        epic_context=(("epic-1", context),)
    )
    text = render_handoff(issue, step)
    assert f"Epic-Hinweis (epic-1):\n{context}" in text
    normalized = " ".join(text.split())
    assert (
        "Ziel, Zusammenhang und begründende Entscheidungen"
        in normalized
    )
    assert "Melde Widersprüche zum konkreten Auftrag." in normalized


def test_epic_context_instruction_appears_once_before_ordered_hints():
    issue = _issue(
        epic_context=(("outer", "Ziel"), ("inner", "Beitrag"))
    )
    text = render_handoff(issue, "implement")
    instruction = "Die Epic-Hinweise vermitteln"
    assert text.count(instruction) == 1
    assert text.index(instruction) < text.index("Epic-Hinweis (outer)")
    assert text.index("Epic-Hinweis (outer)") < text.index(
        "Epic-Hinweis (inner)"
    )


@pytest.mark.parametrize("step", HANDOFF_STATES)
def test_no_epic_context_adds_no_instruction(step):
    text = render_handoff(_issue(), step)
    assert "Die Epic-Hinweise vermitteln" not in text
    assert "Epic-Hinweis (" not in text


# --- Review-Zustände der Abläufe --------------------------------------


SOURCE_TARGETS = (
    "map",
    "graph",
    "materialize",
)


@pytest.mark.parametrize("target", SOURCE_TARGETS)
def test_source_review_targets_require_source_refs(target):
    problems = validate_for(
        _issue(source_refs=None), f"{target}.review"
    )
    assert problems[0].startswith("metadata.handoff.source_refs")


@pytest.mark.parametrize(
    "target", ["map", "graph"]
)
def test_map_graph_review_need_no_design_or_ac(target):
    issue = _issue(design=None, acceptance_criteria=None)
    assert validate_for(issue, f"{target}.review") == ()


def test_materialize_review_needs_refs_and_contract_fields():
    target = "materialize"
    assert validate_for(_issue(), f"{target}.review") == ()

    missing_refs = validate_for(
        _issue(source_refs=None), f"{target}.review"
    )
    assert missing_refs[0].startswith("metadata.handoff.source_refs")

    missing_design = validate_for(
        _issue(design=None), f"{target}.review"
    )
    assert missing_design == ("design",)


def test_build_review_target_needs_no_source_refs():
    issue = _issue(source_refs=None)
    problems = validate_for(
        issue, "implement.review"
    )
    assert problems == ()


@pytest.mark.parametrize("target", SOURCE_TARGETS)
def test_source_review_targets_render_source_refs(target):
    text = render_handoff(_issue(), f"{target}.review")
    assert "- docs/design/a.md#L12-L40\n- bd:karte\n" in text


def test_build_review_target_does_not_render_source_refs():
    assert "docs/design/a.md" not in render_handoff(
        _issue(), "implement.review"
    )


def test_review_targets_have_distinct_role_texts():
    texts = {
        target: render_handoff(_issue(), f"{target}.review")
        for target in WRITE_STATES
    }
    assert "Kartenprüfung" in texts["map"]
    assert "Graphprüfung" in texts["graph"]
    assert (
        "Materialisierungsprüfung" in texts["materialize"]
    )
    assert "deterministischen Vorlauf" in texts["implement"]
    for target in SOURCE_TARGETS:
        assert "deterministischen Vorlauf" not in texts[target]


def test_materialize_review_transports_ac3_criteria():
    text = " ".join(
        render_handoff(
            _issue(), "materialize.review"
        ).split()
    )
    assert "ursprünglichen, bestätigten Nutzeranforderungen und" in text
    assert "nicht nur gegen einen möglicherweise fehlerhaften" in text
    assert "Modalität (darf/muss/darf nicht)" in text
    assert "Geltungsbereich" in text
    assert "Nicht-Ziele" in text
    # "unbeauftragte Umfangserweiterung" ist ein Graph-Kriterium.
    assert "unbeauftragte Umfangserweiterung" not in text
    assert "fehlende Quelle ist Klasse source" in text
    assert "Übergröße" in text


def test_materialize_review_criteria_cover_invented_build_test_ban():
    """Regressionsfixtur: ein materialisierter Auftrag erfindet ein
    Build-Testverbot, das der Bau-Rolle widerspricht (siehe
    ki-dev-ablauf-8is und test_build_may_test_review_may_not: "Build
    darf gezielt testen"). AC3 verlangt keine automatische Erkennung;
    die Fixtur belegt nur, dass die transportierten Kriterien
    ("Modalität darf/muss/darf nicht", bestätigte Entscheidung vs.
    Umsetzungsvorschlag) einem Reviewer erlauben, das erfundene
    Verbot als Prüfgegenstand zu erkennen."""
    issue = _issue(
        design=(
            "Der Bau-Agent darf keine Tests ausführen; jegliche "
            "Testausführung ist untersagt."
        )
    )
    text = " ".join(
        render_handoff(
            issue, "materialize.review"
        ).split()
    )
    # Der Rohtext des Auftrags erscheint nicht in der Übergabe
    # (Grenzen); die Kriterien dafür, ein erfundenes "darf nicht" als
    # unbestätigte Entscheidung zu erkennen, aber schon.
    assert "Der Bau-Agent darf keine Tests" not in text
    assert "Modalität (darf/muss/darf nicht)" in text
    assert (
        "Unterscheide bestätigte Entscheidungen von "
        "Umsetzungsvorschlägen und offenen Produktfragen" in text
    )


def test_materialize_review_criteria_cover_unauthorized_loop_scope():
    """Regressionsfixtur: ein materialisierter Auftrag erweitert
    unbeauftragt die ki-dev-loop-Architektur (wiw selbst nennt "keine
    neue Loop-Architektur" als Nicht-Umfang). AC3 verlangt keine
    automatische Erkennung; die Fixtur belegt nur, dass
    Geltungsbereich-/Nicht-Ziele-/Übergröße-Kriterien einem Reviewer
    erlauben, die unbeauftragte Erweiterung als Prüfgegenstand zu
    erkennen."""
    issue = _issue(
        description=(
            "Zusätzlich führen wir eine neue Loop-Runde für "
            "automatische Freigaben im Bauablauf ein."
        )
    )
    text = " ".join(
        render_handoff(
            issue, "materialize.review"
        ).split()
    )
    assert "automatische Freigaben" not in text
    assert "Geltungsbereich" in text
    assert "Nicht-Ziele" in text
    assert (
        "Benenne Übergröße, widersprüchliche Nachträge und nötige "
        "Teilung mit betroffenem Abschnitt" in text
    )


@pytest.mark.parametrize("target", WRITE_STATES)
def test_all_review_targets_forbid_own_tooling_or_further_models(
    target,
):
    text = " ".join(
        render_handoff(_issue(), f"{target}.review").split()
    )
    assert "Prüfwerkzeuge oder Folgemodelle" in text


def test_default_review_is_build_and_forbids_further_models():
    default = " ".join(
        render_handoff(_issue(), "implement.review").split()
    )
    assert "Reviewziel: implement" in default
    assert "Prüfwerkzeuge oder Folgemodelle" in default


@pytest.mark.parametrize("target", WRITE_STATES)
def test_every_review_target_outputs_pass_changes_needs_decision(
    target,
):
    text = render_handoff(_issue(), f"{target}.review")
    assert "PASS oder die stärkste Befundklasse" in text


def test_review_line_names_effective_target():
    assert "Reviewziel: implement\n" in render_handoff(
        _issue(), "implement.review"
    )
    assert "Reviewziel: map\n" in render_handoff(
        _issue(), "map.review"
    )


@pytest.mark.parametrize(
    "step,expected",
    [
        ("map", "ki-dev -f map step KARTE map.review"),
        ("graph", "ki-dev -f graph step VORGANG graph.review"),
        (
            "materialize",
            "ki-dev -f materialize step x-1 materialize.review",
        ),
        ("implement", "implement implement=ANTWORT.json"),
    ],
)
def test_productive_steps_name_the_concrete_review_call(
    step, expected
):
    assert expected in render_handoff(_issue(), step)


def test_build_review_lists_criterion_refs_without_text():
    text = render_handoff(
        _issue(acceptance_criteria="1. Erstens GEHEIM\n2. Zweitens"),
        "implement.review",
    )
    assert "requirement_ref: AC1, AC2 (" in text
    assert "GEHEIM" not in text
    assert "als Antwort dieses Zustands" in " ".join(text.split())


def test_build_review_rejects_gapped_criterion_numbering():
    with pytest.raises(BeadInputInvalidError, match="fortlaufend"):
        render_handoff(
            _issue(acceptance_criteria="1. a\n3. b"), "implement.review"
        )


def test_build_review_states_requirement_ref_is_always_present():
    text = " ".join(
        render_handoff(_issue(), "implement.review").split()
    )
    assert "requirement_ref ist immer vorhanden" in text
    assert "bei fix \"AC<n>\", sonst null" in text


def test_validate_reports_gapped_criteria_for_build_review():
    issue = _issue(acceptance_criteria="1. a\n3. b")
    (problem,) = validate_for(issue, "implement.review")
    assert problem.startswith("acceptance_criteria:")
    assert validate_for(issue, "map.review") == ()
