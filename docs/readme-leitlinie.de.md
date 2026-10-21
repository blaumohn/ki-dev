# README-Leitlinie: Gestaltung für Menschen

Für jeden, der `README.md` oder `README.en.md` schreibt oder prüft, Mensch
oder Agent. Entstanden aus dem Umbau vom 2026-10-17
(`ki-dev-ablauf-4lb3`). Vorher und nachher vergleichen:
`git show 5a67ee1:README.md` gegen die aktuelle [README](../README.md).

## Warum diese Seite

Die README in `5d3d4c6` bekam im Agenten-Durchlauf mit
`scripts/readme-walkthrough` 3,5 von 4 Punkten
([Durchläufe](readme-walkthrough.de.md#frühere-durchläufe)), die
Korrekturrunde `5a67ee1` flickte die Befunde einzeln. Für Menschen blieb
sie ein Fehlschlag. Das Werkzeug konnte das nicht zeigen:

- Die Fragen prüften Inhalt (Was tut ki-dev? Wie hängen TOML, Profil und
  Aufruf zusammen?). Ein Agent beantwortet sie auch aus einer schlecht
  gegliederten Prosa-README, denn er hat die ganze Datei vor sich.
- Der Maßstab enthielt keine Anforderung an die Informationsarchitektur:
  kein Leser-Modell, keine Fährte, keine Begriffstrennung, kein Verfahren
  als Beispiel. Fehlte die Frage, fehlte der Befund.

Agenten lesen vollständig, linear und geduldig, finden jede Antwort
irgendwo und werten Fundstellen. Ein Mensch überfliegt, folgt der Fährte,
baut aus dem ersten Bildschirm und dem ersten Beispiel ein Modell und geht
bei der zweiten Unklarheit. Korrekte und vollständige Fakten ergeben noch
keine README. Bewertet wird der Weg eines Menschen, nicht ob Antworten
vorhanden sind. Einzelne Befunde zu flicken repariert keine falsche
Gliederung.

## Auftrag

Nach Kopf, Inhaltsverzeichnis und erstem Beispiel kann ein Besucher sagen:
was ki-dev ist (Idee), woraus es besteht (Ebenen und Orte) und wie weit
es ist (Stand). Wer für ein Team sichtet (Tech-Lead), kann schon nach Kopf
und Inhaltsverzeichnis sagen, was die Person hinter ki-dev einem Team
beitragen kann, je Punkt mit Beleg und ohne Marketing: ein Problem, das
sein Team kennt, ein Urteil im Entwurf, Umfang des Gebauten, Sorgfalt als
Arbeitsweise, Reife ohne rote Alarme, eine Grundlage zum Weiterbauen. Er
weiß, was er tun kann: ausprobieren, mitmachen, den Autor ansprechen, das
Repo beobachten. Alles Weitere verlinkt die README.
Sie ist kein Handbuch, kein Bericht, keine Testmatrix und kein Prosabuch.

## Wie ein Mensch liest

Danach wird gestaltet; jede Regel unten folgt aus einer dieser Annahmen.

- **Überfliegen:** Kopf, Inhaltsverzeichnis, Überschriften, Codeblöcke,
  Skizzen. Prosa liest er nur, wo er hängen bleibt.
- **Der Fährte folgen:** Überschriften, Linktexte und Inhaltsverzeichnis
  kündigen an, was dahinter steht. Er folgt der stärksten Fährte; findet er
  dort nicht, was sie versprach, verliert er Vertrauen. Wer für ein Team
  sichtet (Tech-Lead, Kollegin), sucht nur Signale für seine Entscheidung,
  keine Bedienung: Problem, Urteil im Entwurf, Umfang, Sorgfalt, Beleg
  einen Klick entfernt, Reife, Grundlage zum Weiterbauen.
- **Ein Modell aus dem ersten Beispiel:** Alles Spätere ordnet er dort ein.
  Trägt das erste Beispiel die Kernbegriffe nicht, baut er ein falsches.
- **Nähe ist Bedeutung:** Was nah beieinander steht, gehört zusammen; was
  darüber steht, liegt darüber; eine Zeile ohne Bezeichnung setzt die
  vorige fort.
- **Zwei Lesarten sind ein Fehler:** Bei der ersten rät er, bei der zweiten
  geht er.
- **Springen kostet:** Er liest in der Reihenfolge des Inhaltsverzeichnisses
  und will zurück, ohne zu scrollen.

## Regeln mit Fehlbeispiel

1. **Zeigen statt beschreiben.** Ein echtes Minimalbeispiel aus echten
   Dateien (Ablauf-TOML, Profil, Befehle) mit Halbsatz-Kommentaren, auch
   wenn es noch nicht betriebsbereit ist. Fehler: „ki-dev legt diese
   Steuerung in Dateien: Ablauf …, Profil …, Auftrag …“ als Prosaliste.
   Besser: `[op.review]` mit `role = "review"  # eine Rolle, kein Agent: den
   wählt das Profil`.
2. **Das Verfahren zeigen, nicht die Aufgabe.** Fehler: „Beispiel: ein Bug,
   zwei Agenten“, und der Leser hält ki-dev für einen Bugfixer. Besser:
   „Umsetzer und Reviewer als Ablauf“; der Bug ist nur der Auftrag in
   Schritt 3.
3. **Ebenen im Fluss benennen, Begriffe ab dem ersten Satz trennen.** Jeder
   Beispielschritt beginnt mit seiner Ebene oder Eingabe, verlinkt auf
   [Ebenen und Orte](../README.md#ebenen-und-orte) („**Ebene Ablauf.**“,
   „**Eingabe Profil.**“). Ein Wort, ein Begriff: Ebene (wer wen steuert) ≠
   Ort (wo es liegt: Paket, Gerüst) ≠ Eingabe (Profil, Auftrag), Op (wirkt
   nach außen) ≠ Aktion (ändert Laufdaten), Rolle (im Ablauf) ≠ Executor
   (Name im Profil) ≠ Adapter (Transport-Code), Ablauf ≠ Ablaufkette,
   Lauf ≠ Bead-Graph-Durchgang.
4. **Ein Modell vertiefen, nicht neu ansetzen.** Die Abschnitte folgen dem
   Modell aus dem Beispiel: Kopf (Problem, Idee, Reife) → Beispiel → was
   im Lauf passiert → Stand und bekannte Lücken → Warum → Ebenen und Orte
   → weitere Abläufe → Roadmap → Mitmachen → Lizenz. Jeder
   verweist auf den Beispielschritt zurück, den er vertieft. Fehler: ein
   Abschnitt, für den der Leser ein neues Bild des Projekts bauen muss.
5. **Fährte legen.** Überschrift und Linktext sagen, was dort steht:
   „Einrichten, ohne Agenten ausprobieren“, „Was im Lauf passiert“.
   Aktive Links ab dem ersten Satz führen zu der Stelle, die den Begriff
   zeigt („[Ablauf aus TOML](../README.md#1-ablauf-mitgeliefert)“). Stark
   verlinken: jeder Begriff beim ersten Auftreten im Abschnitt, jede
   genannte Datei, jedes Skizzenelement mit Fundstelle; die Schritte
   verlinken auf ihre Ebene, die Skizze zurück auf die Schritte. Fehler:
   Kopf ohne Links, Motivation erst ab Zeile 462 (Durchlauf `5d3d4c6`).
   Fehler: „Nicht nur Code“ als Überschrift (Regel 15).
6. **Linear navigieren.** Inhaltsverzeichnis in Lesereihenfolge mit
   Unterlinks auf die Beispielschritte; `↑ Inhalt` am Ende jedes Abschnitts
   und Unterabschnitts.
7. **Skizzieren, was skizzierbar ist, und jedes Element eindeutig.**
   - Erst das Kriterium, dann die Kästen: Jede Dimension steht in einem
     Satz vor der Skizze (Ebene = wer wen steuert, Ort = wo es liegt).
     Kasten = Ebene, Zeilenbezeichnung = Ort, beschrifteter Pfeil =
     Beziehung, Abstand zwischen Ebenen. Eine geplante Ebene steht als
     ◇-Zeile darüber, Eingaben als Zeile darunter, nie als Kasten im
     Stapel.
   - `<pre>` mit `<a href>`, damit Elemente verlinkt sind; höchstens 72
     Zeichen sichtbar, Kastenkanten in einer Spalte, DE und EN gleich
     gebaut (`tests/test_readme_skizze.py`).
   - Fehler: Kästen nach Beispielschritten statt nach einem Kriterium
     (`e322b79`). Das Profil teilt als Kasten mit ↑-Pfeil die Skizze, kein
     Pfeil führt vom Paket zum Gerüst, `Muster` und `Ops` stehen im Kasten
     Gerüst statt auf ihrer Ebene, Ops, Übergabe und Grenzen in zwei
     Kästen.
   - Fehler: `│ Muster und gemeinsame Ops │` ohne Bezeichnung unter
     `Adapter … mock`: Fortsetzung oder eigener Teil? Fehler: `Arbeitsgraph
     Beads: …` direkt über dem Paket-Kasten: Ist Beads ein Teil davon oder
     eine Ebene darüber?
   - Mermaid nur, wo GitHub es lesbar setzt: ein Zustandspfad ja, ein
     Ebenenbild nein (gerendert unleserlich, `7f37f10`).
8. **Gegen den Code prüfen, nicht gegen das Gedächtnis.** Fehler: die Spur
   `controller_step ─controller_task→ worker_step` war ausgedacht, echt ist
   `worker_step_prepare`. Echte Artefakte zeigen und ganz verlinken
   ([`demo-lauf.events.jsonl`](beispiele/demo-lauf.events.jsonl)); was von
   Hand übertragen ist, so benennen.
9. **Architektur heißt Vereinbarung.** Die Skizze zeigt die vereinbarte
   Architektur
   ([Schichten und Orte](ausfuehrer-luecken.de.md#schichten-und-orte)),
   nicht den Ist-Code. Abweichungen stehen knapp mit Bead-ID in der
   Roadmap. Verschweigen ist so falsch wie den Ist-Stand als Architektur zu
   zeichnen.
10. **Stand ehrlich.** Läuft und fehlt getrennt; rote Spezifikationstests
    als solche; ein Ziel nie als Funktion; nichts Ungemessenes als
    Ersparnis. Der Kopf nennt die Reife in einem Satz mit Link auf den
    eigenen Abschnitt „Stand und bekannte Lücken“ hinter dem Beispiel.
    Dort stehen Ziel der nächsten Ausgabe, „Was schon geht“ und „Was noch
    fehlt“ in Klartext für Leser außerhalb des Projekts, je Punkt ein Link
    auf den Beleg (Doku, Test, Roadmap), nicht auf eine Stelle mit
    demselben Wortlaut. Ein Beispielschritt verweist darauf, statt die
    Lücken zu wiederholen; seine Notiz sagt nur, was ihn betrifft, in
    seinen Begriffen (Schritt 3: Profilfelder). Fehler (`02c0078`): sechs
    Stand-Punkte im Kopf, vier davon in Begriffen, die erst das Beispiel
    einführt (`implement`, Kontextmessung, Kontingentgrenze); Problem,
    Umfang und Sorgfalt fehlten. Fehler (`b30e7fa`): Der
    Kopf sagt „kein Mensch reicht jede Antwort von Hand weiter“ und
    „Adapter … laufen“, Schritt 4 sagt „Noch offen: ein abgenommener Lauf
    mit echten Agenten“. Fehler (Entwurf): „kein Zyklus ohne Mensch
    (Test)“ als Stand im Kopf, verständlich nur für Projektkenner.
11. **Für wen.** Zielgruppe ausdrücklich (knappe Token-Budgets: Code wählt
    den nächsten Schritt, kein Modell liest dafür jede Zwischenausgabe);
    Späteres als Option, nicht als Voraussetzung. Die
    ersten Zeilen sind die teuersten: Ein belegtes Problem gehört als
    erster Absatz in den Kopf, „Warum“ wiederholt es nicht; nur Motivation
    ohne Beleg gehört hinter das Beispiel. Fehler (`b30e7fa`): „für alle,
    die mit begrenzten Tokens arbeiten“, „kostet zusätzlich“ vor dem
    Beispiel, die Ersparnis ungemessen. Fehler (`02c0078`): das mit MAST
    belegte Problem erst unter „Warum“, die Regel zu grob gelesen; „kein
    Aufseher-Modell, das jede Ausgabe liest“, eine Alternative, die vorher
    nicht vorkam und dem prüfenden Review-Modell zu widersprechen schien
    (Basislinie, [README-Durchlauf](readme-walkthrough.de.md#basislinie-02c0078)).
12. **Knapp und genau.** Halbsätze statt Absätze; was Skizze oder Link
    tragen, wiederholt die Prosa nicht. Genauigkeit vor Kürze: keine
    künstliche Grenze, wenn ein Begriff sonst falsch wäre.
13. **Befehle wie ein Terminal.** Lesereihenfolge = Ausführungsreihenfolge:
    Kein Block setzt einen Schritt voraus, der später steht. Was der Leser
    anlegt, steht als Befehl im Block (`cat >datei <<'EOF'`), nicht als
    Prosa oder kopierte Drittdatei; Erklärungen als Zeilenend-Kommentar
    (`  # …`). Mitgeliefertes heißt so („hier nichts anzulegen“). Wo ein
    Block nicht an den vorigen anschließt, sagt ein Halbsatz davor, wo er
    beginnt. Fehler (`e54fb0a`): Schritt 3 beginnt „Im ki-dev-Klon nach
    Ausprobieren: `bd` liegt im Projekt-venv …“, und „Ausprobieren“ steht
    zwei Abschnitte danach; Schritt 2 zeigt ein Profil, das niemand
    schreibt, Schritt 3 kopiert es aus `docs/beispiele/default.toml`.
    Fehler (`b30e7fa`): Die Git-Identität setzt nur der Prüflauf
    (`user-flow.sh`); ein Besucher ohne globale Identität scheitert in
    Schritt 2 am Commit. Was ein Block braucht, setzt er selbst, so eng
    wie möglich (`git config` im Wegwerf-Repo).
14. **Die Statuszeile am Block.** Sie steht unter dem Block, den sie
    betrifft, und sagt, was geprüft wurde, mit Link auf den Test. Fehler
    (`2133c43`): „> ✅ bestanden · selbst prüfen: make readme-check“ über
    der Prosa; unklar, was bestanden hat, und „selbst prüfen“ liest sich
    als „nicht geprüft, prüf selbst“.
15. **Gegenstand statt Meta.** Ein Satz benennt, was da ist und was es
    tut. Zwei Fehler: eine Bewertung ohne Beleg („echt“, „gut“, „klar“)
    und eine Abgrenzung gegen eine Alternative, die der Leser nicht
    erwartet. Fehler (`02c0078`): Überschrift „Nicht nur Code“; wer sagte,
    es sei nur Code? Besser nach dem Inhalt: „Dasselbe Verfahren für
    Planung“. Fehler: „Ablauf, Profilformat und Befehle sind echt“; was
    läuft, belegen Statuszeile und Test, die Bewertung fügt nichts hinzu.
    Fehler: „Gute Einstiege, je mit klarer Abnahme“, und zwei von drei
    nannten keine. Ein Kontrast bleibt, wo die README selbst die
    Fehllesart nahelegt und das Gegenstück zeigt (Regel 2: nach dem
    Bug-Beispiel „ein Verfahren, keine einzelne Aufgabe“). Reichweite
    zeigen statt behaupten: ein zweiter Ablauf auf demselben Muster statt
    „hilft allgemein“.

## Arbeitsweise

- Vor jeder README-Änderung den aktuellen Stand committen, auch fremde
  Änderungen; sie sind absichtlich.
- Kleine Runden. Der Mensch sichtet und entscheidet. Eine Frage
  beantworten heißt nicht ändern.
- Erst die Gliederung gegen Auftrag und Regeln prüfen, dann Befunde einzeln
  beheben.
- DE und EN gleich aufgebaut. Erzeugte Blöcke nur über ihre Quellen:
  `readme-scripts/` mit `scripts/render-readme.py`, Ablaufdiagramme mit
  `scripts/render-flow-diagrams.py`; das Profil in Schritt 3 ist das
  HERE-Doc in `readme-scripts/4-rollen.sh`. Statuszeile und Ausgabe eines
  README-Skripts setzt nur `make readme-check`, direkt unter den
  geprüften Block (je Skript ein Test in `tests/readme/`, Stub mit
  Halbsatz für den Teil, den der Container nicht prüfen kann); der
  pre-push-Hook hält sie beim Push nach `dev` aktuell.
- Prüfen: `render-readme.py --check`, `render-flow-diagrams.py --check`,
  `pytest tests/test_doku_links.py tests/test_readme_render.py
  tests/test_readme_walkthrough.py tests/test_flow_diagram.py
  tests/test_readme_profile.py tests/test_readme_skizze.py`.

## Abnahme

- Ein Agenten-Durchlauf ([README-Durchlauf](readme-walkthrough.de.md)) ist
  ein Hinweis, nie die Abnahme; abgenommen wird von einem Menschen. Seine
  Fragen (`scripts/readme-walkthrough-uebergabe.txt`) richten sich an den
  Durchlauf-Agenten und prüfen die Regeln oben.
- Ein Durchlauf zählt nur, wenn er scheitern kann: je Persona das Modell
  nach dem ersten Bildschirm in drei Sätzen, verglichen mit dem Auftrag
  oben; beim Tech-Lead im selben Halt, was die Person hinter ki-dev einem
  Team beitragen kann, mit Zeilenbeleg aus dem ersten Bildschirm; jede
  Stelle mit zwei Lesarten samt beiden Lesarten; jede Bewertung ohne Beleg
  und jede Abgrenzung gegen eine nicht erwartete Alternative (Regel 15);
  jede Fährte, die nicht hielt, was sie versprach; der Abbruchpunkt.
  Liefert erst ein späterer Abschnitt die Antwort, ist das ein Befund
  gegen den früheren. Was als Scheitern gilt:
  [Wann ein Durchlauf scheitert](readme-walkthrough.de.md#wann-ein-durchlauf-scheitert).
- Kleinere Grenze: Markdown-Darstellung (Zeilenumbruch mit zwei
  Leerzeichen, Mermaid-Layout) in der GitHub-Vorschau nachsehen.
