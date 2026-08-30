# Bootstrap 1 – Planung materialisieren

## Quellen

* `design-notes.de.md`
* `bootstrap-design-notes.de.md`

## Ziel

Materialisiere aus diesen beiden Dokumenten die nächsten Bootstrap-Schritte in `bd`.

### Task 1

* `bd`-Vorgang für Fachart-Schemas anlegen.
* `bd`-Vorgang für minimale `ki-dev check`-Validierung anlegen.
* `bd`-Vorgang für die spätere Umwandlung der `*design-notes.de.md` in Fachart-Dokumente anlegen.
* Die notwendigen Abhängigkeiten zwischen diesen Vorgängen setzen.
* Für jeden erzeugten Vorgang einen eigenen Ralphex-Plan unter `docs/plans/` anlegen.

Keine Produktumsetzung durchführen. Keine neue Architekturentscheidung treffen.

## Validation

* `bd ready --json`
* `bd dep cycles`
* `git diff --check`

