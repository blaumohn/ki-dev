# Manuelle Arbeitsübergaben mit `ki-dev -f ABLAUF step`

`step` ist ein zustandsloser Haltepunkt vor einer Übergabe an einen
Executor: Debug und Spielplatz für Abläufe. Jedes Paket hat den Befehl;
der Ablauf kommt wie bei `-f` aus Name oder Pfad
([`map`](../src/ki_dev/flow/map.toml), [`graph`](../src/ki_dev/flow/graph.toml),
[`materialize`](../src/ki_dev/flow/materialize.toml),
[`implement_review`](../src/ki_dev/flow/implement_review.toml) oder ein
eigener Ablauf mit `ops`).

```bash
ki-dev -f ABLAUF step BEAD_ID ZUSTAND [ZUSTAND=DATEI ...]
```

- **ZUSTAND** ist ein Zustand mit Übergabe an einen Executor (`turn` oder
  `ask`); `ki-dev flow show ABLAUF` zeigt sie. Ein Zustand ohne Übergabe
  (etwa der Vorlauf `implement.preflight` oder `finished`) ist Exit 2.
- **Ohne Antwort für ZUSTAND** gibt step dessen Übergabe aus.
- **Mit `ZUSTAND=DATEI`** hat ZUSTAND geantwortet: die Datei ist, was
  sonst der Agent zurückgibt. Dieselben Ops des Pakets prüfen und deuten
  sie (z. B. Review-Urteil `fix`), der Ablauf wählt die Kante wie beim
  Ausführer, step fährt Maschinenzustände wie den Vorlauf selbst und gibt
  die nächste Übergabe aus oder, am Ende, die Nachricht der letzten Kante.
