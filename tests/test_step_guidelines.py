import builtins
import copy
import pathlib
import subprocess
import sys
from pathlib import Path

import pytest

from ki_dev.ops.checks.preflight import (
    PreflightReport,
)
from ki_dev.ops.context.bead_input import BeadInput
from ki_dev.ops.context.guidelines import (
    GUIDELINE_SOURCES,
    GuidelineContractError,
    GuidelineSection,
    parse_guideline_document,
    render_guideline_documents,
    select_common_guidelines,
    select_guidelines,
)
from ki_dev.ops.context.guidelines_source import (
    GuidelineSourceError,
    load_guidelines,
    sync_guideline_documents,
)
from tests.guideline_fixtures import guideline_data, write_guidelines
from tests.turn_helpers import (
    WRITE_STATES,
    render_base_handoff,
    render_handoff,
    render_review_handoff,
    select_for,
)

REPO = Path(__file__).resolve().parents[1]
SOURCE = GUIDELINE_SOURCES[0]


def _documents():
    return tuple(
        parse_guideline_document(source, guideline_data(f"Q{index}"))
        for index, source in enumerate(GUIDELINE_SOURCES)
    )


def _ids(sections, source=SOURCE):
    return [s.id for s in sections if s.source == str(source.path)]


def _issue():
    return BeadInput(
        id="x-1",
        title="Titel",
        description="Beschreibung",
        design="Design",
        acceptance_criteria="AC",
        source_refs=["a.md"],
    )


# ---------------------------------------------------------------------
# AC1: feste Auswahl common + task (+ review)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("step", WRITE_STATES)
def test_productive_step_selects_common_and_task(step):
    selected = select_for(_documents(), step)
    for source in GUIDELINE_SOURCES:
        assert _ids(selected, source) == [
            "common",
            "shared",
            f"{step}-task",
        ]


@pytest.mark.parametrize("target", WRITE_STATES)
def test_review_selects_common_task_and_review_of_target(target):
    selected = select_for(_documents(), f"{target}.review")
    for source in GUIDELINE_SOURCES:
        assert _ids(selected, source) == [
            "common",
            "shared",
            f"{target}-task",
            f"{target}-review",
        ]


def _with_map_common(ids):
    data = guideline_data("Q0")
    data["stages"]["map"]["common"] = ids
    return parse_guideline_document(SOURCE, data)


def test_stage_common_replaces_source_common():
    documents = (_with_map_common(["shared"]),)
    assert _ids(select_for(documents, "map")) == [
        "shared",
        "map-task",
    ]
    assert _ids(
        select_for(documents, "map.review")
    ) == ["shared", "map-task", "map-review"]


def test_stage_common_leaves_other_steps_and_local_unchanged():
    documents = (_with_map_common([]),)
    assert _ids(select_for(documents, "graph")) == [
        "common",
        "shared",
        "graph-task",
    ]
    assert _ids(select_common_guidelines(documents)) == [
        "common",
        "shared",
    ]


def test_stage_common_with_unknown_id_is_reference_problem():
    data = guideline_data("Q0")
    data["stages"]["map"]["common"] = ["geheim-id"]
    with pytest.raises(GuidelineContractError) as caught:
        parse_guideline_document(SOURCE, data)
    assert caught.value.problems == (
        "stages.map.common[0]: unbekannte Abschnitts-ID",
    )


def test_repository_map_gets_only_neutral_work_rules():
    """Kartierung ist bereichsneutral: keine Architektur-,
    Programmier- oder Technikregeln, nur Arbeitsregeln."""
    selected = select_for(load_guidelines(REPO), "map")
    assert [(Path(s.source).name, s.id) for s in selected] == [
        ("arbeitsregeln.de.yaml", "beads-lesen"),
        ("arbeitsregeln.de.yaml", "rollenrechte"),
        ("arbeitsregeln.de.yaml", "sitzungsende"),
    ]


def test_common_selection_has_no_stage_sections_and_keeps_order():
    selected = select_common_guidelines(_documents())
    for source in GUIDELINE_SOURCES:
        assert _ids(selected, source) == ["common", "shared"]
    sources = [s.source for s in selected]
    assert sources == sorted(sources, key=sources.index)
    assert sources[0] == str(GUIDELINE_SOURCES[0].path)


