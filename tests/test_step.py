from functools import partial

import pytest

from ki_dev.flow.planning import load_planning_flow
from ki_dev.ops.context.bead_input import (
    BeadInput,
    BeadInputInvalidError,
    validate_bead_input,
)
from ki_dev.ops.context.contract import ReviewTarget, Step
from tests.turn_helpers import render_handoff as _render_handoff

FLOW = load_planning_flow()
render_handoff = partial(_render_handoff, flow=FLOW)

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


@pytest.mark.parametrize("step", list(Step))
def test_complete_issue_is_valid_for_every_step(step):
    assert validate_bead_input(_issue(), step) == ()


@pytest.mark.parametrize("step", list(Step))
@pytest.mark.parametrize("field", ["id", "title", "description"])
@pytest.mark.parametrize("bad", [None, "", "  ", 3, ["x"]])
def test_common_fields_must_be_nonempty_strings(step, field, bad):
    assert validate_bead_input(_issue(**{field: bad}), step) == (field,)


@pytest.mark.parametrize(
    "step", [Step.MAP, Step.GRAPH, Step.MATERIALIZE]
)
@pytest.mark.parametrize("bad", [None, [], "a.md", [""], {"a": 1}])
def test_source_refs_required_for_map_graph_materialize(step, bad):
    problems = validate_bead_input(_issue(source_refs=bad), step)
    assert problems[0].startswith("metadata.handoff.source_refs")


def test_source_ref_problem_names_the_index():
    problems = validate_bead_input(
        _issue(source_refs=["ok", " ", 7]), Step.MAP
    )
    assert problems == (
        "metadata.handoff.source_refs[1]",
        "metadata.handoff.source_refs[2]",
    )


@pytest.mark.parametrize("step", [Step.IMPLEMENT, Step.REVIEW])
def test_build_review_need_no_metadata(step):
    assert validate_bead_input(_issue(source_refs=None), step) == ()


@pytest.mark.parametrize("step", [Step.IMPLEMENT, Step.REVIEW])
@pytest.mark.parametrize("field", ["acceptance_criteria", "design"])
@pytest.mark.parametrize("bad", [None, "", 5])
def test_build_review_require_contract_fields(step, field, bad):
    assert validate_bead_input(_issue(**{field: bad}), step) == (field,)


@pytest.mark.parametrize(
    "step", [Step.MAP, Step.GRAPH, Step.MATERIALIZE]
)
def test_map_graph_materialize_need_no_design_or_ac(step):
    issue = _issue(design=None, acceptance_criteria=None)
    assert validate_bead_input(issue, step) == ()


def test_all_problems_are_reported_together():
    issue = BeadInput()
    assert validate_bead_input(issue, Step.IMPLEMENT) == (
        "id",
        "title",
        "description",
        "acceptance_criteria",
        "design",
    )


@pytest.mark.parametrize("step", list(Step))
def test_render_is_deterministic_plain_and_dump_free(step):
    first = render_handoff(_issue(), step)
    assert first == render_handoff(_issue(), step)
    assert f"Schritt: {step.value}" in first
    assert "Bead: x-1 - Titel" in first
    assert "\x1b" not in first
    assert "GEHEIMER-DUMP" not in first
    assert "Design-Text" not in first
    assert "AC-Text" not in first
    assert first.endswith("\n")


def test_render_roles_are_distinct():
    roles = {step: render_handoff(_issue(), step) for step in Step}
    assert "Kartierungsagent" in roles[Step.MAP]
    assert "Abschnittsabdeckung" in roles[Step.MAP]
    assert "Auflösungsagent" in roles[Step.GRAPH]
    assert "dünne Vorgänge" in roles[Step.GRAPH]
    assert "Materialisierungsagent" in roles[Step.MATERIALIZE]
    assert "ausführungsreif" in roles[Step.MATERIALIZE]
    assert "Umsetzer" in roles[Step.IMPLEMENT]
    assert "Review-Agent" in roles[Step.REVIEW]
    assert "PASS oder die stärkste Befundklasse" in roles[Step.REVIEW]


def test_source_refs_only_in_reference_steps():
    for step in (Step.MAP, Step.GRAPH, Step.MATERIALIZE):
        text = render_handoff(_issue(), step)
        assert "- docs/design/a.md#L12-L40\n- bd:karte\n" in text
    for step in (Step.IMPLEMENT, Step.REVIEW):
        assert "docs/design/a.md" not in render_handoff(_issue(), step)


