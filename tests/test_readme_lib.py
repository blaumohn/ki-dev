"""tests/readme/lib.sh: Ergebnisdatei je Skript, Stub, Fehlerpfad.

Fake-Skripte und Fake-Tests gegen die echte lib.sh, ohne Docker
(ki-dev-ablauf-i6jl); jede Ergebnisdatei erfüllt RESULT_SCHEMA aus
scripts/readme_results.py, den Vertrag des Renderers.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
from pathlib import Path

import pytest
from plumbum import local

from ki_dev.adapter.executors.claude_cli import ClaudeCliAdapter
from ki_dev.adapter.executors.codex_cli import CodexCliAdapter

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "tests/readme/lib.sh"
HEADER = f'source "{LIB}"\n'
_SPEC = importlib.util.spec_from_file_location(
    "readme_results", ROOT / "scripts/readme_results.py"
)
readme_results = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(readme_results)


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
    assert "1-ok.sh: ungeprüft (Stub): braucht Agenten" in err
    [entry] = _entries(env, "1-ok")
    assert entry["ergebnis"] == "stub"
    assert entry["grund_de"] == "braucht Agenten"
    assert entry["grund_en"] == "needs agents"
    assert "auszug" not in entry


def test_stub_without_english_reason_fails(env, tmp_path):
    test = _test(
        tmp_path, "test_1_ok.sh", 'readme_test_missing "nur DE" ""\n'
    )
    code, _, err = _run(env, test)
    assert code != 0
    assert "Stub ohne Halbsatz DE/EN" in err
    assert _entries(env, "1-ok")[0]["ergebnis"] == "failed"


def test_failing_command_is_failed(env, tmp_path):
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


def test_failing_command_in_substitution_aborts(env, tmp_path):
    test = _test(
        tmp_path,
        "test_1_ok.sh",
        "readme_log_file() { false; echo verdeckt; }\n"
        "readme_run 1-ok.sh\n"
        "readme_result passed\n",
    )
    code, out, _ = _run(env, test)
    assert code != 0
    assert "eins" not in out
    assert _entries(env, "1-ok")[0]["ergebnis"] == "failed"


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


def test_scripts_share_one_shell(env, tmp_path):
    """Wie im selben Terminal: Variable und Verzeichnis gehen weiter."""
    scripts = Path(env["README_SCRIPTS_DIR"])
    (scripts / "3-vor.sh").write_text(f'X=vor\ncd "{tmp_path}"\n')
    (scripts / "4-nach.sh").write_text('echo "$X $PWD"\n')
    test = _test(
        tmp_path,
        "test_4_nach.sh",
        "readme_run 3-vor.sh 4-nach.sh\n"
        'cp "$README_LOG" "$README_LOG.kopie"\n'
        "readme_result passed\n",
    )
    code, out, err = _run(env, test)
    assert code == 0, err
    assert out == f"vor {tmp_path}\n"
    log = Path(env["README_LOG_DIR"]) / "4-nach.log.kopie"
    assert log.read_text() == out
    [entry] = _entries(env, "4-nach")
    assert entry["ergebnis"] == "passed"


def test_workdir_is_where_the_session_ended(env, tmp_path):
    """readme_workdir nennt das Verzeichnis am Ende der Sitzung, auch
    wenn ein Skript in ein mktemp-Verzeichnis außerhalb von TMPDIR
    wechselt (macOS ohne gesetztes TMPDIR)."""
    target = tmp_path / "wo" / "versions-work"
    target.mkdir(parents=True)
    scripts = Path(env["README_SCRIPTS_DIR"])
    (scripts / "3-wechsel.sh").write_text(f'cd "{target}"\n')
    test = _test(
        tmp_path,
        "test_3_wechsel.sh",
        "readme_run 3-wechsel.sh\n"
        'echo "$(readme_workdir)" >&2\n'
        "readme_result passed\n",
    )
    code, _, err = _run(env, test)
    assert code == 0, err
    assert f"{target}\n" in err


def test_workdir_fails_when_the_session_broke_off(env, tmp_path):
    test = _test(
        tmp_path,
        "test_2_boom.sh",
        "readme_run 2-boom.sh || true\n"
        "readme_workdir\n"
        "readme_result passed\n",
    )
    code, _, err = _run(env, test)
    assert code != 0
    assert "Sitzung endete vor dem letzten Befehl" in err


@pytest.mark.parametrize(
    "adapter", [CodexCliAdapter, ClaudeCliAdapter], ids=["codex", "claude"]
)
def test_agent_stub_passes_version_probe_then_fails_turn(adapter):
    """Der Platzhalter aus readme_without_agents besteht die
    Versionsprobe der Adapter mit dem Pin aus tool-versions.json; erst
    der Turn selbst scheitert (test_5_starten.sh erwartet diesen
    Fehler, nicht die Ablehnung einer ungeprüften Version)."""
    cli = adapter()
    program = 'source "$1"; readme_without_agents; "$2" --version'
    version = local["bash"]("-c", program, "_", LIB, cli.executable)
    assert cli.parse_version(version) == cli.cli_version_pin
    program = 'source "$1"; readme_without_agents; "$2" exec'
    code, _, err = local["bash"].run(
        ["-c", program, "_", LIB, cli.executable], retcode=None
    )
    assert code == 127
    # Danach meldet der ERR-Trap von lib.sh den Befehl.
    assert err.splitlines()[0] == (
        f"{cli.executable}: in dieser Prüfung nicht verfügbar"
    )


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
    """Einträge, geprüft gegen den Vertrag des Renderers."""
    path = Path(env["README_RESULTS_DIR"]) / f"{stem}.json"
    entries = json.loads(path.read_text())
    errors = readme_results.RESULT_SCHEMA.iter_errors(entries)
    assert [error.message for error in errors] == []
    return entries