def test_repository_common_sections_cover_former_entry_texts():
    selected = select_common_guidelines(load_guidelines(REPO))
    ids = {(Path(s.source).name, s.id) for s in selected}
    assert {
        ("arbeitsregeln.de.yaml", "leitlinien-pflege"),
        ("arbeitsregeln.de.yaml", "beads-lesen"),
        ("arbeitsregeln.de.yaml", "rollenrechte"),
        ("arbeitsregeln.de.yaml", "sitzungsende"),
        ("arbeitsregeln.de.yaml", "python-pytest"),
        ("arbeitsregeln.de.yaml", "verbrauchsmessung"),
    } <= ids


def test_sources_keep_fixed_order_and_markdown():
    selected = select_for(_documents(), "implement")
    sources = [s.source for s in selected]
    assert sources == sorted(sources, key=sources.index)
    assert sources[0] == "docs/policies/programmierleitlinie.de.yaml"
    assert [str(source.path) for source in GUIDELINE_SOURCES] == [
        "docs/policies/programmierleitlinie.de.yaml",
        "docs/policies/technikleitlinie.de.yaml",
        "docs/policies/arbeitsregeln.de.yaml",
    ]
    assert sources[-1] == "docs/policies/arbeitsregeln.de.yaml"
    assert selected[0].text == "## Q0 common\n\n- Q0:common"


# Phasenschwerpunkte (Geltungsbereich): nur dort zugeordnet; alle
# übrigen Abschnitte gelten in jedem Schritt und Reviewziel außer der
# bereichsneutralen Kartierung (test_repository_map_gets_only_…).
_FOCUS = {
    "architektur-planung": {"graph", "materialize"},
    "programmierung-umsetzung": {"implement"},
    "docstrings": {"implement"},
}
_STATES = [
    state
    for phase in WRITE_STATES
    if phase != "map"
    for state in (phase, f"{phase}.review")
]


@pytest.mark.parametrize("state", _STATES)
def test_repository_mapping_keeps_full_reach(state):
    documents = load_guidelines(REPO)
    selected = select_for(documents, state)
    phase = state.partition(".")[0]
    for document in documents:
        expected = [
            sid
            for sid, _ in document.sections
            if phase in _FOCUS.get(sid, set(WRITE_STATES))
        ]
        assert _ids(selected, document.source) == expected


def test_focus_sections_exist_in_repository_source():
    prog = load_guidelines(REPO)[0]
    assert set(_FOCUS) <= {sid for sid, _ in prog.sections}


# ---------------------------------------------------------------------
# Rendering in der Übergabe (AC1, AC6)
# ---------------------------------------------------------------------


def test_block_follows_unchanged_base_with_source_labels():
    guidelines = (
        GuidelineSection("q.yaml", "a", "## A\n\n```py\nx = 1\n```"),
    )
    base = render_base_handoff(_issue(), "implement")
    text = render_handoff(
        _issue(), "implement", guidelines=guidelines
    )
    assert render_handoff(_issue(), "implement") == base
    assert text.startswith(base)
    block = text[len(base) :]
    assert "LEITLINIEN (mitgeliefert" in block
    assert "--- q.yaml#a ---\n## A\n\n```py\nx = 1\n```\n" in block


def test_long_guidelines_are_neither_cut_nor_part_of_base():
    long_text = "Regel " + "x" * 20_000
    guidelines = (GuidelineSection("q.yaml", "lang", long_text),)
    base = render_base_handoff(_issue(), "implement")
    text = render_handoff(
        _issue(), "implement", guidelines=guidelines
    )
    assert long_text in text
    assert len(base) < 4000 < len(text)
    assert text.startswith(base)


def test_build_review_puts_report_before_guidelines():
    report = PreflightReport(
        valid=True,
        started_at="2026-10-04T00:00:00Z",
        commands=(),
        artifact=".local/handoff/preflight/r.json",
    )
    guidelines = (GuidelineSection("q.yaml", "a", "REGEL"),)
    text = render_review_handoff(_issue(), report, guidelines)
    base = render_base_handoff(_issue(), "implement.review")
    assert text.startswith(base)
    assert text.index("PRUEFBERICHT") < text.index("LEITLINIEN")
    assert text.endswith("REGEL\n")


