import pytest

from ki_dev.handoff import (
    HandoffInvalidError,
    HandoffIssue,
    Step,
    render_handoff,
    validate_handoff,
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
    return HandoffIssue(**(values | changes))


@pytest.mark.parametrize("step", list(Step))
def test_complete_issue_is_valid_for_every_step(step):
    assert validate_handoff(_issue(), step) == ()


@pytest.mark.parametrize("step", list(Step))
@pytest.mark.parametrize("field", ["id", "title", "description"])
@pytest.mark.parametrize("bad", [None, "", "  ", 3, ["x"]])
def test_common_fields_must_be_nonempty_strings(step, field, bad):
    assert validate_handoff(_issue(**{field: bad}), step) == (field,)


@pytest.mark.parametrize(
    "step", [Step.MAP, Step.GRAPH, Step.MATERIALIZE]
)
@pytest.mark.parametrize("bad", [None, [], "a.md", [""], {"a": 1}])
def test_source_refs_required_for_map_graph_materialize(step, bad):
    problems = validate_handoff(_issue(source_refs=bad), step)
    assert problems[0].startswith("metadata.handoff.source_refs")


def test_source_ref_problem_names_the_index():
    problems = validate_handoff(
        _issue(source_refs=["ok", " ", 7]), Step.MAP
    )
    assert problems == (
        "metadata.handoff.source_refs[1]",
        "metadata.handoff.source_refs[2]",
    )


@pytest.mark.parametrize("step", [Step.BUILD, Step.REVIEW])
def test_build_review_need_no_metadata(step):
    assert validate_handoff(_issue(source_refs=None), step) == ()


@pytest.mark.parametrize("step", [Step.BUILD, Step.REVIEW])
@pytest.mark.parametrize("field", ["acceptance_criteria", "design"])
@pytest.mark.parametrize("bad", [None, "", 5])
def test_build_review_require_contract_fields(step, field, bad):
    assert validate_handoff(_issue(**{field: bad}), step) == (field,)


@pytest.mark.parametrize(
    "step", [Step.MAP, Step.GRAPH, Step.MATERIALIZE]
)
def test_map_graph_materialize_need_no_design_or_ac(step):
    issue = _issue(design=None, acceptance_criteria=None)
    assert validate_handoff(issue, step) == ()


def test_all_problems_are_reported_together():
    issue = HandoffIssue()
    assert validate_handoff(issue, Step.BUILD) == (
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
    assert "Bau-Agent" in roles[Step.BUILD]
    assert "Review-Agent" in roles[Step.REVIEW]
    assert "PASS | CHANGES | NEEDS_DECISION" in roles[Step.REVIEW]


def test_source_refs_only_in_reference_steps():
    for step in (Step.MAP, Step.GRAPH, Step.MATERIALIZE):
        text = render_handoff(_issue(), step)
        assert "- docs/design/a.md#L12-L40\n- bd:karte\n" in text
    for step in (Step.BUILD, Step.REVIEW):
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
        _issue(title="A\x1b[31mB\nC\t[bold]D"), Step.BUILD
    )
    assert "\x1b" not in text
    assert "Bead: x-1 - A[31mB C [bold]D\n" in text


def test_render_refuses_invalid_issue():
    with pytest.raises(HandoffInvalidError) as info:
        render_handoff(_issue(design=None), Step.BUILD)
    assert info.value.problems == ("design",)


def test_core_imports_no_cli_or_process_modules():
    import subprocess
    import sys

    code = (
        "import sys, ki_dev.handoff;"
        "bad = {'typer', 'rich', 'subprocess', 'ki_dev.beads_reader'};"
        "sys.exit(int(bool(bad & set(sys.modules))))"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_build_may_test_review_may_not():
    """Build darf gezielt testen (kein pauschales Werkzeugverbot);
    Review startet selbst keine Prüfwerkzeuge, darf aber lesen und
    Testqualität/Abdeckung beurteilen (AC1/AC2)."""
    build = " ".join(render_handoff(_issue(), Step.BUILD).split())
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
def test_every_step_includes_epic_guidance_with_origin(step):
    issue = _issue(
        epic_guidance=(("epic-1", "Kleine Umsetzungsschnitte."),)
    )
    text = render_handoff(issue, step)
    assert "Epic-Hinweis (epic-1):\nKleine Umsetzungsschnitte." in text
