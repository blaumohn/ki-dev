"""Öffentliche PM-Sicht des Journals: Privatprüfung, Abgleich, Index.

Reine Funktionen ohne Ein-/Ausgabe; ``cli.py`` liefert Revisionen,
Journal-Dateien und den bd export. Befunde nennen nur Revision, Datei
und Kategorie, nie den gefundenen Wert.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

INDEX = "index.md"

# Kategorie -> Muster. Bewusst grob: ein Befund ist eine Prüfaufgabe
# für den Menschen, kein Beweis.
PRIVACY_PATTERNS: Mapping[str, re.Pattern[str]] = {
    "lokaler-verweis": re.compile(r"(?<![\w-])\.local/"),
    "absoluter-pfad": re.compile(
        r"(?<![\w.~-])/(?:home|Users|root|workspace|tmp|mnt|srv|opt)/"
    ),
    "mailadresse": re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
    ),
    "zugangsdaten": re.compile(
        r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
        r"|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}"
        r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
        r"|(?i:password|passwort|secret|token|api[_-]?key)"
        r"\s*[:=]\s*\S{6,})"
    ),
}
# Keine Privatbefunde: No-Reply-Adressen von GitHub und reservierte
# Beispieldomänen (RFC 2606), wie sie in Testbeschreibungen stehen.
_PUBLIC_MAIL = re.compile(
    r"[A-Za-z0-9._%+-]+@(?:users\.noreply\.github\.com"
    r"|(?:[A-Za-z0-9-]+\.)*(?:example|invalid|test|localhost)"
    r"|(?:[A-Za-z0-9-]+\.)*example\.(?:com|org|net))\b"
)


@dataclass(frozen=True, order=True)
class Finding:
    revision: str
    path: str
    category: str


def scan_text(text: str) -> tuple[str, ...]:
    """Kategorien, die im Text vorkommen (sortiert, ohne Werte)."""
    cleaned = _PUBLIC_MAIL.sub("", text)
    return tuple(
        sorted(
            category
            for category, pattern in PRIVACY_PATTERNS.items()
            if pattern.search(cleaned)
        )
    )


def audit_changes(
    changes: Iterable[tuple[str, str, str]],
) -> list[Finding]:
    """Befunde je (Revision, Datei, eingefügter Text), sortiert."""
    return sorted(
        {
            Finding(revision, path, category)
            for revision, path, text in changes
            for category in scan_text(text)
        }
    )


def orphans(
    journal_ids: Iterable[str], db_ids: Iterable[str]
) -> list[str]:
    """Journal-Vorgänge ohne DB-Gegenstück (kein Lösch-Hook)."""
    return sorted(set(journal_ids) - set(db_ids))


def render_index(
    issues: Iterable[Mapping[str, object]],
    missing_in_db: Iterable[str],
    exported_at: str,
    code_commit: str,
) -> str:
    """Eine Zeile je Vorgang, nach ID sortiert; gleiche Eingabe ergibt
    dieselbe Datei. Fehlende DB-Vorgänge werden gekennzeichnet."""
    missing = set(missing_in_db)
    rows = sorted(issues, key=lambda issue: str(issue["id"]))
    lines = [
        "# Beads-Journal – Vorgänge",
        "",
        f"Stand der Datenbank: {exported_at} · Code-Commit: "
        f"`{code_commit}`",
        "",
        f"{len(rows)} Vorgänge; Verlauf je Vorgang: "
        "`git log -p -- issues/<ID>.json`.",
    ]
    if missing:
        lines += [
            "",
            "„nicht in DB“: Datei im Journal, Vorgang in der Datenbank "
            "gelöscht (das Journal kennt kein Löschen).",
        ]
    lines += [
        "",
        "| ID | Titel | Status | Typ |",
        "|---|---|---|---|",
    ]
    for issue in rows:
        issue_id = str(issue["id"])
        status = str(issue.get("status", ""))
        if issue_id in missing:
            status += " · nicht in DB"
        lines.append(
            f"| [{issue_id}](issues/{issue_id}.json) "
            f"| {_cell(issue.get('title', ''))} "
            f"| {_cell(status)} "
            f"| {_cell(issue.get('issue_type', ''))} |"
        )
    return "\n".join(lines) + "\n"


def _cell(value: object) -> str:
    text = " ".join(str(value).split())
    return text.replace("\\", "\\\\").replace("|", "\\|")
