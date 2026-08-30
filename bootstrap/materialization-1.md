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

Abhängigkeitskette: `ki-dev-ablauf-96c` → `ki-dev-ablauf-i7n` → `ki-dev-ablauf-ie5`
(jeweils "hängt ab von", Pfeilrichtung = blockiert durch).

## Abschlussprüfung

```bash
bd list --json
bd dep cycles
git diff --check
```

- `bd dep cycles` meldet keine Zyklen.
- `bd ready --json` liefert zum Zeitpunkt dieser Materialisierung genau
  `ki-dev-ablauf-ie5`, da die beiden Folgevorgänge von ihm abhängen.
- Der tatsächliche `bd`-Bestand (`bd list --json`) entspricht der obigen
  Tabelle.

Bootstrap-Stufe 4 (Verarbeitung von `bd:ki-dev-ablauf-9407`) ist
nicht Teil dieser Materialisierung; sie folgt erst nach `ki-dev-ablauf-96c`.
