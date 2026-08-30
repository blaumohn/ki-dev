# Plan: ki-dev-ablauf-i7n ki-dev check und minimale Nachweispruefung umsetzen

## Context

Bootstrap-Stufe 2B (siehe `bootstrap-notes.de.md` Abschnitt 9 und
`design-notes.de.md` als normativer Vertrag). Depends on
`ki-dev-ablauf-ie5` (Fachart-Schemas).

Ziel: `ki-dev check` als minimale deterministische Pruefschicht in Python
umsetzen.

Massgebliche Quellen: `bootstrap-notes.de.md` Abschnitt 9, `design-notes.de.md`.

Umfang: `ki-dev check` prueft mindestens:

1. alle Fachart-Dateien gegen ihr JSON Schema;
2. doppelte Fachart-Kennungen;
3. ungueltige lokale Anforderungskennungen;
4. Verweise einer Testmatrix auf nicht vorhandene
   Spezifikations-/Anforderungskennungen;
5. vorhandene Quelltext- oder Testpfade, sofern eine Testmatrix einen
   konkreten Beleg behauptet.

Unterstuetzt die Anforderungs-/Quelltext-Schnittstelle (`requirements`-Liste
in Spezifikationen, `requirement`/`implementation`/`tests` in
Testmatrix-Eintraegen). Verlangt in dieser Stufe noch nicht, dass jede
pruefbare Anforderung bereits einen Test besitzt.

Nicht Teil dieses Vorgangs: fachlicher Dokumentgraph, implements-Endpunktregeln,
derived_from-Endpunktregeln, allgemeine Graphvalidierung, Zustandsmaschine,
Agentenorchestrierung, GitHub-Pages-Renderer.

Reviewer prueft besonders: Vollstaendigkeit der fuenf Pruefungen gegen
`bootstrap-notes.de.md` Abschnitt 9.

Eskalation wenn: Format der Anforderungs-/Testmatrix-Schnittstelle in den
Quellen widerspruechlich ist (NEEDS_DECISION melden, Vorgang offen lassen,
nicht raten).

## Validation Commands

- `pytest tests/test_ki_dev_check.py`
- `pytest`

### Task 1: ki-dev-ablauf-i7n ki-dev check und minimale Nachweispruefung umsetzen

- [ ] `ki-dev check` laeuft als CLI-Befehl gegen die Fachart-Verzeichnisse aus
      `ki-dev-ablauf-ie5`.
- [ ] Alle fuenf in `bootstrap-notes.de.md` Abschnitt 9 aufgezaehlten
      Pruefungen sind implementiert und getestet.
- [ ] Requirement/Testmatrix-Verweise nach dem dokumentierten Format
      (`requirements`-Liste, `requirement`/`implementation`/`tests`) werden
      erkannt und validiert.