def test_review_hands_no_notes_or_self_assessment_to_reviewer():
    text = render_handoff(_issue(), Step.REVIEW)
    assert "nicht als Bewertungsinput" in " ".join(text.split())
    assert "GEHEIMER-DUMP" not in text


def test_successor_is_only_a_human_hint():
    for step in Step:
        assert "Hinweis für den Menschen:" in render_handoff(
            _issue(), step
        )


def test_title_control_characters_and_newlines_are_flattened():
    text = render_handoff(
        _issue(title="A\x1b[31mB\nC\t[bold]D"), Step.IMPLEMENT
    )
    assert "\x1b" not in text
    assert "Bead: x-1 - A[31mB C [bold]D\n" in text


def test_render_refuses_invalid_issue():
    with pytest.raises(BeadInputInvalidError) as info:
        render_handoff(_issue(design=None), Step.IMPLEMENT)
    assert info.value.problems == ("design",)


def test_core_imports_no_cli_or_process_modules():
    import subprocess
    import sys

    code = (
        "import sys, ki_dev.runner.turns,"
        " ki_dev.ops.context.bead_input;"
        "bad = {'typer', 'rich', 'subprocess',"
        " 'ki_dev.ops.context.beads_reader'};"
        "sys.exit(int(bool(bad & set(sys.modules))))"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_build_may_test_review_may_not():
    """Build darf gezielt testen (kein pauschales Werkzeugverbot);
    Review startet selbst keine Prüfwerkzeuge, darf aber lesen und
    Testqualität/Abdeckung beurteilen (AC1/AC2)."""
    build = " ".join(render_handoff(_issue(), Step.IMPLEMENT).split())
    review = " ".join(render_handoff(_issue(), Step.REVIEW).split())

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


@pytest.mark.parametrize("step", list(Step))
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
    text = render_handoff(issue, Step.IMPLEMENT)
    instruction = "Die Epic-Hinweise vermitteln"
    assert text.count(instruction) == 1
    assert text.index(instruction) < text.index("Epic-Hinweis (outer)")
    assert text.index("Epic-Hinweis (outer)") < text.index(
        "Epic-Hinweis (inner)"
    )


@pytest.mark.parametrize("step", list(Step))
def test_no_epic_context_adds_no_instruction(step):
    text = render_handoff(_issue(), step)
    assert "Die Epic-Hinweise vermitteln" not in text
    assert "Epic-Hinweis (" not in text


# --- ReviewTarget (--review-of) -------------------------------------


SOURCE_TARGETS = (
    ReviewTarget.MAP,
    ReviewTarget.GRAPH,
    ReviewTarget.MATERIALIZE,
)


def test_review_without_target_equals_build_target():
    assert render_handoff(_issue(), Step.REVIEW) == render_handoff(
        _issue(), Step.REVIEW, ReviewTarget.IMPLEMENT
    )
    assert validate_bead_input(
        _issue(), Step.REVIEW
    ) == validate_bead_input(
        _issue(), Step.REVIEW, ReviewTarget.IMPLEMENT
    )


@pytest.mark.parametrize("target", SOURCE_TARGETS)
def test_source_review_targets_require_source_refs(target):
    problems = validate_bead_input(
        _issue(source_refs=None), Step.REVIEW, target
    )
    assert problems[0].startswith("metadata.handoff.source_refs")


@pytest.mark.parametrize(
    "target", [ReviewTarget.MAP, ReviewTarget.GRAPH]
)
def test_map_graph_review_need_no_design_or_ac(target):
    issue = _issue(design=None, acceptance_criteria=None)
    assert validate_bead_input(issue, Step.REVIEW, target) == ()


def test_materialize_review_needs_refs_and_contract_fields():
    target = ReviewTarget.MATERIALIZE
    assert validate_bead_input(_issue(), Step.REVIEW, target) == ()

    missing_refs = validate_bead_input(
        _issue(source_refs=None), Step.REVIEW, target
    )
    assert missing_refs[0].startswith("metadata.handoff.source_refs")

    missing_design = validate_bead_input(
        _issue(design=None), Step.REVIEW, target
    )
    assert missing_design == ("design",)


def test_build_review_target_needs_no_source_refs():
    issue = _issue(source_refs=None)
    problems = validate_bead_input(
        issue, Step.REVIEW, ReviewTarget.IMPLEMENT
    )
    assert problems == ()


@pytest.mark.parametrize("target", SOURCE_TARGETS)
def test_source_review_targets_render_source_refs(target):
    text = render_handoff(_issue(), Step.REVIEW, target)
    assert "- docs/design/a.md#L12-L40\n- bd:karte\n" in text


def test_build_review_target_does_not_render_source_refs():
    assert "docs/design/a.md" not in render_handoff(
        _issue(), Step.REVIEW, ReviewTarget.IMPLEMENT
    )


def test_review_targets_have_distinct_role_texts():
    texts = {
        target: render_handoff(_issue(), Step.REVIEW, target)
        for target in ReviewTarget
    }
    assert "Kartenprüfung" in texts[ReviewTarget.MAP]
    assert "Graphprüfung" in texts[ReviewTarget.GRAPH]
    assert (
        "Materialisierungsprüfung" in texts[ReviewTarget.MATERIALIZE]
    )
    assert "deterministischen Vorlauf" in texts[ReviewTarget.IMPLEMENT]
    for target in SOURCE_TARGETS:
        assert "deterministischen Vorlauf" not in texts[target]


def test_materialize_review_transports_ac3_criteria():
    text = " ".join(
        render_handoff(
            _issue(), Step.REVIEW, ReviewTarget.MATERIALIZE
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
            issue, Step.REVIEW, ReviewTarget.MATERIALIZE
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
            issue, Step.REVIEW, ReviewTarget.MATERIALIZE
        ).split()
    )
    assert "automatische Freigaben" not in text
    assert "Geltungsbereich" in text
    assert "Nicht-Ziele" in text
    assert (
        "Benenne Übergröße, widersprüchliche Nachträge und nötige "
        "Teilung mit betroffenem Abschnitt" in text
    )


@pytest.mark.parametrize("target", list(ReviewTarget))
def test_all_review_targets_forbid_own_tooling_or_further_models(
    target,
):
    text = " ".join(
        render_handoff(_issue(), Step.REVIEW, target).split()
    )
    assert "Prüfwerkzeuge oder Folgemodelle" in text


def test_default_review_is_build_and_forbids_further_models():
    default = " ".join(
        render_handoff(_issue(), Step.REVIEW).split()
    )
    assert "Reviewziel: implement" in default
    assert "Prüfwerkzeuge oder Folgemodelle" in default


@pytest.mark.parametrize("target", list(ReviewTarget))
def test_every_review_target_outputs_pass_changes_needs_decision(
    target,
):
    text = render_handoff(_issue(), Step.REVIEW, target)
    assert "PASS oder die stärkste Befundklasse" in text


def test_review_line_names_effective_target():
    assert "Reviewziel: implement\n" in render_handoff(
        _issue(), Step.REVIEW
    )
    assert "Reviewziel: map\n" in render_handoff(
        _issue(), Step.REVIEW, ReviewTarget.MAP
    )


@pytest.mark.parametrize(
    "step,expected",
    [
        (Step.MAP, "--review-of map"),
        (Step.GRAPH, "--review-of graph"),
        (Step.MATERIALIZE, "--review-of materialize"),
        (Step.IMPLEMENT, "--step review"),
    ],
)
def test_productive_steps_name_the_concrete_review_call(
    step, expected
):
    assert expected in render_handoff(_issue(), step)


def test_build_review_lists_criterion_refs_without_text():
    text = render_handoff(
        _issue(acceptance_criteria="1. Erstens GEHEIM\n2. Zweitens"),
        Step.REVIEW,
    )
    assert "requirement_ref: AC1, AC2 (" in text
    assert "GEHEIM" not in text
    assert "--decision-file" in text


def test_build_review_rejects_gapped_criterion_numbering():
    with pytest.raises(BeadInputInvalidError, match="fortlaufend"):
        render_handoff(
            _issue(acceptance_criteria="1. a\n3. b"), Step.REVIEW
        )


def test_build_review_states_requirement_ref_is_always_present():
    text = " ".join(render_handoff(_issue(), Step.REVIEW).split())
    assert "requirement_ref ist immer vorhanden" in text
    assert "bei fix \"AC<n>\", sonst null" in text


@pytest.mark.parametrize("target", [None, ReviewTarget.IMPLEMENT])
def test_validate_reports_gapped_criteria_for_build_review(target):
    issue = _issue(acceptance_criteria="1. a\n3. b")
    (problem,) = validate_bead_input(issue, Step.REVIEW, target)
    assert problem.startswith("acceptance_criteria:")
    assert (
        validate_bead_input(issue, Step.REVIEW, ReviewTarget.MAP) == ()
    )
