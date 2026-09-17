# Startfreigabe p0h

Stand: 16. September 2026. Bezug: `ki-dev-ablauf-p0h` (Materialisierung nach
dem Verbrauchsvorfall `uar-2-02`, siehe
[uar-2-02-verbrauch.md](uar-2-02-verbrauch.md)). Diese Aufgabe selbst hat
keinen Agentenlauf ausgeloest; die kostenpflichtige Ausfuehrung und die
unabhaengige Bewertung bleiben ausschliesslich uar.2/uar.3 vorbehalten.

## Umgesetzte Pakete

| Paket | Ergebnis |
| --- | --- |
| p0h.1 Auftragsbindung | `LoopTask.acceptance_criteria` + `ReviewDecision.requirement_ref`; CHANGES ohne bekannte Referenz wird zu `NEEDS_DECISION`, nicht automatisch als Reparaturauftrag uebernommen. |
| p0h.2 Lesender Statuspfad | `ki-dev loop status <run_id>`: liest den Checkpoint ueber eine private WAL/SHM-Kopie, ohne `LoopRuntime` schreibfaehig aufzubauen. |
| p0h.3 Worker-Umgebung | `TurnRequest`/`LoopTask` binden `workdir`/`env` technisch (cwd, PYTHONPATH-Ueberlagerung) statt nur im Prompt; jede Eskalation schreibt eine kompakte Uebergabe nach `<run>/handoff/`. Keine automatische Sitzungsrotation (Sitzungen sind aufrufergebunden, siehe uar.1). |
| p0h.4 Eskalation bei Stillstand | `stagnation_reason()` haelt bei wiederholtem CHANGES an derselben Referenz vor dem naechsten Bauaufruf an, berechnet aus persistierten Nachrichten (kein Reset bei Neustart). |
| p0h.5 Diff-Projektion | Audit von `review_context.py` (jbr.1): Binaerdateien tragen jetzt eine Git-Blob-Referenz, generierte Lockfiles werden zusammengefasst statt voll angezeigt; die uebrigen vier Regressionsfaelle (grosse Diffs, JSON-Einzeiler, rekursive Laufartefakte) waren bereits abgedeckt. |

## Offline-/Fake-Integrationsnachweis (p0h.6)

`tests/test_offline_startup_readiness.py` verbindet Reader, Auftragsbindung,
Fortschrittsregel, Umgebungsbindung und Diff-Projektion gegen einen echten
Git-/Beads-Worktree; ein `FakeExecutor` ersetzt ausschliesslich den externen
CLI-Prozess, Auftragsbindung/Fortschrittsregel/Statuspfad/Projektion laufen
im echten Produktionscode:

- `test_offline_run_connects_reader_contract_progress_env_projection`:
  CHANGES mit echter Referenzbindung (`AC1`), echter, per Git erzeugter Diff
  erreicht den Reviewer, Korrektur fuehrt zu PASS, `ki-dev loop status`
  liest denselben Endzustand rein lesend.
- `test_offline_run_pauses_on_stagnation_and_stays_readable`: zwei CHANGES
  in Folge an derselben Referenz halten vor der dritten Baurunde an,
  schreiben eine Handoff-Datei und bleiben danach unveraendert lesbar.

## Effektive Konfiguration und Codeherkunft

Erhoben am 2026-09-16 auf diesem Stand (`git rev-parse HEAD` nach dem
p0h.6-Commit):

```text
Interpreter:  /workspace/.venv/bin/python (Python 3.12.14)
ki_dev-Modul: /workspace/src/ki_dev/__init__.py
git:          2.39.5
bd:           1.2.2 (6c124203e)
```

Effektive `safety_limits` (Standardwerte, wie sie ein neuer Lauf ohne
Ueberschreibung im Manifest persistieren wuerde):

```json
{
  "max_agent_calls": 6,
  "max_total_tokens": 1000000,
  "max_claude_cost_usd": 3.0,
  "max_failed_corrections": 2,
  "max_stagnant_changes": 3
}
```

Effektive Rollen-Budgets (`build`/`review`, gleicher Standard fuer beide):

```json
{
  "max_turns": 12,
  "max_budget_usd": 1.0,
  "max_context_tokens": 80000,
  "timeout_s": 180.0
}
```

Diese Werte sind konservative Betriebsvorgaben, keine aus dem Abo
abgeleiteten Garantien (siehe Verbrauchsschutz-Abschnitt in
[loop-runtime.de.md](../loop-runtime.de.md)).

## Testnachweis

654 Tests gruen (mehrfach wiederholt, keine Flakes beobachtet); Ruff fuer
alle in p0h geaenderten Dateien ohne Befund. Kein Docker-/Containerlauf und
kein bezahlter CLI-Aufruf Teil dieses Nachweises.

Zwei unabhaengige Reviewrunden dieser Commits fanden fuenf Befunde
(einer davon -- `ucq` -- nach einer ersten Behebung nochmal
wiedereroeffnet), die vor dieser Startfreigabe behoben wurden:

1. Eine SQLite-Snapshot-Race beim Statuslesen -- jetzt ueber die
   Online-Backup-API statt manueller WAL-/Hauptdatei-Kopie (`re0`).
2. Fehlende Abnahmekriterien im Bauauftrag -- jetzt auch dort gelistet,
   nicht nur im Reviewer-Prompt (`ygq`).
3. Ein Reviewer-`ESCALATE`, das die Sitzungsuebergabe umging (`ucq`,
   nach Wiedereroeffnung auch fuer fehlgeschlagene Abschlusspruefung und
   Integration behoben -- alle Pausepfade schreiben jetzt einheitlich
   ueber `_write_handoff_if_stopped`).
4. Fehlende Validierung von `status`/`round_id` beim Statuslesen
   (`8to`).
5. `ki-dev loop status` scheiterte mit dem relativen CLI-Standardpfad
   `--runs-dir .ki-dev/runs`, da `Path.as_uri()` einen absoluten Pfad
   verlangt (`0we`); mit echtem `ki-dev`-CLI-Aufruf verifiziert.

Alle sechs sind in Beads geschlossen und durch Regressionstests
abgedeckt.

## Bekannte Grenzen vor uar.2

- Die kompakte Sitzungsuebergabe (p0h.3) deckt nur Erkennung, Pause und
  Persistenz ab; die frische Rollensitzung selbst muss ein Mensch weiterhin
  ausserhalb von ki-dev vorbereiten (uar.1-Modell: aufrufergebundene
  `session_id`).
- `safety_limits`/Rollen-Budgets sind Betriebsvorgaben; sie belegen keine
  Abo-Kontingentprozente.
- uar-2-02s alter, pausierter Lauf und seine Scratch-Worktrees wurden nicht
  fortgesetzt oder nachtraeglich als erfolgreich erklaert; ein Ersatzlauf
  fuer uar.2 braucht eine eigene, frische Vorbereitung nach uar.1.

## Ergebnis

Mit den Nachweisen oben ist die Offline-Startfreigabe erfuellt; `uar.2` ist
in Beads entsprechend nicht mehr an `p0h.6` blockiert. Der kostenpflichtige
Echtlauf und die unabhaengige Abschlussbewertung bleiben ausschliesslich
Sache von `uar.2`/`uar.3`.
