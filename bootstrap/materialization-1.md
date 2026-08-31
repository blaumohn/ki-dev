# Bootstrap-Stufe 1 – Materialisierungsbericht

## Quellenstand

- `design-notes.de.md` (Commit-Stand dieses Branches)
- `bootstrap-notes.de.md` (Commit-Stand dieses Branches)

## Erzeugte Vorgänge

| Bead-ID | Titel | Workflow | Abhängigkeiten | Ralphex-Plan |
| --- | --- | --- | --- | --- |
| `ki-dev-ablauf-ie5` | Fachart-Schemas umsetzen | `workflow:implementation` | – | `docs/plans/ki-dev-ablauf-ie5-bootstrap-schemas.md` |
| `ki-dev-ablauf-i7n` | ki-dev check und minimale Nachweisprüfung umsetzen | `workflow:implementation` | `ki-dev-ablauf-ie5` | `docs/plans/ki-dev-ablauf-i7n-bootstrap-check.md` |
| `ki-dev-ablauf-96c` | design-notes.de.md und bootstrap-notes.de.md in Fachart-Dokumente überführen | `workflow:planning` | `ki-dev-ablauf-i7n` | `docs/plans/ki-dev-ablauf-96c-bootstrap-fachart-migration.md` |
| `ki-dev-ablauf-3zh` | Planning-Snapshot kontrolliert in die Fachart-Dokumente einarbeiten | `workflow:planning` | `ki-dev-ablauf-96c` | `docs/plans/ki-dev-ablauf-3zh-bootstrap-planning-write.md` |

Abhängigkeitskette: `ki-dev-ablauf-3zh` → `ki-dev-ablauf-96c` → `ki-dev-ablauf-i7n` → `ki-dev-ablauf-ie5`
(jeweils "hängt ab von", Pfeilrichtung = blockiert durch).

Die vier Vorgänge entsprechen B2A, B2B, B3 und B4 aus `bootstrap-notes.de.md`
Abschnitt 6 ("erzeugt mindestens diese Vorgänge"). Die Ausführung von
Bootstrap-Stufe 4 selbst bleibt durch die Abhängigkeit auf `ki-dev-ablauf-96c`
blockiert, bis die Fachart-Migration abgeschlossen ist; `ki-dev-ablauf-3zh`
dient bis dahin nur der Nachverfolgung.

## Abschlussprüfung

```bash
bd list --json
bd ready --json
bd dep cycles
git diff --check
```

- `bd dep cycles` meldet keine Zyklen.
- `bd ready --json` liefert zum Zeitpunkt dieser Materialisierung genau
  `ki-dev-ablauf-ie5`, da alle Folgevorgänge (mittelbar) von ihm abhängen.
- Der tatsächliche `bd`-Bestand (`bd list --json`) entspricht der obigen
  Tabelle: vier offene Vorgänge in der genannten Abhängigkeitskette.

## Voraussetzung Planning-Snapshot: nachgeliefert

Zum Zeitpunkt dieser Materialisierung fehlte `bd:ki-dev-ablauf-9407`
noch. Laut `bootstrap-notes.de.md` Abschnitt 5 (Bootstrap-Stufe 0) gehört diese
Datei zu den in Stufe 0 einmalig angelegten und committeten Bootstrap-Artefakten;
Abschnitt 11 (Bootstrap-Stufe 4) setzt voraus, dass der Snapshot bereits bei
`WRITE` gespeichert wurde und dort nur noch verarbeitet wird.

Der Snapshot wurde inzwischen auf diesem Branch nachgeliefert und liegt jetzt
unter `bd:ki-dev-ablauf-9407` im Repository (nachträglich, nicht
bereits in Stufe 0 wie in den Notes vorgesehen — eine Prozessabweichung, aber
kein offener Blocker mehr).

Folge für den Arbeitsgraphen: `ki-dev-ablauf-3zh` ist als Vorgang materialisiert
und über die Abhängigkeitskette korrekt hinter `ki-dev-ablauf-96c` eingereiht.
Die im Vorgang hinterlegte Eskalationsbedingung
("`bd:ki-dev-ablauf-9407` fehlt") greift nicht mehr, da die Datei
vorhanden ist; sie ist vor dem Start von `ki-dev-ablauf-3zh` nur noch auf
inhaltliche Aktualität zu prüfen.
