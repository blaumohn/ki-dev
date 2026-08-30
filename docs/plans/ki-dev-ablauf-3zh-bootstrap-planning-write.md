# Plan: ki-dev-ablauf-3zh Planning-Snapshot kontrolliert in die Fachart-Dokumente einarbeiten

## Context

Bootstrap-Stufe 4 (siehe `bootstrap-notes.de.md` Abschnitt 11 und
`design-notes.de.md` als normativer Vertrag). Depends on
`ki-dev-ablauf-96c` (Fachart-Migration).

Ziel: Den bei `WRITE` gespeicherten Planning-Snapshot
(`bd:ki-dev-ablauf-9407`) kontrolliert in die neuen
Fachart-Dokumente einarbeiten (erste strukturierte Planning-Fortschreibung).

Massgebliche Quellen: `bootstrap-notes.de.md` Abschnitt 11,
`bd:ki-dev-ablauf-9407`, die aktuellen Fachart-Dokumente unter
`docs/ki-dev/fach/`.

Umfang: Der Lauf prueft Planning-Snapshot plus aktuelle Fachart-Dokumente und
schreibt nur die seit der letzten bereits materialisierten Planning-Grenze neu
entstandenen Entscheidungen. Verflachungsregel:

- bereits geschriebene Planung -> aus den Fachart-Dokumenten lesen
- nur neuer Planning-Nachlauf -> Snapshot
- beides zusammen -> kontrollierte Fortschreibung

Die alte vollstaendige Planning-Sitzung wird nicht erneut als regulaerer
Schreibeingang benoetigt.

Nicht Teil dieses Vorgangs: automatischer ki-dev-Dispatcher, vollstaendiger
Planning-Orchestrator, CONTROLLED_WRITE-Zustandsmaschine, Fachart-Graph,
vollstaendige Graphvalidierung, GitHub-Pages-Projektion.

Reviewer prueft besonders: keine Doppel-Materialisierung bereits geschriebener
Planung; korrekte Anwendung der Verflachungsregel.

Eskalation wenn: `bd:ki-dev-ablauf-9407` fehlt oder die
Planning-Grenze nicht eindeutig bestimmbar ist (NEEDS_DECISION melden, Vorgang
offen lassen, nicht raten).

## Validation Commands

- `ki-dev check`
- `git diff --check`

### Task 1: ki-dev-ablauf-3zh Planning-Snapshot kontrolliert in die Fachart-Dokumente einarbeiten

- [ ] Alle betroffenen Fachart-Dokumente bestehen `ki-dev check`.
- [ ] Nur neuer Planning-Nachlauf aus `bd:ki-dev-ablauf-9407` ist
      eingearbeitet; bereits materialisierte Planung wird nicht dupliziert.
- [ ] Der verarbeitete Snapshot-Stand ist dokumentiert.
