# Ausführer-Architektur: was fehlt (Quelle für Kartierung)

Stand 2026-10-14, Sitzung zu `ki-dev-ablauf-ige.6.4`. Quelle für
Kartierung → Graph → Materialisierung → Umsetzung. Noch keine Beads.

## Ziel

- Vor der GitHub-Veröffentlichung ist die Architektur **wahr**: kein
  Teil-Scheinmodell, kein zweiter Ausführer neben dem Gerüst.
- Das Gerüst ist eine kohärente Grundlage mit getrennten
  Untersystemen, jedes mit eigener Begriffswelt; darauf baut man
  Abläufe und Profile, testet, probiert, passt an. Beispiele späterer
  Untersysteme: Projektmanagement (Beads, Graph-Durchgang), adaptive
  Steuerung (nichtdeterministische Rückmeldung, statistische
  Schätzer), Spiegelrollen (Agenten passen das System an).
- Alle bestehenden Merkmale bleiben (Token-, Kontingent-,
  Budgetgrenzen usw.).
- Betrieblich: README-Umbautest besteht (Epic 5wl.1);
  `implement_review` aus dem Paket-Repo läuft weiter; neue Abläufe
  entstehen in Paket-Repos.

## Schichten und Orte

```
Ablauf (TOML)      Zustände, Kanten, cond/unless, Rundengrenzen
  ↑ Paket-Ops      RunModel-Unterklasse: zählt, liest Laufdaten
Runner-SM          run.toml: hold → start → artifact_saved | failed
  ↑ SM-Ops         RunModel: Wächter/Aktionen, nie extern, sofort
Wirkungen          Dispatch (Übergaben), BoundOperations (Katalog)
  ↓                = SCXML <invoke>: extern, dauert, kann abbrechen
Executor/Adapter   claude, codex, manual, mock: Text rein, Text raus;
                   misst (Kontext, Kontingent, Verbrauch)
```

Regeln:

1. Fachliche Entscheidung (was `fix` bedeutet, wann Mensch) →
   Ablauf. Schutz für jeden Ablauf gleich → Gerüst.
2. Was die SM direkt aufruft, wirkt nie nach außen.
3. Dispatch übersetzt nur (Zustand/Ereignis ↔ Prompt/Antwort),
   entscheidet nichts.
4. Grenzen: **Messen** = Wirkung (Adapter); **Vergleichen** =
   Wächter in der SCXML; **Grenzwerte** = Profil-Daten.

Beispiel Kontextgrenze (heute in Python `_context_guard` versteckt):

```
Adapter misst  → 85_000
Ereignis       → measured {context: 85000, quota_left: 8.0}
run.toml       measured cond=within_limits   → start
               measured unless=within_limits → halt.stopped
Profil         max_context_tokens = 80_000 → Halt, sichtbar als Kante
```

Ablauf eines Turns (Beispiel `implement.review`):

```
SM hold op-00000042 (attempt run7:3) → [measured] → start
Dispatch: role review → claude → ask → '{"event":"fix",…}' → read
SM artifact_saved → Ablaufkante review --fix--> correction
```

## Lücken: alter Ausführer → Zielort

Alt: `flow_ops/implement/runtime.py` (~1300 Z.), `machine/`,
`run_machine.py`, `record.py`, `runner/safety.py`. Neu:
`runner/package.py` + `runner/dispatch.py` haben davon nichts.

| Merkmal (Standardwert) | Zielort |
| --- | --- |
| Kontextgrenze `max_context_tokens=80_000` | Messung Adapter, Ereignis + Wächter run.toml, Wert Profil |
| Kontingentreserve `min_remaining_percent=10.0`, Delta `20.0` Pp. | wie oben |
| Budget `max_agent_calls=6`, `max_total_tokens=1e6`, `max_claude_cost_usd=3.0`; Reservierung `call_id` vor `start`, Buchung danach | Wirkung (Ledger) + `pending.call_id` (SM-Op `begin_operation`) |
| Schutzhalt, Fortsetzung am Zustand | run.toml (`failed` → `stopped`, `resume`) |
| Prozessfehler `process_retries=3`, Protokollfehler `protocol_attempts=3` | run.toml (ablaufneutral) |
| Halt-Notiz (`handoffs/r0003-rev000042`) | Gerüst, bei jedem Halt |
| Rundengrenze `changes_rounds=5`, `worker_attempts=12` | Ablauf-Kante + Paket-Wächter |
| `changes_refused` (`max_failed_corrections=2`), `stagnation` (`max_stagnant_changes=3`, gleiche `requirement_ref`) | Ablauf-Kante + Paket-Wächter |
| leeres Ergebnis `delta_effective` | Ablauf; **offen:** Vorlauf-Ereignis (`checks_empty`) oder eigener Wächter |
| Finalisierung freeze → finalize_history → verify_final → integrate | Muster-Variante nach PASS + `[op.*]` in ops/ |
| `-f implement` start/resume/status | PackageRunner + Dispatch, Executoren aus Profil |

## Vorschlag Schnitt (für die Kartierung)

1. Gerüst: Messung als Ereignis, Grenzwächter in run.toml, Ledger
   als Wirkung, Schutzhalt.
2. Gerüst: Wiederholung Prozess-/Protokollfehler, Halt-Notiz.
3. Paket/Muster: Rundengrenze, `changes_refused`, `stagnation`,
   leeres Ergebnis.
4. Muster + ops: Finalisierung.
5. Umstellung: ein `flow/implement.toml`, `-f implement` auf dem
   einen Ausführer, `implement_review.toml` und alter Ausführer weg,
   Tests (~15 Dateien: safety, context_guard, quota_guard, usage_*,
   runner_runtime …) auf neuen Pfad, Doku.

Erledigt in dieser Sitzung: ige.6.6 (Umbenennung `answers.py`,
`PackageOps`), ige.6.5 (Antwortformat in Schreib-/Korrekturvorlagen;
Tests ignorieren `KI_DEV_FLOW_PATH` der Umgebung). Das Paket-Repo
`.local/ablaufpakete` hat die neuen Vorlagen noch nicht.
