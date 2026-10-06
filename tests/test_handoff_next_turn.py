"""Einheiten für Grenze, Leser und Vorlagen von ``--next-turn``."""

import io
from functools import partial

import pytest

from ki_dev.handoff import HandoffIssue, ReviewTarget
from ki_dev.handoff_next_turn import (
    DEFAULT_FEEDBACK_MAX_CHARS as DEFAULT_MAX,
)
from ki_dev.handoff_next_turn import (
    FeedbackReadError,
    NextTurnInputError,
    load_feedback_max_chars,
    read_feedback,
)
from ki_dev.handoff_next_turn import (
    render_repair_turn as _render_repair_turn,
)
from ki_dev.handoff_next_turn import (
    render_review_turn as _render_review_turn,
)
from ki_dev.step_flow import load_step_flow

FLOW = load_step_flow()
render_repair_turn = partial(_render_repair_turn, flow=FLOW)
render_review_turn = partial(_render_review_turn, flow=FLOW)

ISSUE = HandoffIssue(
    id="x-1",
    title="Titel",
    description="d",
    design="g",
    acceptance_criteria="a",
    source_refs=["a.md#L1"],
)


def _no_stdin() -> io.BytesIO:
    raise AssertionError("stdin wurde angefordert")


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "toml",
    [
        None,
        "",
        "[tool.ki-dev]\nx = 1\n",
        "[tool.ki-dev.handoff]\n",
        "[tool.ki-dev.handoff.preflight]\nchecks = []\n",
    ],
)
def test_missing_limit_is_default(tmp_path, toml):
    if toml is not None:
        _write(tmp_path / "pyproject.toml", toml)
    assert load_feedback_max_chars(tmp_path) == DEFAULT_MAX
    assert DEFAULT_MAX == 600


def test_configured_limit_is_used(tmp_path):
    _write(
        tmp_path / "pyproject.toml",
        "[tool.ki-dev.handoff]\nfeedback_max_chars = 42\n",
    )
    assert load_feedback_max_chars(tmp_path) == 42


@pytest.mark.parametrize(
    "value", ["0", "-5", '"600"', "true", "1.5", "600.0", "{}", "[]"]
)
def test_invalid_limit_is_rejected_without_raw_value(tmp_path, value):
    _write(
        tmp_path / "pyproject.toml",
        f"[tool.ki-dev.handoff]\nfeedback_max_chars = {value}\n",
    )
    with pytest.raises(NextTurnInputError) as error:
        load_feedback_max_chars(tmp_path)
    assert "tool.ki-dev.handoff.feedback_max_chars" in str(error.value)
    assert "positive ganze Zahl" in str(error.value)


def test_invalid_toml_is_rejected(tmp_path):
    _write(tmp_path / "pyproject.toml", "kaputt = [")
    with pytest.raises(NextTurnInputError, match="TOML"):
        load_feedback_max_chars(tmp_path)


@pytest.mark.parametrize(
    ("toml", "field"),
    [
        ("[tool]\nki-dev = 7\n", "tool.ki-dev"),
        ("[tool.ki-dev]\nhandoff = 7\n", "tool.ki-dev.handoff"),
        ("tool = 1\n", "tool"),
    ],
)
def test_wrong_table_type_is_rejected_with_field_path(
    tmp_path, toml, field
):
    _write(tmp_path / "pyproject.toml", toml)
    with pytest.raises(NextTurnInputError) as error:
        load_feedback_max_chars(tmp_path)
    assert f"{field} muss eine Tabelle sein" in str(error.value)
    assert "7" not in str(error.value).replace(field, "")


def test_reads_file_exactly_and_never_truncates(tmp_path):
    path = _write(tmp_path / "f.txt", "ä😀 \r\nx")
    assert read_feedback(str(path), 6, _no_stdin) == "ä😀 \r\nx"
    with pytest.raises(NextTurnInputError, match="5 Zeichen"):
        read_feedback(str(path), 5, _no_stdin)


def test_reads_stdin_through_the_same_path(tmp_path):
    data = io.BytesIO("ä😀 \r\nx".encode())
    assert read_feedback("-", 6, lambda: data) == "ä😀 \r\nx"
    # Der Strom bleibt offen: stdin wird nicht geschlossen.
    assert not data.closed


