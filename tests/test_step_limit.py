"""Basisgrenze: reiner Kern, Rendering und Konfigurationsgrenze."""

from functools import partial
from pathlib import Path

import pytest

from ki_dev.flow.planning import lade_planungsablauf
from ki_dev.step.guidelines import GuidelineSection
from ki_dev.step.handoff import (
    HandoffIssue,
    ReviewTarget,
    Step,
)
from ki_dev.step.handoff import (
    render_base_handoff as _render_base_handoff,
)
from ki_dev.step.handoff import (
    render_handoff as _render_handoff,
)
from ki_dev.step.limit import (
    DEFAULT_BASE_MAX_CHARS,
    MAX_DIAGNOSIS_CHARS,
    HandoffBaseTooLongError,
    check_base_length,
)
from ki_dev.step.limit_config import (
    LimitConfigInvalidError,
    LimitConfigReadError,
    base_max_chars_from,
    load_base_max_chars,
)

FLOW = lade_planungsablauf()
render_handoff = partial(_render_handoff, flow=FLOW)
render_base_handoff = partial(_render_base_handoff, flow=FLOW)

SECRET = "GEHEIMER-ROHWERT"

# Alle Schritte und Reviewziele; Review ohne Ziel ist build.
COMBINATIONS = [
    (Step.MAP, None),
    (Step.GRAPH, None),
    (Step.MATERIALIZE, None),
    (Step.BUILD, None),
    (Step.REVIEW, None),
    (Step.REVIEW, ReviewTarget.MAP),
    (Step.REVIEW, ReviewTarget.GRAPH),
    (Step.REVIEW, ReviewTarget.MATERIALIZE),
    (Step.REVIEW, ReviewTarget.BUILD),
]


def _issue(title="Titel", epic=(), refs=("a.md#L1",)) -> HandoffIssue:
    return HandoffIssue(
        id="x-1",
        title=title,
        description="Beschreibung",
        design="Design",
        acceptance_criteria="AC",
        source_refs=list(refs),
        epic_context=tuple(epic),
    )


def _base(step, target, **issue_fields) -> str:
    return render_handoff(_issue(**issue_fields), step, target)


def _padded_title(step, target, size: int) -> str:
    """Mehrbyte-Titel für genau ``size`` Zeichen Basis."""
    empty = len(_base(step, target, title="ä"))
    return "ä" * (size - empty + 1)


# --- reiner Kern ----------------------------------------------------


