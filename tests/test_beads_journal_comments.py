"""Kommentar-Journal: comments export/mark-incorporated/lint (ebqv)."""

import json
import sys

import pytest

from ki_dev.beads_journal import cli, comments, journal
from ki_dev.beads_journal.contract import PayloadError
from tests.test_beads_journal import IDENTITY, git, issue, subjects

SECRET = "GEHEIM-7f3a"
MARK = comments.COMMAND + " mark-incorporated"


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
    Aufrufzeitpunkt fest.
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
            "args = sys.argv[1:]\n"
            "if args[:2] == ['--readonly', 'export']:\n"
            "    for row in rows:\n"
            "        print(json.dumps({'_type': 'issue', **row}))\n"
            "    sys.exit(0)\n"
            "action, ids, label = args[1], args[2:-1], args[-1]\n"
            "for row in rows:\n"
            "    if row['id'] in ids:\n"
            "        labels = set(row.get('labels', []))\n"
            "        labels = labels | {label} if action == 'add'"
            " else labels - {label}\n"
            "        row['labels'] = sorted(labels)\n"
            "json.dump(rows, open(state, 'w'))\n"
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
    fake.rows(
        [issue(labels=[], comments=[comment(1, "neu"), comment(2)])]
    )

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
    fake.rows([issue(labels=["comments:open"], comments=[comment(1)])])

    assert run(repo, "export") == 0

    assert subjects(journal_dir) == before
    assert "comments" not in fake.current()[0]


def test_mark_incorporated_selected_and_label_follows(
    repo,
    journal_dir,
    fake,
    capsys,
):
    fake.rows([issue(comments=[comment(1), comment(2)])])
    assert run(repo, "export") == 0
    assert fake.current()[0]["labels"] == ["comments:open"]

    assert run(repo, "mark-incorporated", "t-1", "c-1") == 0
    assert fake.current()[0]["labels"] == ["comments:open"]
    assert f"{MARK} t-1" in capsys.readouterr().out

    assert run(repo, "mark-incorporated", "t-1") == 0

    assert states(journal_dir) == {
        "c-1": "incorporated",
        "c-2": "incorporated",
    }
    assert fake.current()[0]["labels"] == []
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
        ([issue()], ["../t-1"], "ungültige Vorgangs-ID", "bd list"),
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


def test_lint_open_entries_are_only_a_hint(
    repo,
    journal_dir,
    fake,
    capsys,
):
    fake.rows([issue(comments=[comment(1)])])
    assert run(repo, "export") == 0
    capsys.readouterr()

    assert run(repo, "lint") == 0

    assert f"t-1: 1 offen. Einbauen nach Bedarf, dann: {MARK} t-1" in (
        capsys.readouterr().out
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
