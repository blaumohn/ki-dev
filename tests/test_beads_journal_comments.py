"""Kommentar-Journal: comments export/mark-incorporated/lint (ebqv)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ki_dev.beads_journal import cli, comments, journal
from ki_dev.beads_journal.contract import PayloadError
from tests.test_beads_journal import IDENTITY, git, issue, subjects

SECRET = "GEHEIM-7f3a"
MARK = comments.COMMAND + " mark-incorporated"
HOOK = Path(__file__).parents[1] / ".beads" / "hooks" / "pre-commit.old"
EXPORT = ["--readonly", "export"]


def comment(number, text=SECRET):
    return {
        "id": f"c-{number}",
        "issue_id": "t-1",
        "author": "tester",
        "text": f"{text} {number}",
        "created_at": "2026-10-25T10:00:00Z",
    }


class FakeBd:
    """bd und Löschskript über eine Zustandsdatei mit Exportzeilen.

    calls.jsonl hält jeden Aufruf mit der Commitzahl des Journals zum
    Aufrufzeitpunkt fest. bd kennt nur den lesenden Export; jeder
    andere Aufruf (Schreiben nach bd) endet mit Exit 9.
    """

    def __init__(self, folder, monkeypatch, journal):
        self.folder = folder
        self.state = folder / "state.json"
        self.calls = folder / "calls.jsonl"
        self.fail = folder / "clear-fails"
        folder.mkdir()
        self.rows([])
        bd = self._script("bd", self._bd_body(journal))
        clear = self._script("clear", self._clear_body(journal))
        monkeypatch.setattr(cli, "BD_PROGRAM", str(bd))
        monkeypatch.setattr(comments, "CLEAR_SCRIPT", clear)

    def rows(self, rows):
        self.state.write_text(json.dumps(rows))

    def current(self):
        return json.loads(self.state.read_text())

    def logged(self):
        if not self.calls.exists():
            return []
        return [
            json.loads(line)
            for line in self.calls.read_text().splitlines()
        ]

    def writes(self):
        """Aufrufe außer dem lesenden bd export."""
        return [args for args, _ in self.logged() if args != EXPORT]

    def _script(self, name, body):
        script = self.folder / name
        script.write_text(f"#!{sys.executable}\n{body}")
        script.chmod(0o755)
        return script

    def _prelude(self, journal):
        return (
            "import json, subprocess, sys\n"
            f"state = {str(self.state)!r}\n"
            f"calls = {str(self.calls)!r}\n"
            "rows = json.load(open(state))\n"
            "count = subprocess.run(['git', '-C', "
            f"{str(journal)!r}, 'rev-list', '--count', 'HEAD'],"
            " capture_output=True, text=True).stdout.strip()\n"
            "with open(calls, 'a') as log:\n"
            "    log.write(json.dumps([sys.argv[1:], count]) + '\\n')\n"
        )

    def _bd_body(self, journal):
        return self._prelude(journal) + (
            f"if sys.argv[1:] != {EXPORT!r}:\n"
            "    sys.exit(9)\n"
            "for row in rows:\n"
            "    print(json.dumps({'_type': 'issue', **row}))\n"
        )

    def _clear_body(self, journal):
        return self._prelude(journal) + (
            f"if __import__('os').path.exists({str(self.fail)!r}):\n"
            "    sys.exit(3)\n"
            "for row in rows:\n"
            "    if row['id'] in sys.argv[1:]:\n"
            "        row.pop('comments', None)\n"
            "json.dump(rows, open(state, 'w'))\n"
        )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    return path


@pytest.fixture
def journal_dir(repo):
    path = repo / ".local" / "beads-journal"
    journal.initialize(path, [], IDENTITY)
    return path


@pytest.fixture
def fake(tmp_path, monkeypatch, journal_dir):
    return FakeBd(tmp_path / "fake", monkeypatch, journal_dir)


def run(repo, *args):
    return cli.main(["--repo", str(repo), "comments", *args])


def stored(journal_dir, issue_id="t-1"):
    path = journal_dir / "comments" / f"{issue_id}.json"
    return json.loads(path.read_text())


def states(journal_dir, issue_id="t-1"):
    return {
        entry["id"]: entry["state"]
        for entry in stored(journal_dir, issue_id)["comments"]
    }


def test_export_commits_before_clearing(
    repo,
    journal_dir,
    fake,
    capsys,
):
    fake.rows([issue(comments=[comment(1), comment(2)]), issue("t-2")])

    assert run(repo, "export") == 0

    assert subjects(journal_dir)[-2:] == [
        "comments: README.md",
        "comments t-1: 2 ausgelagert",
    ]
    clear_call = [
        count for args, count in fake.logged() if args == ["t-1"]
    ]
    assert clear_call == ["3"]
    assert "comments" not in fake.current()[0]
    assert stored(journal_dir) == {
        "issue_id": "t-1",
        "comments": [
            {
                "id": f"c-{n}",
                "author": "tester",
                "created_at": "2026-10-25T10:00:00Z",
                "text": f"{SECRET} {n}",
                "state": "open",
            }
            for n in (1, 2)
        ],
    }
    output = capsys.readouterr().out
    assert SECRET not in output
    assert "t-1: 2 in bd, 2 neu ausgelagert" in output
    assert f"{MARK} t-1" in output
    assert git(journal_dir, "status", "--porcelain") == ""


def test_clear_failure_keeps_commit_and_fails(
    repo,
    journal_dir,
    fake,
    capsys,
):
    fake.rows([issue(comments=[comment(1)])])
    fake.fail.write_text("")

    assert run(repo, "export") == 1

    assert subjects(journal_dir)[-1] == "comments t-1: 1 ausgelagert"
    error = capsys.readouterr().err
    assert "Löschen in bd fehlgeschlagen" in error
    assert "t-1" in error
    assert f"{comments.COMMAND} export" in error
    assert fake.current()[0]["comments"]


def test_second_export_keeps_state_and_appends_new(
    repo,
    journal_dir,
    fake,
):
    fake.rows([issue(comments=[comment(1)])])
    assert run(repo, "export") == 0
    assert run(repo, "mark-incorporated", "t-1") == 0
    fake.rows([issue(comments=[comment(1, "neu"), comment(2)])])

    assert run(repo, "export") == 0

    assert states(journal_dir) == {"c-1": "incorporated", "c-2": "open"}
    assert stored(journal_dir)["comments"][0]["text"] == f"{SECRET} 1"
    assert subjects(journal_dir)[-1] == "comments t-1: 1 ausgelagert"


def test_export_without_new_comments_commits_nothing(
    repo,
    journal_dir,
    fake,
):
    fake.rows([issue(comments=[comment(1)])])
    assert run(repo, "export") == 0
    before = subjects(journal_dir)
    fake.rows([issue(comments=[comment(1)])])

    assert run(repo, "export") == 0

    assert subjects(journal_dir) == before
    assert "comments" not in fake.current()[0]


def test_mark_incorporated_selected_then_all(
    repo,
    journal_dir,
    fake,
    capsys,
):
    fake.rows([issue(comments=[comment(1), comment(2)])])
    assert run(repo, "export") == 0

    assert run(repo, "mark-incorporated", "t-1", "c-1") == 0
    assert f"{MARK} t-1" in capsys.readouterr().out

    assert run(repo, "mark-incorporated", "t-1") == 0

    assert states(journal_dir) == {
        "c-1": "incorporated",
        "c-2": "incorporated",
    }
    assert "labels" not in fake.current()[0]
    assert fake.writes() == [["t-1"]]
    assert subjects(journal_dir)[-2:] == [
        "comments t-1: 1 eingebaut",
        "comments t-1: 1 eingebaut",
    ]


@pytest.mark.parametrize(
    "rows, args, reason, hint",
    [
        (
            [issue()],
            ["t-1", "c-9"],
            "Kommentar-ID unbekannt: c-9",
            f"{MARK} t-1",
        ),
        (
            [issue(comments=[comment(3)])],
            ["t-1"],
            "bd hat noch 1 Kommentare",
            f"{comments.COMMAND} export",
        ),
        ([issue("t-2")], ["t-2"], "comments/t-2.json fehlt", "export"),
        (
            [issue()],
            ["../t-1"],
            "ungültige Vorgangs-ID",
            f"{comments.COMMAND} lint",
        ),
    ],
)
def test_mark_incorporated_rejects_without_writing(
    repo,
    journal_dir,
    fake,
    capsys,
    rows,
    args,
    reason,
    hint,
):
    fake.rows([issue(comments=[comment(1)])])
    assert run(repo, "export") == 0
    fake.rows(rows)
    before = (subjects(journal_dir), stored(journal_dir))
    capsys.readouterr()

    assert run(repo, "mark-incorporated", *args) == 1

    assert (subjects(journal_dir), stored(journal_dir)) == before
    error = capsys.readouterr().err
    assert reason in error
    assert hint in error


def test_lint_fails_on_comments_in_bd(
    repo,
    journal_dir,
    fake,
    capsys,
):
    fake.rows([issue(comments=[comment(1)])])

    assert run(repo, "lint") == 1

    output = capsys.readouterr().out
    assert "t-1: 1 Kommentare in bd" in output
    assert f"{comments.COMMAND} export" in output
    assert SECRET not in output


def test_lint_fails_on_open_entries(
    repo,
    journal_dir,
    fake,
    capsys,
):
    fake.rows([issue(comments=[comment(1)])])
    assert run(repo, "export") == 0
    capsys.readouterr()

    assert run(repo, "lint") == 1

    assert f"t-1: 1 offen. Einbauen nach Bedarf, dann: {MARK} t-1" in (
        capsys.readouterr().out
    )


def test_lint_passes_when_all_incorporated(
    repo,
    journal_dir,
    fake,
    capsys,
):
    fake.rows([issue(comments=[comment(1)]), issue("t-2")])
    assert run(repo, "export") == 0
    assert run(repo, "mark-incorporated", "t-1") == 0
    capsys.readouterr()

    assert run(repo, "lint") == 0

    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("hand_edit", [False, True])
def test_lint_writes_nothing(repo, journal_dir, fake, hand_edit):
    fake.rows([issue(comments=[comment(1)])])
    assert run(repo, "export") == 0
    if hand_edit:
        path = journal_dir / "comments" / "t-1.json"
        path.write_text("{}")
    fake.rows([issue(comments=[comment(1), comment(2)])])
    before = (
        subjects(journal_dir),
        git(journal_dir, "status", "--porcelain"),
        fake.current(),
        fake.writes(),
    )

    assert run(repo, "lint") == 1

    assert before == (
        subjects(journal_dir),
        git(journal_dir, "status", "--porcelain"),
        fake.current(),
        fake.writes(),
    )


def test_lint_fails_on_hand_edited_file(
    repo,
    journal_dir,
    fake,
    capsys,
):
    fake.rows([issue(comments=[comment(1)])])
    assert run(repo, "export") == 0
    path = journal_dir / "comments" / "t-1.json"
    record = stored(journal_dir)
    record["comments"][0]["state"] = "erledigt"
    path.write_text(json.dumps(record))
    capsys.readouterr()

    assert run(repo, "lint") == 1

    output = capsys.readouterr().out
    assert (
        "comments/t-1.json: comments.0.state: unbekannter Wert"
        in output
    )
    assert "erledigt" not in output
    assert (
        f"git -C {journal_dir} checkout -- comments/t-1.json" in output
    )


@pytest.mark.parametrize(
    "change, reason",
    [
        (
            lambda r: r["comments"][0].update(state="x"),
            "comments.0.state: unbekannter Wert",
        ),
        (
            lambda r: r["comments"][0].pop("text"),
            "comments.0.text: Pflichtfeld fehlt",
        ),
        (
            lambda r: r["comments"][0].update(extra=1),
            "comments.0: unbekanntes Feld",
        ),
        (
            lambda r: r.update(issue_id="t-2"),
            "issue_id: passt nicht zum Dateinamen",
        ),
        (
            lambda r: r["comments"].append(dict(r["comments"][0])),
            "comments: doppelte id",
        ),
    ],
)
def test_schema_names_field_path(tmp_path, change, reason):
    record = {
        "issue_id": "t-1",
        "comments": [
            {
                "id": "c-1",
                "author": "a",
                "created_at": "2026-10-25T10:00:00Z",
                "text": SECRET,
                "state": "open",
            }
        ],
    }
    change(record)
    path = tmp_path / "t-1.json"
    path.write_text(json.dumps(record))

    with pytest.raises(PayloadError) as caught:
        comments.load(tmp_path, path)

    assert f"comments/t-1.json: {reason}" in str(caught.value)
    assert SECRET not in str(caught.value)


def test_readme_is_created_once(repo, journal_dir, fake):
    assert run(repo, "export") == 0
    readme = journal_dir / "comments" / "README.md"
    assert "mark-incorporated" in readme.read_text()
    count = len(subjects(journal_dir))
    mtime = readme.stat().st_mtime_ns

    assert run(repo, "export") == 0

    assert len(subjects(journal_dir)) == count
    assert readme.stat().st_mtime_ns == mtime


def test_inactive_journal_points_to_init(repo, capsys):
    assert run(repo, "lint") == 1

    assert "beads_journal init" in capsys.readouterr().err


def hook_repo(tmp_path, export_exit, lint_exit):
    """Wegwerf-Repo mit pre-commit.old und einem Fake-venv-Python.

    Das Fake-Python protokolliert die comments-Aktion und endet mit dem
    vorgegebenen Exit.
    """
    path = tmp_path / "hook-repo"
    (path / ".venv" / "bin").mkdir(parents=True)
    git(path, "init", "-q")
    python = path / ".venv" / "bin" / "python"
    python.write_text(
        "#!/bin/sh\n"
        'echo "$4" >> "$(dirname "$0")/calls"\n'
        f'[ "$4" = export ] && exit {export_exit}\n'
        f"exit {lint_exit}\n"
    )
    python.chmod(0o755)
    return path


def run_hook(path):
    return subprocess.run(
        ["sh", str(HOOK)],
        cwd=path,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        check=False,
    )


@pytest.mark.parametrize(
    "export_exit, lint_exit, calls, expected",
    [
        (0, 0, ["export", "lint"], 0),
        (0, 1, ["export", "lint"], 1),
        (3, 0, ["export"], 3),
    ],
)
def test_pre_commit_old_chains_export_then_lint(
    tmp_path, export_exit, lint_exit, calls, expected
):
    path = hook_repo(tmp_path, export_exit, lint_exit)

    result = run_hook(path)

    assert result.returncode == expected
    log = path / ".venv" / "bin" / "calls"
    assert log.read_text().split() == calls


def test_pre_commit_old_without_venv_fails(tmp_path):
    path = tmp_path / "leer"
    path.mkdir()
    git(path, "init", "-q")

    result = run_hook(path)

    assert result.returncode == 1
    assert "make setup" in result.stderr


def test_pre_commit_old_is_not_taken_for_a_bd_hook():
    """bd überspringt .old mit eigenen Markern (getHookVersion)."""
    text = HOOK.read_text(encoding="utf-8")

    for marker in (
        "# --- BEGIN BEADS INTEGRATION",
        "# bd-shim ",
        "# bd-hooks-version: ",
        "# bd (beads)",
    ):
        assert marker not in text
