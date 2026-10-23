# README-Durchlauf (Cognitive Walkthrough)

Prüft, ob das README einen Leser bis zu einer Entscheidung trägt. Kein
Software-Test: ein Mensch oder ein Agent spielt die Personas nach und
notiert je Schritt, was er sieht, welchen Eindruck er hat und was er tut
(weiterlesen, klicken, schließen).

## Maßstab

Maßstab ist die [README-Leitlinie](readme-leitlinie.de.md): Auftrag, wie ein
Mensch liest, Regeln mit Fehlbeispielen. Die README stellt ein
Entwicklungsprojekt vor, das noch nicht betrieblich nutzbar ist. Eine rote
Anforderung ist kein automatischer DX-Fehler; eine unerklärte Ausgabe, eine
Stelle mit zwei Lesarten oder ein Beispiel, das eine Aufgabe statt eines
Verfahrens zeigt, ist einer.

Ein Durchlauf zählt nur, wenn er scheitern kann. Der alte Fragenkatalog
prüfte Inhalt; ein Agent beantwortete ihn auch aus einer README, die für
Menschen scheiterte (3,5 von 4, siehe unten).

## Personas

| Persona | Zeit | Ziel | Entscheidung |
| --- | --- | --- | --- |
| Tech-Lead sichtet eine Bewerbung | 60 s | Problemverständnis, technische Umsetzung und den Beitrag der Person hinter ki-dev für ein Team erkennen | Gespräch sinnvoll oder nicht, schon nach dem ersten Bildschirm |
| Entwickler erkundet das Projekt | 5 min | Ansatz, Entwicklungsstand und nächsten Erkundungsschritt verstehen | erkunden, verfolgen oder verlassen; Betrieb gesondert beurteilen |
| KI-Agent im Repo | ein Lesedurchgang | Beispiel, Ist/Ziel und zuständige Quellen verstehen | richtige Datei öffnen |
| Prüfer verfolgt einen Nachweis | 10 min | Aussage → Test → Aussagegrenze nachvollziehen | Nachweis trägt die konkrete Behauptung oder nicht |

## Schritte

1. Erster Bildschirm (bis zum Inhaltsverzeichnis): Der Leser hält an und
   schreibt in drei Sätzen, was ki-dev ist, woraus es besteht und wie weit
   es ist. Der Tech-Lead schreibt im selben Halt, was die Person hinter
   ki-dev seinem Team beitragen könnte, je Punkt mit Zeile aus Kopf oder
   Inhaltsverzeichnis, Vermutetes gekennzeichnet, und ob er nach diesem
   Bildschirm ein Gespräch anbieten würde. Die Antworten bleiben stehen;
   wo das Weiterlesen sie widerlegt oder erst ergänzt, ist ein Befund
   gegen den Kopf.
2. Erstes Beispiel: Zeigt es ein Verfahren oder eine einzelne Aufgabe? Kann
   er jedem Schritt seine Ebene zuordnen, ohne zu raten?