- **Weitere `ZUSTAND=DATEI`** liefern Daten von weiter vorn: die Datei ist
  die Antwort dieses Zustands (bei einer Katalogoperation wie dem Vorlauf
  ihr Ergebnis). Was eine Übergabe oder Kante davon braucht, deklariert
  der Ablauf mit Herkunft (`input`, siehe
  [Daten von weiter vorn](#daten-von-weiter-vorn-input)); fehlt eine
  Eingabe, ist das Exit 2 mit Name und Herkunft.
- `DATEI` `-` liest stdin (höchstens einmal je Aufruf); eine Antwort hat
  höchstens 20000 Zeichen, nie gekürzt.

```bash
ki-dev -f map step projekt-42 map                          # Übergabe an den Kartierungsagenten
ki-dev -f map step projekt-42 map.review                   # Übergabe an das Review
ki-dev -f map step projekt-42 map.review map.review=review.json
                                                           # Urteil fix → Übergabe an die Korrektur
ki-dev -f map step projekt-42 map.correction map.correction=done.json
                                                           # Korrektur erledigt → Folgenachricht an das Review
ki-dev -f implement_review step projekt-42 implement implement=done.json
                                                           # Umsetzung erledigt → Vorlauf → Review
```

**Zustandslos.** Jeder Aufruf fährt einen Lauf, der nur für diesen Aufruf
besteht (`runner/package.py`, Ablauf als Region der Lauf-Maschine
`runner/run.toml`, Ablage in einem temporären Verzeichnis); gespeichert
wird nichts, kein Halt, kein Versuch, kein Protokoll. Gleiche Eingabe gibt
gleiche Ausgabe (der Prüfbericht trägt seinen Zeitstempel). Es gibt keine
Versuchskennung (`attempt`): sie bände eine Antwort an einen Lauf, den es
nicht gibt.

**Der Mensch ist verantwortlich.** step gleicht nichts mit dem Stand des
Repos ab und erinnert keinen früheren Aufruf. Welche Antworten du
mitgibst und ob sie zum Arbeitsstand passen, entscheidest du; step prüft
sie nur formal, wie der Ausführer es bei einem Agenten täte, und errät
nichts (Programmierleitlinie: Fallbacks verdecken keine Fehler).

**Ops des Pakets.** Was eine Antwort bedeutet, welche Katalogoperationen
(Vorlauf) eingesteckt werden und welche Eingaben eine Übergabe braucht,
liefern die Ops des Pakets: das Modul `ops` des Ablaufs mit
`package_ops(flow)` (Schnittstelle `src/ki_dev/step/package.py`); für alle
Abläufe auf dem Review-Muster nennt der Katalog
`flow/patterns/review.toml` einmal `ki_dev.flow_ops.review`. step kennt
weder Zustandsarten noch Ereignisse eines Musters.

**Transport.** step und `ki-dev -f implement` übergeben an den Boten über
dieselbe Funktion des Adapters `manual` (`ki_dev.adapter.manual.send`);
gerendert wird jede Übergabe vom Ausführer (`ki_dev.runner.turns`) aus
der Deklaration im Ablauf: Vorlage und Kontextbausteine je Zustand oder,
wenn die Kante sie bestimmt, je Übergang. step liest den Bead nur
(`bd --readonly show BEAD_ID --json`, Frist 10 s) und startet keinen
Agenten; du startest die Sitzung selbst und fügst den Text dort ein.
Läuft ein Aufruf durch den Vorlauf, führt dieser konfigurierte Befehle aus
(siehe [Vorlauf](#deterministischer-vorlauf-vor-der-review-übergabe)).

Die Ausgabe ist unfarbiger Klartext ohne Zeilenumbruch nach
Terminalbreite; sie lässt sich umleiten (`… > uebergabe.txt`).
`ki-dev -f map step --help` fasst das auf Deutsch zusammen. Die Daten
heißen weiter „Übergabe“ (`handoff`): `metadata.handoff`, die
pyproject-Abschnitte `tool.ki-dev.handoff.*` und Artefakte unter
`.local/handoff/`.

Ohne Ablaufposition bleiben zwei Formen von `ki-dev step`: `local`
(freie Sitzung) und `map --agent … --session …`
([Sitzung als Quelle](#sitzung-als-quelle-step-map)). `ki-dev step BEAD`
und die früheren Optionen `--step`, `--review-of`, `--next-turn`,
`--feedback-file` und `--decision-file` gibt es nicht mehr (Exit 2, kein
Alias).

## Freie lokale Sitzung (`step local`)

```bash
ki-dev step local > uebergabe.txt
```

Für Sitzungen ohne Auftrag aus Beads. Der Aufruf braucht weder Bead noch
Datenbankverbindung noch `bd` im PATH und schreibt nichts. Mit `--agent`,
`--session` oder `--title` kombiniert endet er mit Exit 2.
Die Ausgabe besteht aus einer festen kurzen Basis (`Schritt: local`) und dem
gesonderten Leitlinienblock mit den allgemeinen Abschnitten (`common`) aller
Regelquellen (siehe [Mitgelieferte Leitlinien](#mitgelieferte-leitlinien));
die phasenspezifischen Abschnitte gehören nicht dazu. Die Basisgrenze
(`base_max_chars`) gilt nur für die Basis; Leitlinienquelle fehlt: Exit 1,
ungültig: Exit 2.

Es ist keine Planungsrolle gewählt: Die Übergabe nennt nur Lesebefehle
(`bd show/ready/prime`) und keine Aufforderung zu `--claim` oder `close`. Eine
ausdrücklich wählbare Planungsrolle gibt es nicht; wer Beads-Status ändern
soll, sagt das in der Sitzung selbst.

## Pflichtfelder je Schritt

Welche Bead-Felder eine Übergabe braucht, steht im Ablauf am Zustand
(`[phase.require]`, z. B. `review = ["source_refs"]`); die Prüfung in
`ops/context` kennt keine Phase. Die Tabellen unten zeigen die Werte
der mitgelieferten Abläufe.

### Geerbte Epic-Hinweise

Ein Epic-Hinweis vermittelt Ziel, Zusammenhang und begründende Entscheidungen
des Elternvorhabens. Er hilft dem Agenten, die Aufgabe eines untergeordneten
Vorgangs im Ganzen zu verstehen und eine dazu passende Lösung zu entwickeln.
Die Übergabe fordert dazu auf, diesen Kontext zu berücksichtigen und
Widersprüche zum konkreten Auftrag zu melden.

Beispiel für den Kontext eines Epics:

> Wir erproben manuelle Agentenübergaben, bevor wir den Ablauf automatisieren.
> Der Mensch startet die Sitzungen und entscheidet über weitere Schritte.

Ein Kind-Vorgang zur Vorbereitung einer Übergabe kann daraus verstehen,
warum ein automatischer Agentenstart am Ziel des Epics vorbeigehen würde.
Der Hinweis darf auch geltende Einschränkungen enthalten; sein Zweck reicht
über eine Sammlung von Handlungsregeln hinaus.

Untergeordnete Vorgänge erben automatisch `metadata.handoff.epic_context`
aus ihren Epic-Vorfahren über Beads-Beziehungen vom Typ `parent-child`.
Auch Zwischenvorgänge ohne eigenen Hinweis unterbrechen die Vererbung nicht.
Die Ausgabe nennt die Epic-ID und zeigt Hinweise vom äußersten zum nächsten
Epic; sie werden nicht überschrieben. Blockierungs- und Herkunftsbeziehungen
liefern keinen Kontext. Widersprüche klärt der Mensch.

Das Feld `epic_context` enthält diesen Epic-Kontext. Es gibt
kein zusätzliches Pflichtfeld und keine automatische Bewertung, ob ein Text
das Epic inhaltlich ausreichend erklärt.

Das optionale Feld enthält einen nichtleeren Text mit höchstens 600 Zeichen.
Fehlerhafte Hinweise, nicht lesbare Eltern, mehrdeutige Eltern und Zyklen
verhindern eine unvollständige Übergabe (Exit 1). Eltern ohne Hinweis bleiben
stumm; ihre Beschreibungen, Notizen und Kommentare werden nicht übernommen.

Beispiel: `ki-dev-ablauf-zip` bündelt die Handoff-Vorgänge. Bei
`ki-dev -f implement_review step ki-dev-ablauf-prx implement` erscheint automatisch:

> Epic-Hinweis (ki-dev-ablauf-zip): Experimenteller „mensch-dev loop“ …

Der Hinweis wird einmal am Epic gepflegt, nicht in jedem Kind verknüpft.

### Pflichtwerte

Immer: `id`, `title`, `description` als nichtleere Strings.

| Zustand | zusätzlich |
| --- | --- |
| `map`, `graph`, `materialize` (und ihr `.review`) | `metadata.handoff.source_refs` |
| `implement`, `implement.review` | `acceptance_criteria`, `design` |

Geprüft wird der Zustand des Aufrufs und jede ausgegebene Übergabe.
`implement` und `implement.review` brauchen keine Metadaten; fehlende Metadaten blockieren nur
`map`, `graph` und `materialize`. `design` soll die relevanten
Schnittstellen/Code-Einstiege und die konkreten Prüfaufträge enthalten. Das
Werkzeug prüft nur Vorhandensein und Typ, nicht die inhaltliche
Ausführungsreife.

### Antworten im Review-Muster

Die Ops des Review-Musters (`ki_dev.flow_ops.review`) deuten die
Antworten je Zustandsart; jede Antwort ist ein JSON-Objekt:

| Zustand | Antwort | Ereignis |
| --- | --- | --- |
| `P`, `P.correction` (Schreiben, Korrektur) | `{}` oder `{"feedback": "…"}` | `done` |
| `P.review` | `{"event", "detail", "requirement_ref"}`, optional `preflight_args`/`preflight_skip` | das Urteil |
| `P.decision`, `source` (Mensch) | `{"event": "accept"}` (bzw. `correct`, `source`, `imported`) | das genannte |

**Rückmeldung.** `feedback` ist die Rückmeldung des Schreibagenten: nur,
was nicht aus Diff und Prüfergebnissen hervorgeht. Sie erscheint in der
nächsten Nachricht als unbestätigte Aussage (nicht geprüft, kein Beleg,
Zeilen mit `| ` zitiert, Steuerzeichen entfernt). Grenze:
`[tool.ki-dev.handoff] feedback_max_chars` in `pyproject.toml`, eine
positive ganze Zahl (Standard 600, auch ohne Datei), Unicode-Zeichen
einschließlich Leerraum; leer, zu lang oder ungültig konfiguriert ist
Exit 2, nie gekürzt. `bd`-Notizen und -Kommentare werden weder gelesen
noch beschrieben.

**Urteil.** Die Review-Antwort folgt dem gemeinsamen Vertrag von step und
`ki-dev -f implement` (`src/ki_dev/review_decision.py`):

```json
{"event": "fix", "detail": "Test für leere Eingabe fehlt", "requirement_ref": "AC2"}
```

`event` ist `PASS` oder eine Befundklasse (`fix`, `source`, `decision`);
das Urteil (`CHANGES`, `NEEDS_DECISION`) folgt aus der Klasse.
Nicht-PASS braucht `detail`. `requirement_ref` ist immer vorhanden: bei
`fix` `"AC<n>"` (ohne gültige Referenz wird daraus `decision`), sonst
`null`. Zeilen `N.` in `acceptance_criteria` ergeben `AC1..ACn`, ohne
Nummerierung ist das ganze Feld `AC1`; eine Nummerierung mit Lücke oder
Doppel ist ein formaler Mangel (Exit 2). Ungültiges JSON, fremde Felder,
`escalate` oder verletzte Feldregeln: Exit 2 mit Feldpfad, ohne Rohwerte.

| Antwort | nächste Übergabe | Kante |
| --- | --- | --- |
| `fix` mit gültigem `AC<n>` | Schreibagent (bisherige Sitzung) | `fix → P.correction` |
| `fix` ohne/mit fremdem `AC` | Mensch, als `decision` | `decision → P.decision` |
| `source` | Mensch | `source → source` |
| `decision` | Mensch | `decision → P.decision` |
| `PASS` | Mensch (Ende) | `PASS → finished` |

```bash
ki-dev -f implement_review step projekt-42 implement.review \
  implement.review=antwort.json implement.preflight=vorlauf.json
pbpaste | ki-dev -f map step projekt-42 map.review map.review=-
```

**PASS nach dem Vorlauf.** In `implement_review` trägt die Kante `PASS`
den Wächter `full_checks` (kein Teillauf) und deklariert die Tatsachen
des Vorlaufs als Eingabe (`facts` aus `implement.preflight`). Ohne sie
endet der Aufruf mit Exit 2:

```text
implement.review --PASS--> braucht facts (aus implement.preflight; Antwort mitgeben: implement.preflight=DATEI.json)
```

Die Antwort des Vorlaufs ist sein Ergebnis, etwa
`{"event": "checks_passed", "facts": ["full_checks"], "report": null, "finding": null}`.
step prüft nur ihre Form, nicht ob sie zum Arbeitsstand passt; das
verantwortest du. Nach einem Teillauf (`"facts": []`) weist der Wächter
PASS ab (Exit 2).

**Begrenzte Prüfsteuerung des Reviewers.** Bei jedem Ereignis außer
`PASS` darf die Review-Antwort den Prüfumfang der nächsten Runde
vorschlagen (`"preflight_args": {"tests": "-k test_review"}`,
`"preflight_skip": {"lint": "nur Doku geändert"}`). step prüft die Werte
mit denselben Regeln wie die Optionen gegen die Vorlauf-Konfiguration und
gibt sie in der Nachricht an den Umsetzer aus; anwenden tust du sie, indem
du sie an den nächsten Aufruf mit Vorlauf hängst. Nie bei `PASS` (ein
PASS braucht den Volllauf). Ungültige Steuerung: Exit 2.

### Daten von weiter vorn (`input`)

Eine Übergabe oder Kante kann Laufdaten brauchen, die ein früherer
Zustand liefert. Der Ablauf deklariert sie mit ihrer Herkunft:

```toml
[[state]]
id = "summary"
kind = "work"
operation = [{ do = "turn", template = "summary", input = { report = "work" } }]
```

Im Review-Muster braucht die Korrektur das Urteil des Reviews
(`input = { verdict = "review" }`, lokale Namen), die Review-Übergabe in
`implement_review` Tatsachen und Bericht des Vorlaufs (`[phase.input]`),
die Kante `PASS` dort die Tatsachen. Liefert der Aufruf eine Eingabe
nicht, weder als Antwort dieses Aufrufs noch als `ZUSTAND=DATEI`, ist das
Exit 2 mit Name und Herkunft:

```text
ki-dev -f map step projekt-42 map.correction
map.correction braucht verdict (aus map.review; Antwort mitgeben: map.review=DATEI.json)
ki-dev -f map step projekt-42 map.correction map.review=review.json   # Übergabe an die Korrektur
```

Die Eingabe gilt für die Übergabe bzw. Kante, nicht für die Antwort auf
sie: wer `map.correction=done.json` mitgibt, braucht das Urteil nicht.
Fehlt einer Übergabe ein Datum, das der Ablauf nicht deklariert, nennt
step nur den Namen.

### Folgenachricht nach einer Korrektur

```bash
ki-dev -f map step projekt-42 map.correction map.correction=done.json
ki-dev -f implement_review step projekt-42 implement.correction implement.correction=done.json
```

Die Kante `P.correction --done-->` bestimmt die Nachricht selbst: eine
kurze Folgenachricht in die bisherige, vom Autor getrennte
Review-Sitzung (Reviewziel, Bead, Prüfauftrag, Bericht, Rückmeldung),
keine zweite Rollenübergabe; eine frische Sitzung bekommt die Übergabe
von `P.review`. In `implement_review` läuft vorher der Vorlauf:

| Ablauf | Ergebnis | Empfänger, stdout, Exit |
| --- | --- | --- |
| `implement_review` | Vorlauf fehlgeschlagen (Korrektur, Prüfung, Start, Timeout, Artefakt) | Umsetzer: Reparaturnachricht mit Befund und Grenze der Rückmeldung; Exit 1 |
| `implement_review` | Vorlauf bestanden | bisherige Review-Sitzung: Korrekturen und betroffene Kriterien samt Regressionen erneut prüfen, Prüfbericht beigefügt; Exit 0 |
| `map`, `graph`, `materialize` | ohne Vorlauf | dieselbe Review-Sitzung: erneute, phasengerechte Prüfung; Exit 0 |

Der Fortschritt des Vorlaufs steht auf stderr, die Nachricht auf stdout
(auch bei Exit 1). `checks_partial` erreicht das Review, aber kein PASS.

### `--preflight-args`/`--preflight-skip`: Teillauf mit begründetem Umfang

Scheitert der Vorlauf an einem unabhängigen Test, hängt `--preflight-args
NAME=ARGS` die Argumente einmalig an die Prüfung `NAME` an;
`--preflight-skip NAME=GRUND` lässt sie begründet aus. `pyproject.toml`
bleibt unverändert:

```bash
ki-dev -f implement_review step projekt-42 implement implement=done.json \
  --preflight-args 'tests=-k "not langsam"'
ki-dev -f implement_review step projekt-42 implement.correction \
  implement.correction=done.json --preflight-skip 'lint=nur Doku geändert'
```

`ARGS` wird wie in einer Shell zerlegt und hat keine Längengrenze. `GRUND`
ist einzeilig, nichtleer und höchstens 200 Zeichen lang. Beide Optionen sind
wiederholbar (je Prüfung einmal), gelten nur für einen Ablauf, der den
Vorlauf bindet (`implement_review`; sonst Exit 2), und nur für Prüfungen, nie
für Korrekturen. Exit 2 vor jeder Schreibwirkung: fehlendes `=`, leerer Name,
leere `ARGS`, ungültiger `GRUND`, unvollständiges Quoting, NUL/CR/LF,
doppelte Prüfung, dieselbe Prüfung in beiden Optionen, unbekannter Name oder
Name einer Korrektur (stderr nennt die vorhandenen Prüfungen).

Jede Angabe macht den Lauf zum **Teillauf**. Er erlaubt ein Zwischenreview,
aber keinen PASS: Bericht und Folgerunde enthalten den Absatz `TEILLAUF`, die
Folgerunde verlangt die stärkste Befundklasse statt `PASS`. Ein PASS braucht einen
vollständigen Vorlauf ohne diese Optionen. Drei Dinge bleiben getrennt:

| Begriff | Bedeutung | Folge |
| --- | --- | --- |
| `valid` | alle gelaufenen Befehle bestanden | sonst Nachricht an den Umsetzer (Exit 1) |
| `partial` | Zusatzargumente oder Auslassungen | kein PASS |
| Ausführungsfehler | Vorlauf nicht kontrolliert abgeschlossen | Exit 1, Reparaturnachricht statt Übergabe |

Die Angaben bleiben sichtbar: Ergänzte Zeilen tragen `[ergänzt per
--preflight-args]`, ausgelassene stehen als `SKIPPED` mit Grund im Bericht.
Das Prüfartefakt nennt `added_args`, `skip_reason` und `partial`.

Die frische Sitzung startest du selbst; `step` startet keinen Agenten
und schließt sie nicht automatisch. Optional kannst du dafür ein anderes
Modell oder einen anderen Anbieter wählen – kein Anbieter ist
vorgeschrieben, es gibt keine automatische Übermittlung oder
Modellanfrage und **keine Garantie unabhängiger Fehler**: Ein anderes
Modell kann dieselben Lücken übersehen.

| Review-Zustand | zusätzliche Pflichtfelder | deterministischer Vorlauf |
| --- | --- | --- |
| `map.review` | `metadata.handoff.source_refs` | nein |
| `graph.review` | `metadata.handoff.source_refs` | nein |
| `materialize.review` | `metadata.handoff.source_refs`, `acceptance_criteria`, `design` | nein |
| `implement.review` | `acceptance_criteria`, `design` | ja (davor `implement.preflight`) |

Nur `implement_review` bindet den
[deterministischen Vorlauf](#deterministischer-vorlauf-vor-der-review-übergabe)
aus `ops/checks/preflight.py` (Operation `checks`, eingesteckt von den Ops
des Musters); `map`, `graph` und `materialize` sind reine,
lesende Quellenprüfungen ohne Prozessaufrufe und ohne `pyproject.toml`. Für
`materialize` gilt zusätzlich: Es reicht nicht, den fertig materialisierten
Auftrag gegen sich selbst zu prüfen – das Review vergleicht ihn gegen die
ursprünglichen, bestätigten Nutzeranforderungen und Quellen und gibt bei
fehlender Quelle `NEEDS_DECISION` statt eines Freibriefs für formal gefüllte
Felder.

Jede produktive Übergabe (`map`, `graph`, `materialize`, `implement`) nennt am
Ende den passenden nächsten Aufruf, z. B. nach `materialize`:

```bash
ki-dev -f materialize step BEAD_ID materialize.review
```

Alle vier Prüfgegenstände geben `PASS` oder die stärkste Befundklasse aus, nennen
Befunde mit Quellen-/Anforderungsbezug, konkreter Abweichung und betroffenem
Abschnitt und starten selbst weder Prüfwerkzeuge noch Folgemodelle. Ein
Review hat keine automatische Autorität gegenüber dem vorangegangenen Agenten
und schließt nichts automatisch; `PASS` gilt nur für den vom Menschen
zugeordneten Arbeitsstand/Scope, was `handoff` nicht technisch prüft, und
unentscheidbare Konflikte entscheidet der Mensch. Es gibt keine erzwungene
Review-Kette: Nach jedem produktiven Schritt folgt ein Review, nach einer
substanziellen Korrektur nur eine erneute Prüfung der betroffenen Kriterien.

### Metadatenbeispiel

```json
{"handoff": {"source_refs": ["docs/design/protokoll-a.md#L12-L40", "bd:projekt-karte"]}}
```

Setzen mit z. B.
`bd update projekt-42 --metadata '{"handoff":{"source_refs":["docs/design/protokoll-a.md#L12-L40","bd:projekt-karte"]}}'`.
`source_refs` ist eine nichtleere Liste nichtleerer Strings: relative
Dateipfade mit Fundstelle oder `bd:`-IDs. Sie werden nur als Text
weitergegeben, nicht aufgelöst und nicht auf Vollständigkeit geprüft.

## Fehlende Felder und Fehlerfälle

| Exit | Bedeutung |
| --- | --- |
| 0 | Übergabe auf stdout (nach dem Vorlauf mit Prüfbericht) oder, am Ende des Ablaufs, die Nachricht der letzten Kante |
| 2 | Aufruf falsch (unbekannter Ablauf oder Zustand, Zustand ohne Übergabe, `ZUSTAND=DATEI` ungültig, doppelt oder für einen Zustand ohne Antwort, stdin mehrfach, `--preflight-args`/`--preflight-skip` ohne Vorlauf oder ungültig, Optionen der früheren Form), ungültige Antwort (Vertrag der Ops, Ereignis ohne Kante, Wächter verletzt), fehlende deklarierte Eingabe (mit Name und Herkunft), ungültige `feedback_max_chars` oder `base_max_chars`, zu lange Basisübergabe, Bead formal unvollständig, ungültige Vorlauf-Konfiguration; Sitzungsform: fehlendes `map`, anderer Anbieter als `codex` oder `claude`, ungültige Sitzungs-ID; stderr nennt z. B. die Feldpfade `metadata.handoff.source_refs` oder `metadata.handoff.source_refs[1]` |
| 1 | `bd` nicht lesbar (nicht gefunden — stderr nennt dann `Bead BEAD_ID nicht gefunden` —, Fehler, Zeitüberschreitung, unerwartete Antwort), fehlgeschlagener Vorlauf (Reparaturnachricht an den Umsetzer auf stdout), nicht lesbare Antwortdatei (Datei/stdin, kein UTF-8), nicht lesbare `pyproject.toml` (Basisgrenze). Sitzungsform: Sitzung fehlt, ist mehrdeutig oder besteht die Dialogprüfung nicht; Quellen-Datei abweichend; Quellen-Bead mehrdeutig oder nicht bestätigt; `bd`-Fehler. Kurze, bereinigte Ursache auf stderr |

Ist der Aufruf selbst falsch (Ablauf, Zustand, Antwortangaben, Optionen),
wird `bd` nicht gestartet. Beheben: fehlende Felder im Bead ergänzen
(`bd update …`) bzw. die genannte Antwort mitgeben und erneut aufrufen.

## Ablauf in wenigen Minuten

1. `ki-dev -f map step KARTE map`: Übergabe ausgeben, in einer neuen
   Agentensitzung einfügen. Danach mit `map.review` die Karte in einer
   frischen Sitzung prüfen lassen.
2. `ki-dev -f graph step KARTE graph`: der Agent legt dünne Vorgänge an;
   jeden mit `ki-dev -f graph step VORGANG graph.review` prüfen lassen.
3. `ki-dev -f materialize step VORGANG materialize`: je dünnem Vorgang eine
   Sitzung; danach `materialize.review`.
4. `ki-dev -f implement_review step VORGANG implement`: Übergabe in eine
   Umsetzungssitzung.
5. `ki-dev -f implement_review step VORGANG implement implement=done.json`:
   die Umsetzung ist erledigt, der
   [deterministische Vorlauf](#deterministischer-vorlauf-vor-der-review-übergabe)
   läuft; erst bei dessen Erfolg entsteht die Übergabe für eine **frische,
   getrennte** Review-Sitzung. Der Review-Text verlangt ein eigenes Urteil
   anhand von `description`, `design`, `acceptance_criteria`, Diff und
   Prüfbericht. Die Antwort gibst du mit `implement.review=antwort.json`
   weiter; das Schließen des Beads entscheidest du.

Der Block „Hinweis für den Menschen“ am Ende jeder Übergabe nennt die
Folgeschritte des aktuellen Zustands aus dem
[Ablauf](#zustände-und-befundklassen); du trägst sie weiter.

## Zustände und Befundklassen

Jeder Ablauf ist eine Phase mit eigenen Zuständen aus dem Muster
[`flow/patterns/review.toml`](../src/ki_dev/flow/patterns/review.toml);
der Katalog liefert auch Vokabular, Befundklassen und die Zustände
`source` und `finished`. Abläufe sind Daten, kein Code. Das gemeinsame
Ablaufformat
(`src/ki_dev/flow/model.py`) prüft ihn per JSON Schema und mit benannten
Regeln: Jedes Ziel existiert, jedes Review kennt die Pflichtereignisse seiner
Art (`[required]` im Katalog), und von jedem Zustand führt ein Weg zu
`finished`. PASS führt nach `finished`; der Hinweis nennt den nächsten
Ablauf (`ki-dev -f graph step BEAD graph`).

| Zustand | Wer | Bedeutung |
| --- | --- | --- |
| `P` (`map`, `graph`, `materialize`, `implement`) | Schreibagent | erstellt oder **ergänzt** das Ergebnis |
| `P.review` | getrennter Review-Agent | Urteil mit Befundklassen |
| `P.correction` | Schreibagent, bisherige Sitzung | behebt Befunde der Klasse `fix` |
| `P.decision` | Mensch | `accept`, `correct` oder `source` |
| `source` | Mensch, Planungssitzung | offene Frage braucht eine neue Quelle |
| `finished` | Mensch | Schließen entscheidest du |

Review-Befunde tragen eine Klasse. Das Urteil folgt der stärksten Klasse
(`decision` > `source` > `fix`), ohne Befund `PASS`:

| Klasse | Urteil | Weiter mit |
| --- | --- | --- |
| `fix` | `CHANGES` | `P.correction`, danach `P.correction=done.json` |
| `source` | `NEEDS_DECISION` | Planungssitzung, Import, **bestehende** Karte ergänzen |
| `decision` | `NEEDS_DECISION` | `P.decision` |

Beispiel: Ein Graph-Review findet eine offene Frage.

```text
graph.review --source--> source          Planungssitzung mit dem Menschen
source --imported--> finished            ki-dev step map --agent claude --session S2 --title T
map (neuer Lauf)                         Agent ergänzt die bestehende Karte K
map --done--> map.review                 ki-dev -f map step K map.review
map.review --PASS--> finished            ki-dev -f graph step K graph
graph (neuer Lauf)                       Agent ergänzt die bestehenden Vorgänge
```

Eine Entscheidung ohne erneutes Review (`accept`) hält der Mensch im Bead
fest, etwa als `metadata.source_map.review = "ACCEPTED_BY_DECISION"` samt
Begründung; sie ist kein PASS. Beads dürfen ihren Zustand als
`metadata.step.zustand` (ID aus der Tabelle) tragen; `ki-dev` liest ihn in
dieser Etappe noch nicht.

## Sitzung als Quelle (`step map`)

```bash
ki-dev step map --agent codex --session SESSION_ID --title 'Docker-Schicht'
ki-dev step map --agent claude --session SESSION_ID --title 'bd-Hook'
```

Erschließt eine lokale Codex- oder Claude-Sitzung als Quelle für den Schritt
`map`. Beide Anbieter liefern denselben geprüften Transkripttyp. Das
Positionswort `map` ist Teil des Aufrufs und das einzige erlaubte
Positionsargument. `--agent`, `--session` und `--title` sind erforderlich; `--agent` bezeichnet den
Anbieter der **Quellsitzung** (`codex` oder `claude`), nicht den späteren
Kartierungsagenten. Es gibt kein Dateipfadargument und keine automatische Wahl
der letzten Sitzung. Die Form lässt sich nicht mit einer `BEAD_ID`, einem
anderen Positionsargument mischen; auch `--agent`/`--session`
ohne `map` wird abgelehnt (Exit 2, vor jeder Schreibwirkung).
`--title` ist nichtleerer Text bis 120 Zeichen und muss Buchstaben oder
Ziffern enthalten; daraus entsteht der Dateislug. Der Titel wird nie aus
Gesprächsinhalten abgeleitet; fehlt er, endet der Aufruf mit Exit 2.

**Sitzungsordner:** Codex: `KI_DEV_CODEX_SESSIONS_DIR` (ausdrücklicher
Ordner), sonst `CODEX_HOME/sessions`, sonst `~/.codex/sessions`. Claude:
`KI_DEV_CLAUDE_SESSIONS_DIR` (ausdrückliche Projektwurzel), sonst
`~/.claude/projects`; gesucht wird `PROJEKT/SESSION_ID.jsonl`. Ein gesetzter, aber leerer
Wert ist ein Fehler (mit Klartextmeldung, ohne Traceback), ebenso ein nicht
lesbarer Ordner oder eine nicht lesbare Sitzungsdatei. Die ID darf nur aus Buchstaben, Ziffern, `_` und `-`
bestehen und muss genau eine Sitzung treffen.

**Dialogprüfung:** Die frühere strenge Annahme eines sauberen Wechsels mit
gleicher Anzahl (cg1) ist abgelöst. Wiederholte Rollen, Nachträge und eine
offene letzte Eingabe sind gültig und bleiben vollständig erhalten; bei Codex
zählen T1 (nur eine Rolle), T2 (ungleiche Anzahl) und T4 (Rollenbrüche) nur
als Diagnose, bei Claude zusätzlich offene Eingaben. Codex verlangt ein
eindeutiges, endliches `ordinal` und bei sauberem Wechsel passende
`turn_id`-Paare. Claude übernimmt menschliche Eingaben und `end_turn`-Text;
technische Aufgabenmeldungen werden nur bei belegter Herkunft (`origin.kind`,
`turnOrigin`, `promptSource`) ausgelassen und gezählt, Slash-Befehlszeilen
nur ohne jede Herkunftsangabe; menschliche Zitate bleiben, auch mit führendem
Tag. Jede `sessionId` muss der angeforderten Sitzung entsprechen. Ungültiges JSON (auch eine abgeschnittene letzte Zeile), unbekannte
Phasen oder Herkunft, ungültige Zeitstempel, leere Texte oder ein Transkript
ohne Beiträge brechen mit Exit 1 ab; es entsteht weder Datei noch Bead. Die Meldung nennt nur
Prüfcode, Zeile und Feldpfad (höchstens 10 Fälle je Prüfung), nie
Gesprächsinhalt. Sie weist auf eine Plausibilitäts-/Formatabweichung hin, nicht
auf einen bewiesenen CLI-Versionswechsel. Es gibt kein `--force`. Für neue
Formate bleibt ein getrenntes, nicht veröffentlichtes Entwicklungswerkzeug;
seine Ausgabe gehört nicht ungefiltert in einen Agentenkontext.

**Schreibwirkungen (lokal):**

1. Das normalisierte Transkript wird als datierter
   [Snapshot](session.de.md#datierte-jsonl-snapshots) unter
   `.local/var/transcripts/YYMMDDTHH_titel_sid8.jsonl` abgelegt (derselbe
   Speicher wie `ki-dev session transcript`). Ein identischer Stand wird
   wiederverwendet, auch unter anderem Titel; abweichender Inhalt am selben
   Schlüssel ist ein Fehler. Eine Sitzung ohne belegten Beginn
   (`started_at`) endet mit Exit 1 vor jedem Bead.
2. Ein Quellen-Bead wird über `bd list` gesucht (Schlüssel
   `metadata.handoff.source_key` aus Anbieter, Sitzung, Byte-Hash und
   Parserversion) und sonst per `bd create` angelegt. `metadata.handoff.source_refs`
   verweist auf den Snapshot; die Beschreibung nennt Quelle und Stand, aber
   keinen Gesprächsinhalt. Mehrere Treffer brechen ab. Ein früher angelegter
   Quellen-Bead, der noch auf die alte Ablage
   `.local/handoff/AGENT/SESSION_ID/DIGEST-PARSERVERSION.jsonl` verweist,
   bleibt gültig, solange diese Datei vorhanden ist; sie wird weder
   verschoben noch umgeschrieben.
3. Erst danach gibt der Befehl die bestehende `map`-Übergabe mit
   Quellenreferenz und Hinweis zum abschnittsweisen Lesen aus. Das Transkript
   erscheint weder auf stdout noch in Beads.

Geänderte Sitzungsbytes ergeben einen neuen Stand und einen neuen Bead; frühere
Quellen und Karten bleiben unberührt. Schlägt `bd` fehl (Exit 1), darf das
gültige Artefakt bleiben; der Wiederholungsaufruf verwendet es erneut. Nutze den
Aufruf seriell: Parallelimporte sind nicht abgesichert.

**Manuelle Fortsetzung:** Übergabe kopieren und in einer frischen
Kartierungssitzung einfügen, danach getrennt prüfen lassen. Die Karte geht mit
Wiederholungen, Präzisierungen und Widersprüchen inhaltlich um; der Parser
bereinigt nichts. Der Befehl startet keinen Agenten und legt keine Karte an,
beansprucht oder schließt nichts.

## Deterministischer Vorlauf vor der Review-Übergabe

Build darf gezielt entwickeln und testen; das ist kein pauschales Test-,
Typprüfer- oder Werkzeugverbot. Ein deterministischer Vorlauf entlastet die
Bau-Sitzung nur von mechanischem Linting/Formatieren und den abschließenden
Prüfungen. Die Review-Sitzung selbst startet keine Formatter, Linter,
Typprüfer oder Tests und keine Folgemodelle; sie liest Dateien, Diff,
Anforderungen und den Prüfbericht und beurteilt anhand dessen auch Testqualität und Abdeckung.

Erreicht ein Aufruf in `implement_review` den Zustand `implement.preflight`
(nach `implement=…` oder `implement.correction=…`), führt step diesen
Vorlauf selbst aus, **bevor** die nächste Übergabe entsteht — das erweitert
den sonst rein lesenden Vertrag ausdrücklich für diesen Aufruf. Ablauf: konfigurierte
Korrekturen seriell (Abbruch bei der ersten fehlgeschlagenen; restliche
Korrekturen **und** alle Prüfungen gelten dann als ausgelassen und erscheinen
so im Bericht; bereits erfolgte Änderungen bleiben unverändert stehen, es gibt
keinen automatischen Rückbau), danach — nur wenn alle Korrekturen erfolgreich
waren — alle konfigurierten Prüfungen. Die Zuordnung der Ergebnisse zum
Arbeitsstand liegt beim Menschen; der Vorlauf erzeugt weder Fingerprints noch
Git-Snapshots und erkennt keine Änderungen zwischen Prüfungen. Er braucht
dafür auch kein Git-Repository.

**Konfiguration:** projektlokale `pyproject.toml` (Orte aller
ki-dev-Konfigurationen listet `ki-dev config`), Tabelle
`tool.ki-dev.handoff.preflight`, Listen `corrections` (darf leer sein) und
`checks` (mindestens ein Eintrag), je Eintrag `name` (eindeutig über beide
Listen), nichtleere `argv`-Liste nichtleerer Zeichenketten ohne NUL/CR/LF,
positiver endlicher `timeout_s`. Die Länge von `argv` ist nicht begrenzt;
lange Befehle kürzt nur die Ausgabe (siehe **Ausgabe**).
Keine Autodetektion, keine automatische Installation, keine impliziten
Fixes; fehlt die Tabelle oder `checks`, enthält `argv` NUL/CR/LF, oder ist
die Datei kein gültiges UTF-8/TOML, ist das ein Konfigurationsfehler (Exit 2, vor jedem
Korrekturbefehl erkannt, unabhängig davon, welcher Eintrag betroffen ist). Prozessaufrufe laufen
ohne Shell im aktuellen Arbeitsverzeichnis (Projektwurzel) mit geerbter
Umgebung. Enthält das erste `argv`-Element einen Pfadtrenner, gilt es relativ
zur Projektwurzel (`scripts/pruefe.sh`); ein Name ohne Trenner wird im aktuellen
`PATH` gesucht, und zwar genau unter diesem Namen: `pruef_werkzeug` startet
nicht ersatzweise `pruef-werkzeug`, sondern meldet ohne exakten Treffer einen
Startfehler. Kein Commit, kein Zurücksetzen, kein Agentenstart, kein
Beads-Update.

**Ausgabe:** Während des Vorlaufs meldet stderr vor jedem gestarteten
Befehl eine Fortschrittszeile (`Vorlauf: tests läuft (Timeout 360 s) …`),
damit ein langer Lauf nicht wie ein Hänger aussieht; stdout bleibt davon
frei und lässt sich weiter umleiten (`> uebergabe.txt`).
Erfolg (Exit 0) — stdout enthält nur die Übergabe, angereichert
um einen kompakten Bericht (`PRUEFBERICHT vorlauf-start=…`, je Befehl
Status, gekürzter Ausgabe und `argv` mit eindeutigem Quoting mehrteiliger
Argumente). `name` und die Prozessausgabe werden von Steuerzeichen/ANSI-Codes
bereinigt und begrenzt. `argv` wird nicht maskiert; über 100 Zeichen wird sie
einzeilig mit sichtbarer Restlänge gekürzt (`pytest --desel…(+87)…test_y`).
Vollständig steht sie im Prüfartefakt, auf das genau eine Zeile verweist
(`Vollständig: .local/handoff/preflight/<Zeitstempel>.json`) — bei Erfolg in
der Übergabe, bei Exit 1 im Reparaturbefund. Eine abschließende Hinweiszeile nennt, dass PASS nur bei
unverändertem Arbeitsbaum und Bead gilt und ki-dev das beim Eingang der Antwort
prüft.
Prüf- oder Ausführungsfehler (Exit 1) — stdout trägt die Reparaturnachricht; ihr Befund listet
jeden konfigurierten Befehl mit seinem tatsächlichen Status (auch bereits
erfolgreiche Korrekturen und wegen eines vorherigen Fehlschlags ausgelassene
Befehle), statt nur die fehlgeschlagenen zu zeigen; volle Prozesslogs
bleiben außen vor. Der Befund endet mit dem Ort der Konfiguration
(`Konfiguration: pyproject.toml [tool.ki-dev.handoff.preflight]`) und, wenn
eine Prüfung (nicht eine Korrektur) gescheitert ist, dem einmaligen Ausweg
(`Einmalig ergänzen: --preflight-args tests=ARGS`). Ein Prüfartefaktfehler außerhalb eines
einzelnen konfigurierten Befehls (z. B. Artefaktverzeichnis nicht schreibbar)
erscheint als eigener kurzer `Vorlauf-Ausführungsfehler` statt eines
unbehandelten Programmabbruchs; bereits gelaufene Befehle (bestanden wie
fehlgeschlagen, jeweils nicht zurückgesetzt) werden dabei mit aufgeführt,
nicht verworfen. Details stehen bei Bedarf als lokales
Prüfartefakt unter `.local/handoff/preflight/` (nicht versioniert, kein
Projektmemory).
Ungültige Konfiguration oder ein formal unvollständiger Bead (Exit 2) werden
vor dem ersten Korrekturbefehl erkannt.

Der Vorlauf gehört zum manuellen `handoff`-Ablauf. Gemeinsame Helfer dürfen
klein umstrukturiert und wiederverwendet werden, wenn Ein-/Ausgabeverträge und
Betriebsverhalten anderer Features erhalten bleiben und dies tatsächlich
Arbeit spart. Die vorhandenen Git-Helfer lesen Commit-Referenzen oder verlangen
einen sauberen Arbeitsbaum; sie ersetzen keinen Vergleich uncommitteter
Inhalte. Für diesen optionalen Schutz wird keine neue Infrastruktur gebaut.

## Grenze der Basisübergabe

Begrenzt wird nur die gerenderte Basis: Schritt/Reviewziel, Bead-ID und
-Titel, gemeinsame und Rollentexte, Epic-Hinweise, Quellenreferenzen,
Folgeschritthinweis und beim Sitzungsimport der Lesehinweis. Der gesonderte
Leitlinienblock und der Prüfbericht des Vorlaufs zählen nicht mit und bleiben
vollständig; die gesamte Ausgabe kann die Grenze daher überschreiten. Das ist
keine Tokenzusage, keine Summe von Bead-Feldern und keine zweite Definition der
Beads-Feldgrenzen.

**Grenze:** `[tool.ki-dev.handoff] base_max_chars` in `pyproject.toml`, eine
positive TOML-Ganzzahl (Standard 4000 bei fehlender Datei oder Angabe; dieses
Projekt setzt sie ausdrücklich). Gezählt werden Unicode-Zeichen des
tatsächlich ausgegebenen Basistexts einschließlich Leerzeichen,
Zeilenumbrüchen und des abschließenden Zeilenumbruchs. Gleich der Grenze ist
zulässig. `ki-dev config` zeigt den Ort.

**Übergröße:** Exit 2, stdout leer, nie gekürzt. Die Diagnose (höchstens 1000
Zeichen) nennt Ist und Grenze sowie die größten veränderlichen Anteile als
Feld- bzw. Referenzindex (`title`, `epic_context[0]`, `source_refs[1]`,
`Lesehinweis`) mit Zeichenzahl, nie deren Text; die vollständigen Quellen
bleiben im Bead. Rollen- und Gemeinsamtexte zählen mit, stehen aber nicht in
der Liste.

**Ungültige Konfiguration:** boolesche, Fließkomma-, Text- und Listenwerte,
Null und negative Zahlen, eine falsche Tabelle (`tool`, `ki-dev`,
`handoff` ist keine Tabelle) und defektes TOML oder Nicht-UTF-8 sind Exit 2;
eine nicht lesbare Datei ist Exit 1. Es gibt keinen stillen Ersatz.

**Zeitpunkt:**

- `ki-dev -f ABLAUF step …`: Die Konfiguration wird vor jeder `bd`-Anfrage
  gelesen. Geprüft wird die ausgegebene Übergabe, jede Folgenachricht
  eingeschlossen. Welche Übergabe ein beantworteter Zustand auslöst,
  zeigt erst der Ablauf: Läuft davor der Vorlauf, hat er bei Übergröße
  bereits gearbeitet (Exit 2, kein stdout, kein Rückbau).
- `map --agent … --session …`: Die Konfiguration wird vor Quellenablage und
  Beads-Anlage geprüft. Die endgültige Basis (mit Titel und Lesehinweis)
  steht erst nach der Quellenanlage fest. Ist sie zu lang, gibt es weder
  Übergabe noch Kürzung; Quelldatei und Quellen-Bead bleiben bestehen und
  werden beim erneuten Aufruf wiederverwendet. Kein Rückbau.

## Mitgelieferte Leitlinien

Alle Formen hängen die geltenden Regeltexte der Architektur-/Programmier-
und der Technikleitlinie sowie der Arbeitsregeln direkt an:
`ki-dev -f ABLAUF step` und `map --agent … --session …` die Regeln des Schritts,
`local` nur die allgemeinen Abschnitte (`common`). Der Agent muss Leitlinien weder suchen noch ihre
Phasenzuordnung selbst entscheiden; er wendet die mitgelieferten Texte an,
ohne ihre Quelldokumente erneut vollständig zu lesen.

**Quelle und Auswahl.** Die Regeln stehen in
`docs/policies/programmierleitlinie.de.yaml`,
`docs/policies/technikleitlinie.de.yaml` und
`docs/policies/arbeitsregeln.de.yaml` (in dieser Reihenfolge). Die
Arbeitsregeln ersetzen den früheren Einstiegstext von `AGENTS.md`/`CLAUDE.md`:
Beads lesen, Rollenrechte („Manueller Handoff“), Sitzungsende, Python/pytest und
Verbrauchsmessung; sie stehen vollständig in `common` und erreichen jede
Sitzung. Jede Datei
enthält `title`, `permalink`, `sections` (geordnete Liste `{id, text}`, Text
als Markdown-Literalblock `|-`), `common` sowie `stages` mit genau `map`,
`graph`, `materialize` und `implement`, jeweils `task` und `review` als
ID-Listen. Ausgewählt wird fest, ohne Modell oder Themenklassifikation:
`common` + `stages[ZIEL].task`; bei einer prüfenden Übergabe (Review-Zustand)
zusätzlich `stages[ZIEL].review`. ZIEL ist die Phase des Ablaufs (sein
Start, z. B. `implement` für `implement_review`). Reihenfolge wie in `sections`, jede ID je
Datei einmal, auch wenn sie mehrfach zugeordnet ist. Die Zuordnung verringert
die Geltung nicht: Allgemeine Regeln stehen in `common` und erreichen jeden
Schritt; `stages` tragen nur die Phasenschwerpunkte (Architektur in Planung
und Materialisierung für graph/materialize, Programmierung in Umsetzung und
Review sowie Docstrings für build).

**Ausgabe.** Der Block `LEITLINIEN (mitgeliefert; …)` steht nach allen
Teilen der Basisübergabe: nach dem Hinweis für den Menschen, beim map-Import
nach dem Lesehinweis, bei der Build-Review nach dem `PRUEFBERICHT`. Jeder
Abschnitt beginnt mit `--- YAML-DATEI#ABSCHNITTS-ID ---`; Zeilenumbrüche,
Listen und Codeblöcke bleiben erhalten. Der Block ist ein gesondert
ausgewiesener Kontextblock wie der Prüfbericht: Er wird nie gekürzt und zählt
nicht zu einer Längengrenze der Basisübergabe. Die gesamte Ausgabe kann
deshalb deutlich länger sein als die Basisübergabe. Das ist keine
Tokenersparnis und keine Verbrauchszusage. Folgenachrichten in eine
bestehende Sitzung hängen keine Leitlinien erneut an; die Sitzungen haben
sie bereits erhalten.

**Fehler.** Die Quellen werden relativ zum aktuellen Verzeichnis geladen,
ohne Ersatzquelle, und vor Vorlauf, Quellenablage und Beads-Anlage geprüft.
Fehlende oder unlesbare Datei: Exit 1. Kein UTF-8, ungültiges YAML oder
Vertragsverletzung (Typ, leerer Text, fehlendes oder unbekanntes Feld,
doppelte oder unbekannte Abschnitts-ID): Exit 2. Diagnosen nennen Datei,
Feldpfad und ggf. Zeile, nie Regeltexte.

**Pflegeweg.** Regeln nur in den YAML-Dateien ändern, dann
`./.venv/bin/python scripts/render-guidelines.py` ausführen. Das Skript
erzeugt daraus vollständig `docs/programmierleitlinie.de.md`,
`docs/technikleitlinie.de.md` und `docs/arbeitsregeln.de.md` (Frontmatter, Permalink, Überschriften und damit
Anker bleiben erhalten; eine Kopfzeile kennzeichnet die Seite als generiert).
`--check` schreibt nichts und endet bei Abweichung mit Exit 1. `handoff`
selbst erzeugt keine Dokumentationsdateien.

**Arbeit ohne `handoff`.** `AGENTS.md` und `CLAUDE.md` sind leer. Sitzungen
ohne Bead beginnen mit `ki-dev step local`; wer ganz ohne Übergabe arbeitet,
liest die erzeugten Seiten `docs/programmierleitlinie.de.md`,
`docs/technikleitlinie.de.md` und `docs/arbeitsregeln.de.md`; deren Inhalt ist
derselbe.

## `AGENTS.md`/`CLAUDE.md` leer und lokal geschützt

Die Einstiegstexte stehen nur noch in `docs/policies/*.de.yaml`; die beiden
Dateien sind im Repository leer. Git transportiert keinen Schreibschutz (kein
`0444` im Klon). Nach jedem frischen Klon einmal (das Skript braucht nur die
Standardbibliothek; vor dem Anlegen der Projekt-venv genügt ein beliebiges
Python 3, danach die venv wie sonst im Projekt):

```bash
./.venv/bin/python scripts/protect-agent-files.py          # chmod 0444, nur für leere Dateien
./.venv/bin/python scripts/protect-agent-files.py --check  # leer und schreibgeschützt? (Exit 1: nein)
```

Das Skript fasst nur diese zwei Dateien im Klon an, ruft keine Fremdprogramme
auf und ändert keine globale Konfiguration. Schutz aufheben:
`chmod u+w AGENTS.md CLAUDE.md`.

**Wirkung von `bd init`/`bd setup` (bd 1.3.0, geprüft in Wegwerfklons mit
eigenem `HOME`/`CODEX_HOME`, ohne `origin`, Git-Identität per Umgebung).**
Der Schreibschutz hält sie nicht auf:

- `bd setup codex` und `bd setup claude` schreiben den Beads-Block trotz `0444`
  in die Datei (Mode danach `0644`, nicht leer).
- `bd init --non-interactive --prefix P` (mit Hooks, ohne `--skip-agents`) tut
  dasselbe; die Meldung „open AGENTS.md: permission denied“ betrifft nur einen
  Teilschritt, die Datei wird dennoch neu geschrieben. Zusätzlich legt es
  `.claude/` und `.cursor/` an und committet selbst (`bd init: initialize
  beads issue tracking`), darin die wieder befüllten `AGENTS.md` und
  `CLAUDE.md`.
- `bd init --non-interactive --prefix P --skip-agents` lässt beide Dateien
  unverändert (leer, `0444`) und legt sie auch nicht in seinen Commit. Es
  committet trotzdem seine Änderungen an `.gitignore`, `.beads/.gitignore` und
  `.beads/hooks/*` und setzt lokal `core.hooksPath`; das gilt auch ohne
  Schreibschutz und ist hier nicht Gegenstand.
- Nicht geprüft: Wirkung der Beads-Git-Hooks nach späteren
  Checkouts/Merges auf diese Dateien.

Verwende daher `bd init --skip-agents` und starte `bd setup codex|claude` nicht
in diesem Klon. Ist es passiert, meldet `--check` die nicht leere Datei. Ohne Commit mit
`git checkout -- AGENTS.md CLAUDE.md` zurücksetzen; hat `bd init` sie schon
committet, aus dem Stand davor mit `git checkout COMMIT_VOR_INIT -- AGENTS.md
CLAUDE.md` wiederherstellen. Danach das Skript erneut ausführen. Auch mit
wieder befülltem Beads-Block gehen die Rollenrechte der Übergabe vor
(Abschnitt „Manueller Handoff“ der Arbeitsregeln).

## Grenzen

- `handoff` übernimmt weder `notes` noch `comments` noch vollständige
  `description`/`design`-Texte in die Ausgabe. Das filtert nur die Ausgabe: Es
  ist keine technische Zugriffssperre, die Agentensitzung kann den Bead selbst
  lesen.
- Kein Verbrauchsschutz: Der Befehl überwacht weder Kontext noch Kosten noch
  Kontingente und gibt keine Sicherheitsgarantie. Wie lange und wie viel ein
  Agent arbeitet, steuerst du in der jeweiligen Sitzung.
- Keine Schrittwahl, Statusverwaltung, Claims oder Schließungen und keine
  Agentenstarts.
- Nur Codex- und Claude-Sitzungen; keine Rekonstruktion von Resume-/Fork-
  Zweigen. Der Sitzungsstart (`started_at`) stammt nur aus Sitzungsdaten
  (Codex: `session_meta` dieser Sitzung; Claude: frühester vorhandener
  Zeitstempel ihrer Beiträge), nie aus Datei- oder Exportdatum. Fehlt er, bleibt die Anzeige
  möglich; ein datumsbasierter Export scheitert sichtbar.
