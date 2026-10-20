"""Je README-Skript ein Test über den Dateinamen (ki-dev-ablauf-i6jl).

readme-scripts/<name>.sh gehört zu tests/readme/test_<name>.sh (oder
.py), ``-`` im Namen wird ``_``. Der Test steht im Ablauf
tests/readme/user-flow.sh und führt sein Skript per ``readme_run`` aus
oder ist ein Stub (``readme_test_missing``, Halbsatz im Test selbst).
Ohne Docker; ob die Tests grün sind, zeigt make readme-check.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path("readme-scripts")
TESTS = Path("tests/readme")
FLOW = TESTS / "user-flow.sh"
SUFFIXES = (".sh", ".py")
STUB = re.compile(r"^\s*readme_test_missing[\s(]", re.MULTILINE)


def test_every_readme_script_has_its_test():
    assert completeness_problems(ROOT) == []


def test_missing_test_fails(tmp_path):
    repo = _repo(tmp_path)
    (repo / TESTS / "test_1_a.sh").unlink()
    assert completeness_problems(repo) == [
        "FAIL: 1-a.sh: kein Test, kein Stub"
    ]


def test_test_outside_flow_fails(tmp_path):
    repo = _repo(tmp_path)
    (repo / FLOW).write_text(
        '# run_readme_test "$d/tests/readme/test_1_a.sh"\n'
    )
    assert completeness_problems(repo) == [
        "FAIL: tests/readme/test_1_a.sh: nicht im Ablauf"
    ]


def test_test_without_run_or_stub_fails(tmp_path):
    repo = _repo(tmp_path)
    (repo / TESTS / "test_1_a.sh").write_text("readme_run 2-b.sh\n")
    assert completeness_problems(repo) == [
        'FAIL: tests/readme/test_1_a.sh: weder readme_run "1-a.sh"'
        " noch readme_test_missing"
    ]


def test_stub_counts_as_test(tmp_path):
    repo = _repo(tmp_path)
    (repo / TESTS / "test_1_a.sh").write_text(
        'readme_test_missing "braucht X" "needs X"\n'
    )
    assert completeness_problems(repo) == []


def test_script_after_its_precondition_counts(tmp_path):
    repo = _repo(tmp_path)
    (repo / SCRIPTS / "0-vor.sh").write_text("echo vor\n")
    (repo / TESTS / "test_0_vor.sh").write_text("readme_run 0-vor.sh\n")
    (repo / TESTS / "test_1_a.sh").write_text(
        "readme_run 0-vor.sh 1-a.sh\n"
    )
    (repo / FLOW).write_text(
        'run_readme_test "$d/tests/readme/test_0_vor.sh"\n'
        'run_readme_test "$d/tests/readme/test_1_a.sh"\n'
    )
    assert completeness_problems(repo) == []


def test_precondition_alone_does_not_count(tmp_path):
    repo = _repo(tmp_path)
    (repo / TESTS / "test_1_a.sh").write_text(
        "readme_run 1-a.sh.alt 2-b.sh\n"
    )
    assert completeness_problems(repo) == [
        'FAIL: tests/readme/test_1_a.sh: weder readme_run "1-a.sh"'
        " noch readme_test_missing"
    ]


def test_python_test_is_accepted(tmp_path):
    repo = _repo(tmp_path)
    (repo / TESTS / "test_1_a.sh").unlink()
    (repo / TESTS / "test_1_a.py").write_text('readme_run("1-a.sh")\n')
    (repo / FLOW).write_text(
        'run_readme_test "$d/tests/readme/test_1_a.py"\n'
    )
    assert completeness_problems(repo) == []


def test_test_without_script_fails(tmp_path):
    repo = _repo(tmp_path)
    (repo / TESTS / "test_9_alt.sh").write_text("readme_run 9-alt.sh\n")
    assert completeness_problems(repo) == [
        "FAIL: tests/readme/test_9_alt.sh: kein Skript 9-alt.sh"
    ]


def completeness_problems(root: Path) -> list[str]:
    flow = (root / FLOW).read_text()
    problems = []
    for script in sorted(p.name for p in (root / SCRIPTS).glob("*.sh")):
        problems += script_problems(root, script, flow)
    return problems + orphan_problems(root)


def script_problems(root: Path, script: str, flow: str) -> list[str]:
    tests = [t for t in candidate_tests(script) if (root / t).is_file()]
    if not tests:
        return [f"FAIL: {script}: kein Test, kein Stub"]
    if len(tests) > 1:
        return [f"FAIL: {script}: zwei Tests {tests[0]}, {tests[1]}"]
    test = tests[0]
    problems = []
    if not called_in_flow(flow, test):
        problems.append(f"FAIL: {test}: nicht im Ablauf")
    if not runs_or_stubs((root / test).read_text(), script):
        problems.append(
            f'FAIL: {test}: weder readme_run "{script}"'
            " noch readme_test_missing"
        )
    return problems


def orphan_problems(root: Path) -> list[str]:
    problems = []
    for test in sorted((root / TESTS).glob("test_*")):
        script = script_name(test)
        if test.suffix not in SUFFIXES:
            continue
        if not (root / SCRIPTS / script).is_file():
            path = test.relative_to(root)
            problems.append(f"FAIL: {path}: kein Skript {script}")
    return problems


def candidate_tests(script: str) -> list[Path]:
    stem = script.removesuffix(".sh").replace("-", "_")
    return [TESTS / f"test_{stem}{suffix}" for suffix in SUFFIXES]


def script_name(test: Path) -> str:
    stem = test.stem.removeprefix("test_").replace("_", "-")
    return f"{stem}.sh"


def called_in_flow(flow: str, test: Path) -> bool:
    path = re.escape(test.as_posix())
    call = rf'^\s*run_readme_test\s+"?\S*{path}"?\s*$'
    return re.search(call, flow, re.MULTILINE) is not None


def runs_or_stubs(text: str, script: str) -> bool:
    """Das Skript als ein Argument von readme_run, auch nach anderen
    (mehrere Skripte in einer Shell)."""
    name = rf"[\"']?{re.escape(script)}[\"']?(?=[\s,)]|$)"
    run = rf"^\s*readme_run\b[^\n]*?[\s(,]{name}"
    return bool(re.search(run, text, re.MULTILINE) or STUB.search(text))


def _repo(tmp_path: Path) -> Path:
    """Ein Skript 1-a.sh mit Test im Ablauf: ohne Befund."""
    (tmp_path / SCRIPTS).mkdir(parents=True)
    (tmp_path / TESTS).mkdir(parents=True)
    (tmp_path / SCRIPTS / "1-a.sh").write_text("echo a\n")
    (tmp_path / TESTS / "test_1_a.sh").write_text("readme_run 1-a.sh\n")
    (tmp_path / FLOW).write_text(
        'run_readme_test "$d/tests/readme/test_1_a.sh"\n'
    )
    assert completeness_problems(tmp_path) == []
    return tmp_path