# ---------------------------------------------------------------------
# AC3: Vertrag und Referenzen
# ---------------------------------------------------------------------


def _problems(data) -> tuple[str, ...]:
    with pytest.raises(GuidelineContractError) as caught:
        parse_guideline_document(SOURCE, data)
    assert caught.value.source == SOURCE.path
    return caught.value.problems


def _mutated(change):
    data = copy.deepcopy(guideline_data("Q"))
    change(data)
    return data


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda d: d.update(title=7), "title: muss Text sein"),
        (
            lambda d: d.update(title="a\nb"),
            "title: muss nichtleerer einzeiliger Text sein",
        ),
        (lambda d: d.update(sections={}), "sections: muss Liste sein"),
        (
            lambda d: d.update(sections=[]),
            "sections: darf nicht leer sein",
        ),
        (
            lambda d: d["sections"][1].update(text=3),
            "sections[1].text: muss Text sein",
        ),
        (
            lambda d: d["sections"][1].update(text="  \n "),
            "sections[1].text: darf nicht leer sein",
        ),
        (
            lambda d: d["sections"][0].update(id="Gross Id"),
            "sections[0].id: ungültige Abschnitts-ID "
            "(erlaubt: a-z, 0-9, -)",
        ),
        (
            lambda d: d["stages"]["implement"].pop("review"),
            "stages.implement: Pflichtfeld review fehlt",
        ),
        (
            lambda d: d["stages"].update(
                Karte={"task": [], "review": []}
            ),
            "stages: ungültiger Phasenname (erlaubt: a-z, _)",
        ),
        (
            lambda d: d.update(extra="GEHEIM"),
            "(Wurzel): unbekanntes Feld",
        ),
        (
            lambda d: d["sections"][0].update(note="GEHEIM"),
            "sections[0]: unbekanntes Feld",
        ),
        (
            lambda d: d["stages"]["map"].update(task="common"),
            "stages.map.task: muss Liste sein",
        ),
        (
            lambda d: d.pop("common"),
            "(Wurzel): Pflichtfeld common fehlt",
        ),
    ],
)
def test_schema_problems_name_field_path(change, expected):
    assert expected in _problems(_mutated(change))


def test_root_must_be_mapping():
    assert _problems(None) == ("(Wurzel): muss Mapping sein",)


def test_duplicate_section_id_is_rejected():
    def duplicate(data):
        data["sections"][2]["id"] = "common"

    problems = _problems(_mutated(duplicate))
    assert "sections[2].id: doppelte Abschnitts-ID" in problems


def test_unknown_references_name_path_not_value():
    def unknown(data):
        data["common"].append("geheim-id")
        data["stages"]["implement"]["review"].insert(0, "geheim-id")

    problems = _problems(_mutated(unknown))
    assert problems == (
        "common[2]: unbekannte Abschnitts-ID",
        "stages.implement.review[0]: unbekannte Abschnitts-ID",
    )
    assert "geheim" not in " ".join(problems)


def test_problems_never_contain_rule_text():
    def bad(data):
        data["sections"][0]["text"] = ["GEHEIMER REGELTEXT"]

    assert "GEHEIM" not in " ".join(_problems(_mutated(bad)))


def test_core_does_no_file_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Dateizugriff im Kern")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(pathlib.Path, "read_text", forbidden)
    monkeypatch.setattr(pathlib.Path, "read_bytes", forbidden)
    documents = _documents()
    select_guidelines(documents, "materialize", True)
    render_guideline_documents(documents)


def test_stage_names_come_from_the_flows():
    """Welche Phasen es gibt, sagen die Abläufe; eine Quelle ohne die
    Phase eines Ablaufs fällt bei der Auswahl auf."""
    documents = _documents()
    with pytest.raises(GuidelineContractError, match="stages.nirgends"):
        select_guidelines(documents, "nirgends", False)


# ---------------------------------------------------------------------
# Quellen lesen (AC2-Fehlerpfade)
# ---------------------------------------------------------------------


