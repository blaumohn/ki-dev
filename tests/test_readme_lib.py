"""tests/readme/lib.sh: Ergebnisdatei je Skript, Stub, Fehlerpfad.

Fake-Skripte und Fake-Tests gegen die echte lib.sh, ohne Docker
(ki-dev-ablauf-i6jl).
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest
from plumbum import local

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "tests/readme/lib.sh"
HEADER = f'source "{LIB}"\n'


@pytest.fixture
def env(tmp_path):
    scripts = tmp_path / "readme-scripts"
    scripts.mkdir()
    (scripts / "1-ok.sh").write_text("echo eins\necho zwei\n")
    (scripts / "2-boom.sh").write_text(
        f'echo "Log in {tmp_path}/x"\nfalse\necho nie\n'
    )
    (tmp_path / "tests").mkdir()
    return {
        "README_SCRIPTS_DIR": str(scripts),
        "README_RESULTS_DIR": str(tmp_path / "ergebnisse"),
        "README_LOG_DIR": str(tmp_path / "logs"),
    }


def test_passed_writes_entry_with_excerpt(env, tmp_path):
    test = _test(
        tmp_path,
        "test_1_ok.sh",
        "readme_run 1-ok.sh\n"
        'printf "zwei\\n" >"$README_LOG.auszug"\n'
        'readme_result passed "$README_LOG.auszug"\n',
    )
    code, out, _ = _run(env, test)
    assert code == 0
    assert out == "eins\nzwei\n"
    [entry] = _entries(env, "1-ok")
    assert list(entry) == [
        "skript", "parameter", "ergebnis", "datum", "auszug",
    ]
    assert entry["skript"] == "1-ok.sh"
    assert entry["parameter"] == {}
    assert entry["ergebnis"] == "passed"
    assert entry["auszug"] == ["zwei"]
    stamp = datetime.datetime.fromisoformat(entry["datum"])
    assert stamp.tzinfo == datetime.UTC


def test_stub_writes_both_half_sentences(env, tmp_path):
    test = _test(
        tmp_path,
        "test_1_ok.sh",
        'readme_test_missing "braucht Agenten" "needs agents"\n'
        "echo nie\n",
    )
    code, out, err = _run(env, test)
    assert code == 0
    assert "nie" not in out
    assert "1-ok.sh: noch kein Test (Stub): braucht Agenten" in err
    [entry] = _entries(env, "1-ok")
    assert entry["ergebnis"] == "stub"
    assert entry["grund_de"] == "braucht Agenten"
    assert entry["grund_en"] == "needs agents"
    assert "auszug" not in entry


def test_stub_without_english_half_sentence_fails(env, tmp_path):
    test = _test(
        tmp_path, "test_1_ok.sh", 'readme_test_missing "nur DE" ""\n'
    )
    code, _, err = _run(env, test)
    assert code != 0
    assert "Stub ohne Halbsatz DE/EN" in err
    assert _entries(env, "1-ok")[0]["ergebnis"] == "failed"


def test_failing_command_is_failed_without_excerpt(env, tmp_path):
    test = _test(
        tmp_path,
        "test_2_boom.sh",
        "readme_run 2-boom.sh\nreadme_result passed\n",
    )
    code, _, err = _run(env, test)
    assert code != 0
    [entry] = _entries(env, "2-boom")
    assert entry["ergebnis"] == "failed"
    assert "auszug" not in entry
    # Diagnose mit Log-Pfad und letzten Zeilen nur auf stderr
    log = Path(env["README_LOG_DIR"]) / "2-boom.log"
    assert f"Log: {log}" in err
    assert f"Log in {tmp_path}/x" in err
    assert str(tmp_path) not in json.dumps(entry)


def test_failing_effect_check_is_failed(env, tmp_path):
    test = _test(
        tmp_path,
        "test_1_ok.sh",
        "readme_run 1-ok.sh\n"
        'grep -q drei "$README_LOG"\n'
        "readme_result passed\n",
    )
    code, _, err = _run(env, test)
    assert code != 0
    assert "test_1_ok.sh fehlgeschlagen" in err
    [entry] = _entries(env, "1-ok")
    assert entry["ergebnis"] == "failed"
    assert "auszug" not in entry


def test_test_without_result_is_failed(env, tmp_path):
    test = _test(tmp_path, "test_1_ok.sh", "readme_run 1-ok.sh\n")
    code, _, err = _run(env, test)
    assert code == 1
    assert "endete ohne Ergebnis" in err
    assert _entries(env, "1-ok")[0]["ergebnis"] == "failed"


@pytest.mark.parametrize(
    ("excerpt", "message"),
    [
        ("x\n" * 16, "Auszug mit 16 Zeilen, höchstens 15"),
        ("ok\n/tmp/abc/run\n", "Zeile 2 enthält einen lokalen Pfad"),
    ],
)
def test_unstable_excerpt_is_rejected(env, tmp_path, excerpt, message):
    (tmp_path / "auszug").write_text(excerpt)
    test = _test(
        tmp_path,
        "test_1_ok.sh",
        "readme_run 1-ok.sh\n"
        f'readme_result passed "{tmp_path}/auszug"\n',
    )
    code, _, err = _run(env, test)
    assert code != 0
    assert message in err
    assert _entries(env, "1-ok")[0]["ergebnis"] == "failed"


def _test(tmp_path, name, body):
    test = tmp_path / "tests" / name
    test.write_text(HEADER + body)
    return test


def _run(env, test):
    program = 'source "$1"; run_readme_test "$2"'
    with local.env(**env):
        return local["bash"].run(
            args=["-c", program, "_", LIB, test],
            retcode=None,
            timeout=30,
        )


def _entries(env, stem):
    path = Path(env["README_RESULTS_DIR"]) / f"{stem}.json"
    return json.loads(path.read_text())
