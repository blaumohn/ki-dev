"""Auswahlregeln für automatische Sitzungen außerhalb der Adapter."""

from __future__ import annotations

import re
from collections.abc import Sequence
from fnmatch import fnmatchcase
from pathlib import Path

from ki_dev.adapter.executors.session_metadata import (
    read_session_header,
)

_DEFAULT_EXCLUDES = (
    "*/pytest-of-*/*",
    "*/readme-check/*",
    "*/readme-walkthrough/*",
)
_GENERATED_PROMPT = re.compile(
    r"^(?:Bauauftrag fuer Lauf|Unabhaengiger Review fuer Lauf) "
    r"[^\n]+, Runde [0-9]+\.\nArbeitsverzeichnis:"
)


def is_automatic_session(
    agent: str, path: Path, exclude_cwd: Sequence[str]
) -> bool:
    header = read_session_header(agent, path)
    if header.subagent:
        return True
    if header.cwd is not None and any(
        fnmatchcase(header.cwd, pattern)
        for pattern in (*_DEFAULT_EXCLUDES, *exclude_cwd)
    ):
        return True
    return (
        header.first_user_text is not None
        and _GENERATED_PROMPT.match(header.first_user_text) is not None
    )