class _CountingStream(io.BytesIO):
    """Zählt die tatsächlich angeforderten und gelieferten Bytes."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.delivered = 0

    def read(self, size=-1):
        assert size is not None and size >= 0, "unbegrenztes Lesen"
        chunk = super().read(size)
        self.delivered += len(chunk)
        return chunk


@pytest.mark.parametrize(
    ("char", "width"), [("a", 1), ("ä", 2), ("✓", 3), ("😀", 4)]
)
def test_reads_no_byte_beyond_limit_plus_one_characters(char, width):
    stream = _CountingStream((char * 200_000).encode())
    with pytest.raises(NextTurnInputError, match="10 Zeichen"):
        read_feedback("-", 10, lambda: stream)
    assert stream.delivered == 11 * width


@pytest.mark.parametrize("char", ["a", "ä", "😀"])
def test_invalid_utf8_behind_limit_is_overlength_not_read_error(char):
    data = (char * 11).encode() + b"\xff\xfe" + b"x" * 50
    with pytest.raises(NextTurnInputError, match="10 Zeichen"):
        read_feedback("-", 10, lambda: _CountingStream(data))


def test_invalid_utf8_within_limit_is_read_error():
    data = b"a" * 5 + b"\xff" + b"a" * 3
    with pytest.raises(FeedbackReadError, match="UTF-8"):
        read_feedback("-", 10, lambda: io.BytesIO(data))


def test_truncated_utf8_at_end_is_read_error():
    data = b"ab" + "ä".encode()[:1]
    with pytest.raises(FeedbackReadError, match="UTF-8"):
        read_feedback("-", 10, lambda: io.BytesIO(data))


def test_file_is_read_without_overlength_decoding(tmp_path):
    path = tmp_path / "f.txt"
    path.write_bytes(b"a" * 11 + b"\xff" * 100_000)
    with pytest.raises(NextTurnInputError, match="10 Zeichen"):
        read_feedback(str(path), 10, _no_stdin)


@pytest.mark.parametrize("text", ["", " ", "\n\n", " \t"])
def test_blank_feedback_is_rejected(tmp_path, text):
    path = _write(tmp_path / "f.txt", text)
    with pytest.raises(NextTurnInputError, match="leer"):
        read_feedback(str(path), 10, _no_stdin)


def test_read_errors_name_no_content(tmp_path):
    bad = tmp_path / "f.txt"
    bad.write_bytes(b"GEHEIM\xff")
    with pytest.raises(FeedbackReadError, match="UTF-8") as utf8:
        read_feedback(str(bad), 100, _no_stdin)
    assert "GEHEIM" not in str(utf8.value)
    with pytest.raises(FeedbackReadError, match="nicht lesbar"):
        read_feedback(str(tmp_path / "fehlt"), 100, _no_stdin)
    with pytest.raises(FeedbackReadError, match="nicht lesbar"):
        read_feedback(str(tmp_path), 100, _no_stdin)


def test_repair_turn_names_recipient_request_limit_and_finding():
    finding = "- tests: FAIL [argv=x]"
    text = render_repair_turn(ISSUE, finding, 600, None)
    assert text.startswith("Empfänger: Bau-Agent")
    assert "Bead: x-1 - Titel" in text
    assert "Bitte die gemeldeten Fehler beheben." in text
    assert "höchstens 600 Zeichen" in text
    assert finding in text
    assert "Rückmeldung des Schreibagenten" not in text
    assert text.endswith("\n")


def test_review_turn_has_phase_specific_focus_per_target():
    texts = {
        target: render_review_turn(ISSUE, target, None, None)
        for target in (
            ReviewTarget.MAP,
            ReviewTarget.GRAPH,
            ReviewTarget.MATERIALIZE,
        )
    }
    assert len(set(texts.values())) == 3
    assert "Quellenabdeckung" in texts[ReviewTarget.MAP]
    assert "Abhängigkeiten" in texts[ReviewTarget.GRAPH]
    assert "Abnahmekriterien" in texts[ReviewTarget.MATERIALIZE]


def test_feedback_block_is_single_line_quoted_and_sanitized():
    raw = "a\n\x1b[1mb\x1b[0m\r\n\u2028c\x00"
    text = render_repair_turn(ISSUE, "x", 600, raw)
    assert "\n| a\n| [1mb[0m\n|\n| c\n" in text
    assert "\x1b" not in text
    assert "\x00" not in text
