# README-Durchlauf (Cognitive Walkthrough)

Prüft, ob das README einen Leser bis zu einer Entscheidung trägt. Kein
Software-Test: ein Mensch oder ein Agent spielt die Personas nach und
notiert je Schritt, was er sieht, welchen Eindruck er hat und was er tut
(weiterlesen, klicken, schließen).

## Personas

| Persona | Zeit | Ziel | Entscheidung |
| --- | --- | --- | --- |
| Tech-Lead sichtet eine Bewerbung | 60 s | Kann die Person Systeme bauen? | zum Gespräch einladen oder nicht |
| Entwickler sucht ein Werkzeug | 5 min | Löst es mein Problem, läuft es bei mir? | ausprobieren oder nicht |
| KI-Agent im Repo | ein Lesedurchgang | Wo stehen Ablauf, Befehle, Stand? | richtige Datei öffnen |
| Prüfer verfolgt eine Behauptung | 10 min | Ist sie belegt? Pfad: Befehl → Testnachweis → Details | Behauptung als belegt ansehen oder nicht |

## Schritte

1. Dateiliste auf GitHub (Root): Was fällt auf, bevor das README sichtbar ist?
2. Zeilen 1–15 (5-Sekunden-Test): siehe Bestehenskriterium.
3. Erster Link, den die Persona klicken würde: führt er zu dem, was der
   Linktext verspricht?
4. Erster Shell-Block: versteht man den Ablauf, ohne die Prosa zu lesen?
5. Erste negative Aussage: Wo steht sie, und wie wirkt sie an dieser Stelle?
6. Ende des Pfads: Welche Entscheidung trifft die Persona, nach wie vielen Zeilen?
7. Nur Prüfer: eine Behauptung aus den Zeilen 1–15 wählen. Kann ich sie in
   höchstens 2 Klicks bis zum Befehl und bis zum Testcode verfolgen? Klicks
   ab der Startseite zählen, je Ziel getrennt.

## Bestehenskriterium

Nach den Zeilen 1–15 beantwortet jede Persona:

- Was ist das?
- Für wen?
- Was ist anders als bei einem Prompt-Skript?
- Wie probiere ich es aus?

Bestanden bei 4 von 4. Dazu: keine negative Aussage ohne Einordnung in den
ersten 15 Zeilen, kein Verweis ins Leere (z. B. Bead-ID ohne Link). Für den
Prüfer zusätzlich Schritt 7: Befehl und Testcode je in höchstens 2 Klicks.

Die englische Fassung wird nur in Kopf und Prüfstand auf Gleichheit mit der
deutschen geprüft.

## Protokoll

| Datum | Commit | Persona | Entscheidung nach Zeile | 4 Fragen | Befund |
| --- | --- | --- | --- | --- | --- |
| 2026-10-16 | – | Tech-Lead | 25 (schließt) | 1,5 / 4 | Review-Gate-Lücke im ersten Bildschirm, Demo erst ab Zeile 82 |
| 2026-10-16 | `5d3d4c6` | Tech-Lead | 86 (lädt ein) | 3,5 / 4: „Wie probiere ich es aus?“ fehlt in 1–15, Überschrift erst Zeile 20 | Kopf trägt; Prüfstand mit ✅/❌/⬜ und Mitmachen wirkt als Sorgfaltssignal. Motivation und Bootstrap-Problem erst ab Zeile 462, nach 60 s nicht erreicht; Jargon-Dichte (Bote, Gerüst, `ige.6.4.x`) ab Zeile 135 |
| 2026-10-16 | `5d3d4c6` | Entwickler | 57 (probiert aus, wenn Go vorhanden; sonst Abbruch bei Zeile 26) | 3,5 / 4: wie Tech-Lead | „In einer Minute“, aber Go und C-Compiler nötig. „⬜ nicht ausgeführt“ direkt über der Demo widerspricht Zeile 126 („mit Mock geprüft … `make demo`“). Nach der Demo kein nächster Schritt fürs eigene Repo: Bead als Auftragsquelle und Profil erst ab Zeile 223 |
| 2026-10-16 | `5d3d4c6` | KI-Agent | 456 (öffnet `src/ki_dev/flow/implement.toml` bzw. `docs/ausfuehrer.de.md`) | 3,5 / 4: wie Tech-Lead | Ablauf, Befehle und Stand gefunden (Zeilen 61, 211, 419; `make test` Zeile 404). `AGENTS.md` und `CLAUDE.md` mit 0 Byte, `.agents/`, `.codex/` und 4× `compose*.yaml` im README nicht erklärt. Bead-Kurz-IDs nicht auflösbar: `.beads/` enthält in Git keine Issue-Daten |
| 2026-10-16 | `5d3d4c6` | Prüfer | 76 (Befehl gefunden, Testcode nicht verlinkt) | 3,5 / 4: wie Tech-Lead; Schritt 7: Befehl ✅ 1 Klick, Testcode ❌ | Behauptung Zeile 15 → [Prüfstand] → Befehl in Zeile 76. Testcode nur über den Dateibaum (`tests/` → `machine/` → `test_reachability.py`), dort gut lesbar (`test_no_free_cycle_exists`). Zeilen 13 und 14 führen zu Abschnitten ohne Testbefehl; Zeile 357 („ein Test vergleicht sie“) nennt den Test nicht |

EN-Abgleich `5d3d4c6`: Kopf und Prüfstand inhaltlich gleich (5 Punkte, Stand
und Zähler, 10 Zeilen mit Status, Befehl und Bead). Abweichungen: vor
„## Test bench“ fehlt die Trennlinie `---`; die Statuszeile des Review-Gates
sagt „(spec)“, die Legende „(specification)“.

korrigiert (ki-dev-ablauf-kor, 2026-10-16): Kopfpunkt „Ausprobieren ohne
Anbieterzugang“ mit `make setup && make demo`; Abschnitt heißt jetzt
„Ausprobieren“ (EN „Try it“), Go und C-Compiler begründet (`bd` aus dem
Quellcode), das ⬜ über der Demo eingeordnet und „Lokal mit Mock geprüft“
geschärft; Satz zum eigenen Repo nach der Demo; Prüfstand verlinkt die
Testdatei und nennt die Testfunktion; Kopfzeilen 13/14 und der
Diagrammsatz nennen ihren Test; „Lehrstufen oben“ → „Stufen 1–4 im
Prüfstand“; Linktext „ki-dev am eigenen Repo entwickeln“; EN mit
Trennlinien wie DE. Nicht vom Autor abgenommen; eine zweite Runde ist
nicht vorgesehen.