@pytest.mark.parametrize("size", [3999, 4000])
def test_length_up_to_the_limit_is_allowed(size):
    check_base_length("ä\n" * (size // 2) + "x" * (size % 2), 4000, [])


def test_length_above_the_limit_is_rejected():
    with pytest.raises(HandoffBaseTooLongError) as error:
        check_base_length("x" * 4001, 4000, [("title", 3)])
    assert (error.value.actual, error.value.limit) == (4001, 4000)


def test_unicode_characters_not_bytes_are_counted():
    # 4000 Zeichen, aber 8000 Bytes.
    check_base_length("ä" * 4000, 4000, [])
    with pytest.raises(HandoffBaseTooLongError):
        check_base_length("😀" * 4001, 4000, [])


def test_newlines_and_spaces_count():
    with pytest.raises(HandoffBaseTooLongError):
        check_base_length("\n" * 2000 + " " * 2001, 4000, [])


def test_diagnosis_names_actual_limit_and_shares_without_values():
    fields = [("title", 12), ("epic_context[0]", 600)]
    error = HandoffBaseTooLongError(4321, 4000, fields)
    text = str(error)
    assert "4321" in text and "4000" in text
    assert "base_max_chars" in text
    assert text.index("epic_context[0] 600") < text.index("title 12")
    assert len(text) <= MAX_DIAGNOSIS_CHARS


def test_diagnosis_stays_within_1000_chars_with_many_fields():
    fields = [(f"source_refs[{i}]", 100 + i) for i in range(500)]
    error = HandoffBaseTooLongError(99999, 4000, fields)
    note = " ".join(["Notiz"] * 10)
    for text in (str(error), error.diagnosis(note)):
        assert len(text) <= MAX_DIAGNOSIS_CHARS
        assert "weitere)" in text
    assert error.diagnosis(note).endswith(note)


def test_diagnosis_without_fields_is_still_valid():
    text = str(HandoffBaseTooLongError(5, 4, []))
    assert "5 Zeichen" in text and "Anteile" not in text


# --- Rendering ------------------------------------------------------


@pytest.mark.parametrize(("step", "target"), COMBINATIONS)
@pytest.mark.parametrize(
    ("size", "allowed"), [(3999, True), (4000, True), (4001, False)]
)
def test_rendered_base_boundary_for_every_step(
    step, target, size, allowed
):
    title = _padded_title(step, target, size)
    assert len(_base(step, target, title=title)) == size
    if allowed:
        text = render_handoff(
            _issue(title=title), step, target, base_max_chars=4000
        )
        assert len(text) == size
        return
    with pytest.raises(HandoffBaseTooLongError):
        render_handoff(
            _issue(title=title), step, target, base_max_chars=4000
        )


def test_default_limit_is_4000_and_fits_every_step_with_one_epic():
    epic = [("ep", "E" * 600)]
    for step, target in COMBINATIONS:
        text = _base(step, target, epic=epic)
        assert len(text) <= DEFAULT_BASE_MAX_CHARS, (step, target)


def test_without_limit_nothing_is_checked():
    text = render_handoff(_issue(title="T" * 9000), Step.BUILD, None)
    assert len(text) > 9000


def test_guidelines_are_not_counted():
    title = _padded_title(Step.BUILD, None, 4000)
    sections = [
        GuidelineSection(
            source="doc.yaml", id="a", text="Regel " * 3000
        )
    ]
    text = render_handoff(
        _issue(title=title),
        Step.BUILD,
        None,
        sections,
        base_max_chars=4000,
    )
    assert len(text) >= 4000 + 17000
    assert "Regel " * 3000 in text


def test_epic_context_and_source_refs_count_to_the_base():
    step = Step.MATERIALIZE
    size = len(_base(step, None))
    with pytest.raises(HandoffBaseTooLongError) as error:
        render_handoff(
            _issue(epic=[("ep", SECRET)]),
            step,
            None,
            base_max_chars=size,
        )
    assert "epic_context[0]" in str(error.value)
    with pytest.raises(HandoffBaseTooLongError) as error:
        render_handoff(
            _issue(refs=["a.md", SECRET + "x"]),
            step,
            None,
            base_max_chars=size,
        )
    assert "source_refs[1]" in str(error.value)
    assert SECRET not in str(error.value)


def test_reading_hint_counts_to_the_base():
    plain = render_base_handoff(_issue(), Step.MAP)
    hint = "Hinweis " * 10
    both = render_base_handoff(_issue(), Step.MAP, reading_hint=hint)
    assert both == f"{plain}\n{hint}\n"
    with pytest.raises(HandoffBaseTooLongError) as error:
        render_base_handoff(
            _issue(),
            Step.MAP,
            reading_hint=hint,
            max_chars=len(plain),
        )
    assert "Lesehinweis" in str(error.value)


def test_diagnosis_does_not_contain_the_title_text():
    with pytest.raises(HandoffBaseTooLongError) as error:
        render_handoff(
            _issue(title=SECRET * 400),
            Step.BUILD,
            None,
            base_max_chars=100,
        )
    assert SECRET not in str(error.value)
    assert len(str(error.value)) <= MAX_DIAGNOSIS_CHARS


# --- Konfiguration (im Speicher) ------------------------------------


def _doc(value) -> dict:
    return {"tool": {"ki-dev": {"handoff": {"base_max_chars": value}}}}


@pytest.mark.parametrize(
    "document",
    [{}, {"tool": {}}, {"tool": {"ki-dev": {"handoff": {}}}}],
)
def test_missing_optional_value_uses_default(document):
    assert base_max_chars_from(document) == 4000


def test_other_valid_value_wins_and_siblings_are_ignored():
    document = _doc(1234)
    document["tool"]["ki-dev"]["handoff"]["feedback_max_chars"] = 5
    assert base_max_chars_from(document) == 1234


@pytest.mark.parametrize(
    "value", [None, True, False, 4000.0, 0, -1, "4000", [4000], {}]
)
def test_present_invalid_value_is_rejected_with_field_path(value):
    with pytest.raises(LimitConfigInvalidError) as error:
        base_max_chars_from(_doc(value))
    assert (
        "tool.ki-dev.handoff.base_max_chars muss eine positive ganze "
        "Zahl sein" in str(error.value)
    )


@pytest.mark.parametrize(
    ("document", "path"),
    [
        ({"tool": 7}, "tool"),
        ({"tool": {"ki-dev": "x"}}, "tool.ki-dev"),
        ({"tool": {"ki-dev": {"handoff": [1]}}}, "tool.ki-dev.handoff"),
    ],
)
def test_wrong_table_type_is_rejected_not_treated_as_missing(
    document, path
):
    with pytest.raises(LimitConfigInvalidError) as error:
        base_max_chars_from(document)
    assert f"{path} muss eine Tabelle sein" in str(error.value)


def test_diagnosis_never_contains_the_raw_value():
    with pytest.raises(LimitConfigInvalidError) as error:
        base_max_chars_from(_doc(SECRET))
    assert SECRET not in str(error.value)


# --- Konfiguration (Datei) ------------------------------------------


def _write(root: Path, text: str) -> None:
    (root / "pyproject.toml").write_text(text, encoding="utf-8")


def test_missing_file_uses_default(tmp_path):
    assert load_base_max_chars(tmp_path) == 4000


def test_value_is_read_from_the_table(tmp_path):
    _write(tmp_path, "[tool.ki-dev.handoff]\nbase_max_chars = 777\n")
    assert load_base_max_chars(tmp_path) == 777


def test_file_without_the_table_uses_default(tmp_path):
    _write(tmp_path, "[project]\nname = 'x'\n")
    assert load_base_max_chars(tmp_path) == 4000


@pytest.mark.parametrize(
    "value", ["4000.0", "true", "0", "-5", '"4000"', "[1]"]
)
def test_invalid_toml_value_is_exit_2_error(tmp_path, value):
    _write(
        tmp_path, f"[tool.ki-dev.handoff]\nbase_max_chars = {value}\n"
    )
    with pytest.raises(LimitConfigInvalidError):
        load_base_max_chars(tmp_path)


def test_defective_toml_is_invalid_not_default(tmp_path):
    _write(tmp_path, "[tool.ki-dev.handoff\nbase_max_chars = \n")
    with pytest.raises(LimitConfigInvalidError) as error:
        load_base_max_chars(tmp_path)
    assert "kein gültiges TOML" in str(error.value)


def test_toml_diagnosis_does_not_echo_raw_key_names(tmp_path):
    _write(
        tmp_path,
        f"[{SECRET}]\na = 1\n[{SECRET}]\nb = 2\n",
    )
    with pytest.raises(LimitConfigInvalidError) as error:
        load_base_max_chars(tmp_path)
    assert SECRET not in str(error.value)
    assert "kein gültiges TOML" in str(error.value)


def test_non_utf8_file_is_invalid(tmp_path):
    (tmp_path / "pyproject.toml").write_bytes(b"\xff\xfe\x00x")
    with pytest.raises(LimitConfigInvalidError):
        load_base_max_chars(tmp_path)


def test_unreadable_file_is_a_read_error(tmp_path):
    (tmp_path / "pyproject.toml").mkdir()
    with pytest.raises(LimitConfigReadError):
        load_base_max_chars(tmp_path)