3. Begriffe und Lesarten: Welcher Begriff steht für zwei Dinge? Welche
   Stelle, auch in einer Skizze, lässt zwei Lesarten zu (mit beiden
   Lesarten)? Welche Stelle bewertet ohne Beleg oder grenzt sich gegen eine
   Alternative ab, die der Leser nicht erwartet hatte (Zeile, Wortlaut;
   [Leitlinie Regel 15](readme-leitlinie.de.md#regeln-mit-fehlbeispiel))?
4. Fährte und Modell: Hielt jede Überschrift und jeder Link, was er
   versprach? Wo musste er springen oder fand die Antwort erst später? Baut
   jeder Abschnitt auf dem Modell aus dem Beispiel auf?
5. Ausgabe und Tests: Versteht er vor dem Nachweis, was dieser zeigen soll?
   Kann er danach zwischen beobachtetem Verhalten, Lücke und Ziel unterscheiden?
6. Nächste Handlung: Sind Voraussetzungen und Einrichtung erreichbar, wenn
   er selbst erkunden möchte? Hilft `step`, Agenteneingaben und Übergänge zu verstehen?
7. Lesepfad des Minimalbeispiels: Kann er nur mit der README sagen, was er
   zum Ausführen braucht, welche Befehle er in welcher Reihenfolge eingibt
   und woran er am Ende erkennt, dass es geklappt hat? Weiß er, bevor er
   eine Voraussetzung vermisst, welche Alternative es gibt (Demo ohne
   Modellzugang)?
8. Abbruch: Wo endet das Interesse oder das Verständnis, und warum?
9. Prüfer zusätzlich: Eine Ist-Aussage zum Beispiel und eine zum Entwicklungsstand
   bis zum Testcode verfolgen. Prüft der Test genau das Behauptete?

## Auswertung

Kein Punktestand und kein „bestanden“. Entscheidend ist die Erklärung in
eigenen Worten: Problem → Beispiel → Entwicklungsstand → sinnvoller nächster
Schritt, gemessen an den drei Sätzen nach dem ersten Bildschirm. Fundstellen
begründen das Urteil; bloße Auffindbarkeit genügt nicht. Ungeklärte Fragen,
Stellen mit zwei Lesarten und der tatsächliche Abbruchpunkt bleiben im
Bericht stehen.

Ein Agentenbericht ist ein Hinweis, nie die Abnahme; abgenommen wird von
einem Menschen. Wer Befunde umsetzt, prüft zuerst die Gliederung gegen die
Leitlinie und flickt nicht einzeln.

### Wann ein Durchlauf scheitert

Geprüft wird die README-Vorstellung gegen die Grundanforderung: Ein
Tech-Team, das eine Anstellung der Person hinter ki-dev erwägt, erkennt im
ersten Bildschirm, was diese Person einbringen kann, ohne Marketing.

- **Wer:** je Persona ein Agent mit der Übergabe aus
  `scripts/readme-walkthrough prepare`, ohne Projektkenntnis; abgenommen
  wird von einem Menschen.
- **Beitrag (Tech-Lead):** Nach Kopf und Inhaltsverzeichnis, im selben
  Halt wie die drei Sätze: Was könnte die Person hinter ki-dev deinem Team
  beitragen, je Punkt mit Zeile aus diesem Bereich, Vermutetes
  gekennzeichnet? Gescheitert ist die Vorstellung, wenn die Antwort leer
  bleibt oder nur aus Vermutungen besteht. Was der Leser erst danach
  findet, repariert den ersten Eindruck nicht; es ist ein Befund gegen den
  Kopf.
- **Bewertung und Abgrenzung (alle Personas, Frage 8):** Jede zitierte
  Stelle im gelesenen Teil, die ohne Beleg bewertet oder sich gegen eine
  Alternative abgrenzt, die der Leser nicht erwartet hatte, ist ein Befund.
  Auch ein früher als zulässig behandelter Kontrast wird erneut auf seine
  Verständlichkeit geprüft; „keine einzelne Aufgabe“ erklärt das Verfahren
  nicht ([Leitlinie](readme-leitlinie.de.md#regeln-mit-fehlbeispiel)).
- **Lesepfad des Minimalbeispiels (alle Personas, Frage 9):** Gescheitert,
  wenn eine Voraussetzung erst nach dem ersten Befehl oder nur hinter einem
  Link steht, ein Schritt eine zweite Datei braucht, eine Ausgabe (auch ein
  Halt) unerklärt bleibt oder das Ergebnis nicht ohne Raten erkennbar ist.
- **Wie bisher:** Modell nach dem ersten Bildschirm gegen den
  [Auftrag](readme-leitlinie.de.md#auftrag), Stellen mit zwei Lesarten,
  Fährten, die nicht hielten, Abbruchpunkt.

Beantwortet der Agenten-Durchlauf die Beitragsfrage nicht trennscharf,
prüft ein Mensch mit einem First-Impression-Test (5-Second-Test): nur Kopf
und Inhaltsverzeichnis, dieselbe Beitragsfrage, dieselbe Trennung von
README-Stand und Fragen.

DE und EN auf dieselbe Leserführung, Beispielbedeutung und Ist-/Zieltrennung
prüfen. Der Prüfer unterscheidet Link-Erreichbarkeit von inhaltlicher Beweiskraft.

## Durchlauf mit einem Web-Agenten

`./scripts/readme-walkthrough prepare` bereitet aus dem Arbeitsbaum je Persona
einen Ordner mit der vollständigen README vor und gibt auf stdout nur dessen Pfad aus.
Das Zeitbudget begrenzt den Lesedurchlauf; feste Zeilenschnitte würden Beispiele
und Erklärungen mitten im Zusammenhang abschneiden. Auf stderr zeigt er
zuerst, welche Konfigurationspfade geprüft wurden und welcher gilt. Den
Arbeitsbaum bis zum fertigen Bericht nicht ändern.

Die Konfiguration ist eine Datei mit dem Eintrag `ausgabe = <ordner>`. Die
Suchpfade nennt das Script selbst; `./scripts/readme-walkthrough config`
zeigt sie mit Status und Ergebnis, ohne etwas anzulegen. Der erste vorhandene
Pfad gilt. Fehlt die Datei, landet der Lauf unter `.local/var/readme-walkthrough/`
im Repo. Ist die Datei vorhanden, aber ohne oder mit doppeltem Eintrag, bricht
der Befehl mit Fehler ab, ohne auf den Standard zurückzufallen.

Der Lauf landet unter `<ordner>/<head>-<zeit>/`; `~/` im Eintrag wird aufgelöst.

Einen älteren README-Stand mit dem heutigen Verfahren prüfen:
`./scripts/readme-walkthrough prepare --readme REV` nimmt README.md, die
verlinkten Dateien und `root.txt` aus `REV` (`git show`, `git ls-tree`),
Übergabe und Fragen aus dem Arbeitsbaum. Der Ordner nennt beide Stände:
`<head>-readme-<rev>-<zeit>/`. So entsteht eine Basislinie, an der sich
zeigt, ob das Verfahren scheitern kann.

Je Persona einen neuen temporären Chat öffnen; Memory, eigene Anweisungen
und Websuche ausschalten. Web-Chats laden nur Dateien, keine Ordner. Der
Persona-Ordner ist deshalb flach: Die Dateien des Ordners hochladen, nicht
den Ordner; beim Prüfer liegen verlinkte Unterordner als `ordner__datei`
vor, `dateien.txt` nennt die Zuordnung. Danach `uebergabe.txt` als Nachricht einfügen.
Die Antworten an den README-Bearbeiter geben. Dieser erhält die Vorbilder;
der Web-Agent erhält sie nie.

## Basislinie `02c0078`

Der README-Kopf aus `02c0078`, geprüft mit dem Verfahren oben
(`ki-dev-ablauf-i0ro`): `./scripts/readme-walkthrough prepare --readme
02c0078`, Verfahrensstand `5cbcccd`, Ordner
`5cbcccd-readme-02c0078-261021T1351`. Je Persona las ein Claude-Code-
Unteragent ohne Projektkenntnis nur die Dateien seines Ordners; die
Berichte liegen lokal unter `.local/var/readme-walkthrough/` (nicht
versioniert).

| Persona | Abbruch | Beitrag nach dem ersten Bildschirm | Frage 8 (Auswahl) |
| --- | --- | --- | --- |
| Tech-Lead | Z. 449 | 8 Punkte, 6 als vermutet gekennzeichnet; belegt: Entwurfsentscheidung „Code steuert“ (Z. 5–7), offene Lücken (Z. 12–37); Gespräch: ja | „sind echt“ (Z. 266), „kein Aufseher-Modell“ (Z. 388), „ein Verfahren, keine einzelne Aufgabe“ (Z. 57) |
| Entwickler | Z. 392 | nicht gefragt | „passt zu jedem Vorgang“ (Z. 146), „sind echt“ (Z. 266), „Wer mehrere Agenten einsetzt, reicht … von Hand weiter“ ohne Beleg (Z. 381), „kein Aufseher-Modell“, „ein Verfahren, keine einzelne Aufgabe“ |
| Prüfer | Z. 598 | nicht gefragt | „passt zu jedem Vorgang“, „sind echt“, „Es wechselt nur `executor`“ (Z. 193), „kein Aufseher-Modell“, „setzen nur Parameter darauf“ (Z. 459) |

Was sie zeigt:

- Befunde aus `ki-dev-ablauf-qaa0`: Alle drei finden Problem, Zweck und
  Zielgruppe erst unter „Warum“ (Z. 376–390), als Befund gegen den Kopf.
  Stand-Punkte im Kopf brauchen Begriffe, die erst später kommen
  („Was ist Kontingent?“, Entwickler). Der Beitrag der Person bleibt
  überwiegend Vermutung (6 von 8 Punkten).
- Befunde aus `ki-dev-ablauf-9wtu`: „sind echt“ (alle drei), „passt zu
  jedem Vorgang“ (Entwickler, Prüfer).

Was sie nicht zeigt:

- Das Beitragskriterium scheitert an `02c0078` nicht: Zwei Punkte belegt
  der Tech-Lead aus dem Kopf, er würde ein Gespräch anbieten.
- „Nicht nur Code“ nennt keine Persona als Abgrenzung; der Entwickler
  liest die Überschrift als „weitere Abläufe“.
- „Gute Einstiege, je mit klarer Abnahme“ erreicht keine Persona; alle
  brechen vor „Mitmachen“ ab.

Neu aus dem Lauf: „kein Aufseher-Modell, das jede Ausgabe liest“ (alle
drei: Die Alternative kam vorher nicht vor, das Beispiel setzt selbst ein
prüfendes Modell ein) und „ein Verfahren, keine einzelne Aufgabe“
(Tech-Lead, Entwickler: nach dem Kopf nicht erwartet, ausgeführt wird
eine einzelne Aufgabe).

## Frühere Durchläufe

Die folgenden Berichte beziehen sich auf die frühere Struktur und den alten
Fragenkatalog. Sie gelten nicht als Abnahme der neu aufgebauten README.

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
