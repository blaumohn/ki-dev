# Git- und bd-/Dolt-Schrittdeltas

Dieses Dokument beschreibt den ausfuehrbaren Vertrag des Pakets
`ki_dev.deltas`. Es bildet pro Worker-Schritt den beobachtbaren
Aenderungsnachweis aus den vorhandenen versionierten Wahrheiten (Git und
`bd`/Dolt) und ersetzt damit das fruehere explizite Worker-`RESULT`
(Quellen-Beads ki-dev-ablauf-8ysk und ki-dev-ablauf-rdcs).

Nicht Teil dieses Pakets: Zustandsmaschine, Schleifenverkabelung,
Agentenadapter, Git-Finalisierung nach `PASS`, Dolt-Historienkompaktierung.

## Orchestrator-Abstraktion

Git und `bd`/Dolt folgen demselben Aufbau:

```
Basisreferenz -> genau ein Worker-Schritt -> Ergebnisreferenz -> Delta
```

| Begriff | Git | bd / Dolt |
| --- | --- | --- |
| Referenz | Commit-SHA (`git rev-parse HEAD`) | Dolt-Commit (`bd vc status --json` -> `commit`) |
| Ergebnisgrenze | genau ein angehaengter Checkpoint-Commit | Dolt-Auto-Commit je `bd`-Schreibzugriff |
| Delta | `git diff BASE..RESULT` | `bd diff FROM_REF TO_REF` |

`step_delta` und `run_delta` sind getrennte Sichten desselben Aufbaus:

* `step_delta` – Wirkung genau der aktuellen Worker-Runde
* `run_delta` – kumulierte Wirkung seit Laufbeginn (andere Basis, Label
  `DeltaScope.RUN`)

## Beads-Version und Diff-Schnittstelle

* **Gepinnt / automatisiert geprueft:** `SUPPORTED_BD_VERSION = "1.2.2"`
  (`verify_bd_version()`, Test `test_installed_bd_matches_pinned_version`).
* **Reale Schnittstelle:** `bd diff FROM_REF TO_REF`
  (`BD_DIFF_INTERFACE`), Text und `--json`.
* `bd vc diff` existiert in dieser Version **nicht** und wird nicht
  vorausgesetzt (Test `test_bd_diff_interface_matches_reality`).
* Referenzgrenze: `bd vc status --json`, Feld `commit` (voller
  Dolt-Commit-Hash; die verkuerzte Anzeige aus `bd vc status` ist als
  Diff-Referenz nicht brauchbar).
* `bd diff` schreibt bei gleicher Basis und gleichem Ergebnis
  `No changes between FROM_REF and TO_REF` nach stdout (auch mit
  `--json`) und gibt die angeforderten Referenzen dabei woertlich
  zurueck. Nur genau diese Meldung fuer genau diese beiden Referenzen
  gilt als leerer Delta; jede andere Ausgabe – auch eine leere – ist ein
  `DeltaCommandError`.
* `.beads/issues.jsonl` ist ein passiver Export und niemals die
  Versionswahrheit.

## Oeffentliche Funktionen

Modul `ki_dev.deltas`:

| Funktion | Zweck |
| --- | --- |
| `capture_media_refs(repo)` | Git- und `bd`-Basisreferenz vor dem Schritt bzw. Laufbasis zu Laufbeginn |
| `checkpoint_step_result(repo, *, message)` | Schritt abschliessen: genau einen Git-Checkpoint anhaengen, beide Ergebnisreferenzen erfassen |
| `build_step_delta(repo, base, result)` | Delta genau der aktuellen Runde (`DeltaScope.STEP`) |
| `build_run_delta(repo, run_base, result)` | kumulierter Laufdelta (`DeltaScope.RUN`) |
| `assess_step_delta(step_delta, worker_signal=None)` | No-op-/Ergebnispruefung eines leeren Deltas |
| `verify_bd_version()` / `installed_bd_version()` | gepinnte Beads-Version |

Tiefere Bausteine (`capture_git_ref`, `checkpoint_git_step`,
`build_git_delta`, `capture_beads_ref`, `build_beads_delta`) bleiben
einzeln verfuegbar.

## Zugeschnittener Controller-Kontext

`ControllerContext` buendelt die in Anlage B (Planerausgabe 34)
geforderte Pruefsicht als kleinen strukturierten Vertrag – ohne
Schleifenlogik:

| Feld | Inhalt |
| --- | --- |
| `task` | urspruenglicher TASK (Pflicht, nicht leer) |
| `step_delta` | `CombinedDelta` der aktuellen Runde (Scope `STEP`) |
| `round_status` | `RoundStatus(current, limit)` mit `remaining` |
| `open_objection` | noch offene Beanstandung oder `None` |
| `checks` | `tuple[CheckOutcome, ...]` relevanter Pruefergebnisse |
| `run_delta` | kumulierter Laufdelta (Scope `RUN`) nur bei Bedarf |

Die Scopes werden erzwungen: `step_delta` muss `STEP`, ein gesetzter
`run_delta` muss `RUN` sein.

## Leerer Delta ist kein Erfolg

Ein leerer `step_delta` wird nie automatisch als Erfolg behandelt
(Planerausgabe 15). `assess_step_delta` liefert:

| Ergebnis | Bedingung |
| --- | --- |
| `EFFECTIVE` | Delta nicht leer |
| `EMPTY_WITH_SIGNAL` | Delta leer, Worker meldete `NEEDS_DECISION` oder `ESCALATE` |
| `EMPTY_UNEXPLAINED` | Delta leer, kein Worker-Sonderfall – der Aufrufer muss Rueckkopplung oder Eskalation ausloesen |

## Erhaltung der Pruefgeschichte

Waehrend der aktiven Kontrollschleife wird weder Git- noch Dolt-Historie
umgeschrieben. Der Checkpoint haengt genau einen Commit an; Dolt
versioniert sich selbst. Rebase, Squash und Historienkompaktierung
gehoeren nicht hierher.

## Fehler

Jeder fehlgeschlagene Git-/`bd`-Aufruf wird als `DeltaCommandError`
sichtbar (unbekannte CLI, nicht startbarer Prozess, Exitstatus ungleich
null, unbekannte Referenz, unerwartete Ausgabe). Es gibt keine stillen
Fallbacks.
