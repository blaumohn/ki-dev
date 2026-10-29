"""Hülle um strukturierte Agentenantworten: genau ein umschließender
Markdown-Codeblock fällt weg, sonst nichts. Gemeinsam für den
Worker-Vertrag (Adapter) und den Review-Vertrag (Kern)."""

from __future__ import annotations

import re

# Genau ein umschließender Markdown-Codeblock (```` ``` ```` oder
# ```` ```json ````); Modelle setzen ihn trotz Vorgabe zufällig
# (beobachtet: claude-haiku-5-5, 1 von 18 Review-Sitzungen, dann in
# jeder Wiederholung derselben Sitzung).
_FENCE = re.compile(r"\A```(?:json)?[ \t]*\n(.*)\n```\Z", re.DOTALL)


def unwrap_json_fence(raw: str) -> str:
    """Inhalt eines einzigen umschließenden Codeblocks, sonst ``raw``.
    Nur die Hülle fällt weg; Text davor oder danach und mehrere
    Blöcke bleiben, wie sie sind, und damit Vertragsfehler."""
    match = _FENCE.match(raw.strip())
    if match is None or "```" in match.group(1):
        return raw
    return match.group(1)
