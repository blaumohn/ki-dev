---
layout: page
title: Bindungen, Ops-Katalog und gemeinsame Muster
permalink: /de/ablaufpakete/
---

Ein Ablauf (`flow/*.toml`) bestimmt, wann gearbeitet wird und wie es
danach weitergeht. Die Arbeit selbst steht einmal in Python im
Ops-Katalog. Der Ausführer startet Operationen, speichert ihre Ergebnisse
und setzt Läufe fort.

| Schicht | Aufgabe | Ort |
|---|---|---|
| Ablauf | Zustände, Kanten, Bindungen `[op.*]` | `flow/map.toml`, `flow/implement_review.toml`, `flow/implement.toml` |
| Gemeinsame Muster | wiederkehrende Abschnitte | `flow/patterns/review.toml` |
| Ops-Katalog | Arbeit, Eingabeaufbereitung, Ergebnisdeutung | `ops/checks`, `flow_ops/implement/ops.py` |
| Ausführer | Op starten, Ergebnis sichern, Ereignis senden | `runner/` |

## Eine Bindung

```toml
[op.finalize_history]
do = "git.finalize_history"
input = ["frozen_result"]
output = "final_result"
success = "history_finalized"
```

Der Ausführer liest `frozen_result`, ruft den Katalogeintrag
`git.finalize_history` auf, sichert das Artefakt, legt es unter
`final_result` ab und sendet `history_finalized`. Welche Kante dieses
Ereignis nimmt, wählt die Statechart-Bibliothek.

Mehrere Ergebnisfelder stehen als explizite Feldpfade da, keine
Ausdrücke:

```toml
output = { work_report = ["summary"] }
```

Liefert die Op selbst ein Ereignis (Review, Vorlauf), nennt die Bindung
statt `success` das erlaubte Vokabular:

```toml
[op.checks]
do = "checks.preflight"
input = []
output = {}
events = ["checks_passed", "checks_partial", "checks_failed"]
```

`success` und `events` schließen sich aus. JSON Schema prüft Bindungen,
Eingaben und Ergebnisse (`flow/binding.py`). Unbekannte Ops, ungenutzte
Bindungen und Ereignisse ohne Kante weist der Lader ab; ein Ereignis
außerhalb der Bindung weist der Ausführer ab. Austauschbar ist eine Op
nur mit demselben Datenvertrag: ein Patch ersetzt keinen Commit, wenn
die Folgeschritte einen Commit erwarten.

## Gemeinsame Muster

Jeder Review-Ablauf (`map`, `graph`, `materialize`, `implement_review`)
lädt seine Review-Topologie und die gemeinsamen Teile (Vokabular,
Befundklassen, `source`/`finished`) aus dem Katalog:

```toml
pattern_catalog = ["review"]

[[phase]]
id = "graph"
use = "write_review"
next = "materialize"
```

`flow/patterns/review.toml` enthält `review_core` (Schreiben, Review,
Korrektur, Entscheidung) und die Varianten `write_review` und
`write_review_preflight` einmal. Eine Phase liefert nur Parameter
(nächste Phase, Akteure, Hinweise, Vorlagen). Ein Ablauf darf ein
gemeinsames Muster nicht überschreiben; eine Variante ist ein neues
Muster mit `extends`, kein Schalter.

## Ausführer

- `ki-dev step` (`runner/planning.py`): ein Turn des gewählten Ablaufs
  mit dem Executor `manual`; `turn` und `ask` sind Halte, `checks`
  läuft über `[op.checks]` und den Katalog, den `step` einsteckt.
- `ki-dev -f implement` (Paket `flow_ops/implement/`, eigener Ausführer
  `runtime.py`): die sieben externen Operationen (Arbeit, Nachweise,
  Review, Einfrieren, Historie, Prüfung, Integration) laufen über ihre
  Bindungen in `implement.toml`.
- `runner/package.py` ist der generische Ausführer ohne Fachwissen:
  Regionen aus `runner/run.toml`, `RunStore`, Abbruchfenster
  (`repeatable`, `uncertain`, `reconcile`). Ihn prüfen die Tests mit
  einem Testablauf (`tests/package_fixtures.py`).

Noch offen: `implement` und `implement_review` werden ein Ablauf auf
dem gemeinsamen Ausführer mit parametrisierten Übergaben für manual und
Agenten (`ki-dev-ablauf-ige.6`, `ki-dev-ablauf-ige.7`).
