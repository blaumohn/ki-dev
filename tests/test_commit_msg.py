import pytest
from hypothesis import given
from hypothesis import strategies as st

from ki_dev.commit_msg import (
    check_commit_message_file,
    validate_subject,
)

_VALID = [
    "feat: Python-CLI ergaenzen (ki-dev-ablauf-8dd.1)",
    "feat: Python-CLI ergaenzen (ki-dev-ablauf-8dd)",
    "fix: parser (v2) neu bauen (ki-dev-ablauf-4p8)",
    "docs: verschachtelt (ki-dev-ablauf-8dd.1.2)",
    "chore: xf2 und cbo schliessen "
    "(ki-dev-ablauf-xf2) (ki-dev-ablauf-cbo)",
    "chore: drei Issues schliessen "
    "(ki-dev-ablauf-hju) (ki-dev-ablauf-dqv) (ki-dev-ablauf-8dd.1)",
]

_INVALID = [
    "",
    "feat: ganz ohne id",
    "feat: ki-dev-ablauf-8dd nur im text",
    "feat: kaputt (ki-dev-ablauf-)",
    "feat: kaputt (ki-dev-ablauf-8dd.)",
    "feat: ohne leerzeichen(ki-dev-ablauf-8dd)",
    "feat: grossbuchstaben (KI-DEV-ABLAUF-8DD)",
    "feat: platzhalter (WIP)",
    "feat: id nicht am ende (ki-dev-ablauf-8dd) rest",
    # Kommaformat: bd orphans matcht das nicht als Ganzes und
    # erkennt daher kein Issue (siehe commit_msg.py-Docstring).
    "chore: xf2 und cbo schliessen (ki-dev-ablauf-xf2, cbo)",
    "chore: zweite id ohne eigene klammer (ki-dev-ablauf-xf2 cbo)",
    "chore: trailing komma (ki-dev-ablauf-xf2,)",
]


@pytest.mark.parametrize("subject", _VALID)
def test_valid_subjects_pass(subject):
    assert validate_subject(subject) is None


@pytest.mark.parametrize("subject", _INVALID)
def test_invalid_subjects_rejected(subject):
    problem = validate_subject(subject)
    assert problem is not None
    assert "<Titel> (<Beads-ID>)[ (<Beads-ID>)...]" in problem
    assert "Beads-Integration" in problem


def test_check_file_accepts_valid_message(tmp_path):
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text(
        "feat: x (ki-dev-ablauf-8dd.1)\n\nRumpf\n", encoding="utf-8"
    )
    assert check_commit_message_file(str(path)) == 0


def test_check_file_rejects_invalid_message(tmp_path, capsys):
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text("feat: ohne id\n", encoding="utf-8")
    assert check_commit_message_file(str(path)) == 1
    assert "abgelehnt" in capsys.readouterr().err


_titles = (
    st.text(
        alphabet=st.characters(
            min_codepoint=32,
            max_codepoint=126,
            blacklist_characters="()",
        ),
        min_size=1,
        max_size=60,
    )
    .map(str.strip)
    .filter(bool)
)
_ALNUM = "0123456789abcdefghijklmnopqrstuvwxyz"
_ids = st.builds(
    lambda short, children: (
        f"ki-dev-ablauf-{short}" + "".join(f".{n}" for n in children)
    ),
    st.text(alphabet=_ALNUM, min_size=1, max_size=5),
    st.lists(st.integers(min_value=0, max_value=999), max_size=3),
)


@given(title=_titles, ident=_ids)
def test_wellformed_subject_accepted(title, ident):
    assert validate_subject(f"{title} ({ident})") is None


@given(title=_titles.filter(lambda s: "ki-dev-ablauf-" not in s))
def test_subject_without_id_rejected(title):
    assert validate_subject(title) is not None
