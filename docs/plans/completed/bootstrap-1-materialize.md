# Bootstrap 1 – Planung materialisieren

## Quellen

- `design-notes.de.md`
- `bootstrap-notes.de.md`

## Validation Commands

- `bd list --json`
- `bd ready --json`
- `bd dep cycles`
- `git diff --check`
- Review vergleicht `bd list --json` mit `bootstrap/materialization-1.md`.

### Task 1: Bootstrap-Arbeitsgraph materialisieren

- [x] `bd`-Vorgang für Fachart-Schemas anlegen (B2A).
- [x] `bd`-Vorgang für `ki-dev check` anlegen (B2B).
- [x] `bd`-Vorgang für die Fachart-Migration anlegen (B3).
- [x] `bd`-Vorgang für die Planning-Snapshot-Einarbeitung anlegen (B4,
      `bootstrap-notes.de.md` Abschnitt 6 verlangt "mindestens" B2A–B4).
- [x] Abhängigkeiten setzen (Kette B4 → B3 → B2B → B2A).
- [x] Für jeden Vorgang einen Ralphex-Plan erzeugen.
