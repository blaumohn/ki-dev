# Plan: ki-dev-ablauf-ie5 Fachart-Schemas umsetzen

## Context

Bootstrap-Stufe 2A (siehe `bootstrap-notes.de.md` Abschnitt 8 und `design-notes.de.md`
als normativer Vertrag). Es wird noch kein Fachart-Graph gebaut; Fachart-Dokumente
sind zunaechst Dateien im Repository.

Ziel: Erste Fachart-Schemas und die zugehoerige Verzeichnisstruktur fuer
Fachart-Dokumente anlegen.

Massgebliche Quellen: `bootstrap-notes.de.md` Abschnitt 8, `design-notes.de.md`.

Umfang: JSON-Schema-Dateien unter `schemas/ki-dev/` fuer die Facharten
`system_spec`, `flow_spec`, `decision`, `guideline`, `test_matrix`.
Verzeichnisstruktur `docs/ki-dev/fach/{system-spec,flow-spec,decision,guideline,test-matrix}/`.
Fachdaten-Format YAML. Die Schemas pruefen zunaechst nur lokale Struktur:
Fachart, Kennung, Titel, Zustand, Pflichtfelder, strukturierte Listen, lokale
Unterkennungen, grundlegende Wertebereiche.

Nicht Teil dieses Vorgangs: kein fachlicher Dokumentgraph; keine
Validierungslogik (das ist der abhaengige Folgevorgang `ki-dev-ablauf-i7n`,
`ki-dev check`).

Reviewer prueft besonders: Schema-Vollstaendigkeit gegen
`bootstrap-notes.de.md` Abschnitt 8.

Eskalation wenn: Pflichtfelder einer Fachart nicht eindeutig aus den Quellen
ableitbar sind (NEEDS_DECISION melden, Vorgang offen lassen, nicht raten).

## Validation Commands

- `python3 -c "import json; [json.load(open(f'schemas/ki-dev/{n}.json')) for n in ('system_spec','flow_spec','decision','guideline','test_matrix')]"`
  – prüft explizit alle fünf erwarteten Schema-Dateien (nicht nur ein Glob, das
  auch bei 0–4 Dateien bestünde) auf syntaktisch gültiges JSON.
- `test -d docs/ki-dev/fach/system-spec && test -d docs/ki-dev/fach/flow-spec && test -d docs/ki-dev/fach/decision && test -d docs/ki-dev/fach/guideline && test -d docs/ki-dev/fach/test-matrix`
- `git diff --check`

### Task 1: ki-dev-ablauf-ie5 Fachart-Schemas umsetzen

- [x] Jede der fuenf Facharten (`system_spec`, `flow_spec`, `decision`,
      `guideline`, `test_matrix`) hat ein gueltiges JSON Schema unter
      `schemas/ki-dev/`.
- [x] Jedes Schema erzwingt Fachart, Kennung, Titel, Zustand und die
      dokumentierten Pflichtfelder (strukturierte Listen, lokale
      Unterkennungen, grundlegende Wertebereiche).
- [x] Die Zielverzeichnisse `docs/ki-dev/fach/system-spec/`,
      `docs/ki-dev/fach/flow-spec/`, `docs/ki-dev/fach/decision/`,
      `docs/ki-dev/fach/guideline/`, `docs/ki-dev/fach/test-matrix/`
      existieren.
