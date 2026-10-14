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
| Ops-Katalog | Arbeit, Eingabeaufbereitung, Ergebnisdeutung | `ops/checks`, `flow_ops/implement/ops.py`, `flow_ops/review/` (Ops des Review-Musters) |
| Ausführer | Op starten, Ergebnis sichern, Ereignis senden | `runner/` |

## Gerüst und Paket

Das **Gerüst** ist Mechanik: Kern (`fsm.py`, `flow/model.py`),
Lauf-Maschine `runner/run.toml` mit ihren Ops, Ausführer, gemeinsame
Ops (`ops/`), Übergaben (`runner/turns.py`), Adapter und Executoren
(`adapter/executors.toml`). Es kennt keine Rollen- und Phasennamen.
Ein **Paket** setzt das Gerüst zusammen: Ablauf (`flow/<ablauf>.toml`),
seine Ops (`flow_ops/<paket>/`) und das Profil (Rolle → Executor).

```text
Gerüst sieht:  state="s7", op="op3" → event="e2", executor="claude"
Paket meint:   implement.review, checks → checks_passed, reviewer → claude
```

Abhängigkeit nur Paket → Gerüst. Gemeinsame Teile wie das Review-Muster
mit Vokabular und Befundklassen liegen einmal im Katalog
(`flow/patterns/`). `step` ist kein Ablauf, sondern ein Befehl jedes
Pakets: `ki-dev -f ABLAUF step BEAD ZUSTAND [ZUSTAND=DATEI …]` führt
zustandslos einen Turn mit dem Executor `manual` aus. Der Schichtentest
(`tests/test_schichten.py`) weist Ablauf-, Phasen- und Rollennamen als
Literale in `runner/`, `ops/` und `step/` ab.

### Paket außerhalb des Gerüsts

Ein Paket liegt als eigenes Verzeichnis (eigenes Git-Repo) im Suchpfad
`KI_DEV_FLOW_PATH`. Alles Paketeigene gilt relativ zur Ablaufdatei;
Teile des Gerüsts nennt der Ablauf mit Quelle. Einen Rückfall vom Paket
auf das Gerüst gibt es nicht, Fehlendes ist ein Ladefehler.

| Teil | Paket (relativ zur Ablaufdatei) | Gerüst |
|---|---|---|
| Ops | `ops = "./implement/commands"` | `ops = "ki_dev.flow_ops.review"` |
| Muster | `pattern_catalog = ["./muster/meins"]` | `pattern_catalog = ["ki_dev:review"]` |
| Vorlagen | `templates/<satz>/<name>.txt` | gemeinsame Texte `flow/templates/turns/` |

```text
ablaufpakete/
  implement.toml        ops = "./implement/commands"
  implement/            Ops-Paket, importiert nur relativ und ki_dev
  map.toml …            pattern_catalog = ["ki_dev:review"]
  templates/            Rollenvorlagen
  profiles/             Rolle → Executor
```

Im Agent-Container setzt Compose den Pfad (`docker/agent/README.md`).
Die Abläufe unter `src/ki_dev/flow/` und `flow_ops/implement/` sind bis
`ki-dev-ablauf-cak.7` Übergangsbestand.

## Parametrisierte Übergaben

Eine Übergabe an eine Sitzung (Agent oder Mensch als Bote) entsteht aus
ihrer Deklaration am Zustand oder an der Kante: Vorlage und
Kontextbausteine in ihrer Reihenfolge. So baut ki-dev einen wichtigen
Teil der Anfangsbedingungen einer Sitzung deterministisch aus Ablauf,
Rolle und Bead (Ort im Bead-Graph), für jeden Executor gleich.

```toml
[vocabulary]
context = ["epic_sections", "criteria", "attempt"]

[[state]]
id = "schreiben"
kind = "write"
operation = [{ do = "turn", template = "role-implement", context = [
  { use = "epic_sections" }, { use = "criteria" }, { use = "attempt" },
] }]
```

| Teil | Ort | Beispiel |
|---|---|---|
| Rendern | `runner/turns.py` (`render_turn`) | Vorlage füllen, Bausteine anhängen |
| Gemeinsame Bausteine | `ops/context/blocks.py` (`BLOCKS`) | `epic_sections` (Eltern-Epics), `criteria`, `source_refs`, `guidelines`, `next_steps`, `attempt` |
| Gemeinsame Texte | `flow/templates/turns/` | `epic-intro`, `attempt-line` |
| Rollenvorlagen | `flow/templates/<satz>/` des Pakets | `review/role-implement.txt` |

Ein Paket steckt `Plug(FIELDS, {**BLOCKS, **eigene})` ein und nutzt davon,
was es deklariert; `bind_turns` prüft beim Laden, dass jeder deklarierte
Baustein und jeder Platzhalter eingesteckt ist.

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
pattern_catalog = ["ki_dev:review"]

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

- `ki-dev -f ABLAUF step` (`runner/package.py`): ein Turn des Ablaufs
  ab dem genannten Zustand mit dem Executor `manual`, in einem Lauf nur
  für diesen Aufruf (zustandslos); jede Übergabe (`turn`, `ask`) geht
  über `runner/dispatch.py` an den Boten, mit einer Antwort des Aufrufs
  geht es weiter, sonst gibt step die Übergabe aus. Daten von weiter
  vorn deklariert der Ablauf mit Herkunft (`input` an Operation oder
  Kante). step kennt weder Zustandsarten noch Ereignisse
  eines Musters: Deutung der Antworten, Katalog (`checks` über
  `[op.checks]`), Wächter und Eingaben der Übergaben liefern die Ops
  des Pakets (`ops` des Ablaufs, `step_ops(flow)`, Schnittstelle
  `step/package.py`). Für das Review-Muster nennt der Katalog sie
  einmal: `ops = "ki_dev.flow_ops.review"`.
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