def test_load_reads_all_sources_in_order(tmp_path):
    write_guidelines(tmp_path)
    documents = load_guidelines(tmp_path)
    assert [d.title for d in documents] == [
        "Titel Q0",
        "Titel Q1",
        "Titel Q2",
    ]


def test_missing_source_is_read_error(tmp_path):
    write_guidelines(tmp_path)
    (tmp_path / GUIDELINE_SOURCES[1].path).unlink()
    with pytest.raises(GuidelineSourceError, match="technikleitlinie"):
        load_guidelines(tmp_path)


def test_unreadable_source_is_read_error(tmp_path):
    write_guidelines(tmp_path)
    path = tmp_path / SOURCE.path
    path.unlink()
    path.mkdir()
    with pytest.raises(GuidelineSourceError, match="IsADirectoryError"):
        load_guidelines(tmp_path)


def test_invalid_yaml_names_line_without_raw_text(tmp_path):
    write_guidelines(tmp_path)
    (tmp_path / SOURCE.path).write_text("title: ok\nGEHEIM: [\n")
    with pytest.raises(GuidelineContractError) as caught:
        load_guidelines(tmp_path)
    [problem] = caught.value.problems
    assert problem.startswith("ungültiges YAML (Zeile ")
    assert "GEHEIM" not in problem


def test_non_utf8_source_is_contract_error(tmp_path):
    write_guidelines(tmp_path)
    (tmp_path / SOURCE.path).write_bytes(b"title: \xff\n")
    with pytest.raises(GuidelineContractError) as caught:
        load_guidelines(tmp_path)
    assert caught.value.problems == ("kein gültiges UTF-8",)


def test_yaml_tags_are_not_constructed(tmp_path):
    write_guidelines(tmp_path)
    (tmp_path / SOURCE.path).write_text(
        "title: !!python/object/apply:os.system ['true']\n"
    )
    with pytest.raises(GuidelineContractError):
        load_guidelines(tmp_path)


# ---------------------------------------------------------------------
# AC4: Dokumentgenerierung und Drift
# ---------------------------------------------------------------------


def test_repository_documents_match_sources():
    assert sync_guideline_documents(REPO, check=True) == ()


def test_rendered_document_keeps_front_matter_and_marks_generation():
    document = _documents()[0]
    text = render_guideline_documents((document,))[SOURCE.document]
    assert text.startswith(
        "---\nlayout: page\ntitle: Titel Q0\npermalink: /de/Q0/\n---\n"
        "<!-- Generiert aus docs/policies/programmierleitlinie.de.yaml"
    )
    assert "## Q0 common\n\n- Q0:common\n\n## Q0 shared" in text
    assert text.endswith("- Q0:implement-review\n")


def test_sync_writes_then_check_detects_drift_without_writing(tmp_path):
    write_guidelines(tmp_path)
    assert len(sync_guideline_documents(tmp_path, check=False)) == len(
        GUIDELINE_SOURCES
    )
    assert sync_guideline_documents(tmp_path, check=True) == ()
    target = tmp_path / SOURCE.document
    target.write_text("von Hand geändert\n")
    assert sync_guideline_documents(tmp_path, check=True) == (
        SOURCE.document,
    )
    assert target.read_text() == "von Hand geändert\n"


def _script(*args):
    return subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/render-guidelines.py"),
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_script_check_exits_1_on_drift_and_writes_nothing(tmp_path):
    write_guidelines(tmp_path)
    result = _script("--check", "--root", str(tmp_path))
    assert result.returncode == 1
    assert "docs/programmierleitlinie.de.md: weicht ab" in result.stdout
    assert not (tmp_path / SOURCE.document).exists()
    assert _script("--root", str(tmp_path)).returncode == 0
    assert _script("--check", "--root", str(tmp_path)).returncode == 0


def test_script_reports_contract_error_with_exit_2(tmp_path):
    write_guidelines(tmp_path)
    (tmp_path / SOURCE.path).write_text("title: [\n")
    result = _script("--check", "--root", str(tmp_path))
    assert result.returncode == 2
    assert "ungültiges YAML (Zeile" in result.stderr
