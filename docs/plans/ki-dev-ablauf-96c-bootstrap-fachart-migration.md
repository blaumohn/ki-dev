# Plan: ki-dev-ablauf-96c design-notes.de.md und bootstrap-notes.de.md in Fachart-Dokumente ueberfuehren

## Context

Bootstrap-Stufe 3 (siehe `bootstrap-notes.de.md` Abschnitt 10). Depends on
`ki-dev-ablauf-i7n` (`ki-dev check`).

Ziel: `design-notes.de.md` und `bootstrap-notes.de.md` in Fachart-Dokumente
ueberfuehren.

Massgebliche Quellen: `bootstrap-notes.de.md` Abschnitt 10, `design-notes.de.md`
(vollstaendig), `bootstrap-notes.de.md` (vollstaendig).

Umfang: Nach erfolgreicher Stufe 2 gilt `ki-dev check` als Pflichtpruefung
fuer neue Fachart-Dokumente. Der geltende Inhalt von `design-notes.de.md` und
`bootstrap-notes.de.md` wird in die passenden Facharten zerlegt, zum Beispiel:

- Definition und Systemaufbau -> `system_spec`
- CONTROLLED_WRITE-Zustandsablauf -> `flow_spec`
- Einzelne normative Festlegungen (z. B. "CONTROLLER_FINAL_CHECK ist ein
  frischer Controller-Lauf") -> `decision`
- Schreibschnitt-Aufloesung -> `guideline`
- Zustandsmaschinen-Anforderungen <-> Tests -> `test_matrix`

Die Migration ist keine wortgetreue Aufteilung nach Ueberschriften; der Agent
entscheidet nach fachlicher Bedeutung.

Nicht Teil dieses Vorgangs: Verarbeitung des laufenden Planning-Snapshots
(`bd:ki-dev-ablauf-9407`); das ist ein eigener, spaeterer
Bootstrap-Stufe-4-Vorgang. Die Archivierungsform der alten Dokumente wird hier
nicht vorweggenommen.

Reviewer prueft besonders: fachliche Zuordnung korrekt und vollstaendig, kein
Bedeutungsverlust gegenueber den Quellen.

Eskalation wenn: die fachliche Zuordnung eines Abschnitts zu einer Fachart
nicht eindeutig entscheidbar ist (NEEDS_DECISION melden, Vorgang offen lassen,
nicht raten).

## Validation Commands

- `ki-dev check`
- `git diff --check`

### Task 1: ki-dev-ablauf-96c design-notes.de.md und bootstrap-notes.de.md in Fachart-Dokumente ueberfuehren

- [ ] Alle neu erzeugten Fachart-Dokumente bestehen `ki-dev check`.
- [ ] Jeder normative Inhalt aus `design-notes.de.md` und
      `bootstrap-notes.de.md` ist einer Fachart zugeordnet oder es ist
      dokumentiert, warum nicht.
- [ ] Nach erfolgreicher Migration und Review gelten die Fachart-Dokumente
      als normative Grundlage fuer weitere Planning-Schreibarbeit; die alten
      `*-notes.de.md`-Dateien werden Migrationsquelle/Archiv.
