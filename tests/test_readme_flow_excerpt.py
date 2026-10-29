"""Auszug aus implement.toml im Minimalbeispiel: echt, nicht nachgebaut.

Die README zitiert Zeilen aus src/ki_dev/flow/implement.toml mit
Halbsatz-Kommentaren (``  # …``). Jeder Abschnitt des Auszugs (getrennt
durch Leerzeilen oder eine Zeile ``# …``) muss ohne diese Kommentare
zusammenhängend in der Ablaufdatei stehen, sonst ist er veraltet.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / "src/ki_dev/flow/implement.toml"
DOCUMENTS = {
    "README.md": "Auszug aus `implement.toml`:",
    "README.en.md": "Excerpt from `implement.toml`:",
}
COMMENT = re.compile(r"\s+# .*$")


def excerpt(document: str, lead: str) -> str:
    text = (ROOT / document).read_text()
    match = re.search(
        re.escape(lead) + r"\n\n```toml\n(.*?)^```$",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, f"{document}: kein TOML-Auszug nach {lead!r}"
    return match.group(1)


def chunks(block: str) -> list[str]:
    parts, current = [], []
    for line in block.splitlines():
        if not line.strip() or line.strip() == "# …":
            if current:
                parts.append("\n".join(current))
            current = []
            continue
        current.append(COMMENT.sub("", line))
    if current:
        parts.append("\n".join(current))
    return parts


@pytest.mark.parametrize("document", sorted(DOCUMENTS))
def test_flow_excerpt_matches_implement_toml(document):
    source = FLOW.read_text()
    parts = chunks(excerpt(document, DOCUMENTS[document]))
    assert parts
    for part in parts:
        assert part in source, (
            f"{document}: nicht in implement.toml:\n{part}"
        )


def test_flow_excerpt_is_the_same_in_both_languages():
    de, en = (chunks(excerpt(d, lead)) for d, lead in DOCUMENTS.items())
    assert de == en
