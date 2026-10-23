# README-Leitlinie: Gestaltung für Menschen

Für Änderungen an `README.md` und `README.en.md`. Maßstab ist der Weg
eines Lesers vom ersten Satz bis zum Ausprobieren. Korrekte Einzelaussagen
und bestandene Tests reichen dafür nicht aus.

## Warum diese Seite

Die Überarbeitungen `dxc2`, `9wtu`, `i0ro` und `qaa0` ließen den Einstieg
trotz technischer Prüfungen schwer verständlich. Die Rückmeldung vom
2026-10-22 benennt die Ursache: Problemprosa vor dem Programmtyp, Begriffe
vor ihrem Beispiel, vermischte Voraussetzungen und eine unerklärte Demo.

Eine lange Einleitung wird durch kurze Sätze allein nicht besser. Die
Reihenfolge muss die Fragen beantworten, die beim Lesen gerade entstehen.

Die zweite Rückmeldung vom 2026-10-22 betrifft das Minimalbeispiel: Es
verlangte vorbereitete Sitzungen und Platzhalter-IDs und verwies für die
Voraussetzungen über zwei Links bis in die Adapter-Dokumentation. Ein
Beispiel, das sich so nennt, muss mit den genannten Voraussetzungen bis
zum Ergebnis laufen.

## Auftrag

Der erste Satz sagt, welche Art Programm ki-dev ist und wofür es verwendet
wird. Ein frühes Beispiel zeigt die Zusammenarbeit der Teile. Wer als
Tech-Lead eine Bewerbung sichtet, erkennt daran die technische Arbeit und
die Entwurfsentscheidung, mit Belegen einen Klick entfernt.

Danach kann ein Leser entscheiden: weiter erkunden, ausprobieren, beitragen
oder Kontakt aufnehmen. Der Entwicklungsstand ist vor einem eigenen Lauf
sichtbar. Die README verspricht nur, was Code und Prüfungen belegen.

## Wie ein Mensch liest

- **Überfliegen:** Überschriften, Listen, Beispiele und Ausgaben ergeben
  schon einen verständlichen Weg.
- **Am Beispiel lernen:** Aussage und konkrete Wirkung stehen beieinander.
  Detailwissen kommt dort hinzu, wo es gebraucht wird.
- **Ausprobieren:** Zweck, Voraussetzungen und erwartetes Ergebnis müssen
  vor dem Befehl klar sein.
- **Springen:** Links benennen ihren Inhalt. Ein späterer Absatz repariert
  keine frühere Fehlinterpretation.

## Regeln mit Fehlbeispiel

1. **Programmtyp zuerst.** „Python-Kommandozeilenprogramm für …“ ordnet
   ki-dev ein. „KI-Agenten melden fertig, auch wenn …“ verlangt diese
   Einordnung bereits und klingt ohne Repo-Bezug wie ein Artikelauftakt.
2. **Aussage am Beispiel erklären.** Umsetzung → Review → Korrektur →
   Abschluss zeigt das Verfahren. „Keine einzelne Aufgabe“ setzt eine
   unerklärte Gegenposition voraus.
3. **Mitgeliefert, konfigurierbar und erweiterbar benennen.** `worker` und
   `review` sind Rollen des mitgelieferten Ablaufs. Das Profil besetzt sie;
   eigene Pakete dürfen eigene Rollen und Übergänge festlegen.
4. **Handlungen als Schritte.** Mehrere Handlungen werden eine Liste.
   „Review in eigener Sitzung“ braucht einen Akteur und den Hinweis, zu
   welchem Ablauf die Aussage gehört.
5. **Voraussetzungen nach Zweck trennen.** Python für ki-dev, Git und `bd`
   für die gezeigten Abläufe, Go und C zum Bauen von `bd`. Anforderungen
   des gewählten Installationswegs stehen vor dessen Befehlen.
6. **Ein Weg durch die Einrichtung.** Befehle laufen in Lesereihenfolge;
   Arbeitsverzeichnis und nötige Dateien stehen dabei. Eine optionale
   Demo ist als solche erkennbar und kein Testziel.
7. **Ausgaben erklären.** Vor der Demo steht, was sie tut. Danach muss der
   Leser das Ergebnis erkennen können. `status: passed` allein erklärt
   weder Korrekturrunde noch Übernahme. Vorgegebene Antworten belegen die
   Steuerung, nicht die Leistung eines Agenten.
8. **Grenzen vor der Handlung.** Modellzugang und Tokenverbrauch stehen
   vor dem ersten Befehl, nicht hinter einem Link. Ein Stand-Abschnitt
   bündelt die Lücken; relevante Grenzen bleiben am Beispiel sichtbar.
9. **Kurze Abschnitte mit einer Aufgabe.** Überschriften, Listen und Tabellen
   tragen die Struktur. Erzwungene Halbsätze und ein Link an jedem Fachwort
   können den Lesefluss ebenfalls unterbrechen.
10. **Details vertiefen das Beispiel.** Protokoll, TOML und Architektur zeigen
    denselben Ablauf. Lange Diagramme können einklappbar sein; entscheidende
    Erklärungen müssen auch ohne sie verständlich bleiben.
11. **Belege passend einordnen.** Forschung gehört zur Entwurfsentscheidung.
    Sie belegt weder ein persönliches Problem des Autors noch automatisch
    einen Nutzen von ki-dev.
12. **Begriffe im Zusammenhang erklären.** Eine Rolle beschreibt die Aufgabe,
    ein Executor die Anbindung. Danach erst helfen Begriffe wie Operation,
    Wächter und Runner.
13. **Gegen Code und Artefakte prüfen.** Pfade, Zustände, Konfiguration und
    Ausgaben müssen stimmen. Kürzungen kennzeichnen, Architekturziel und
    Ist-Stand auseinanderhalten.
14. **Prüfergebnisse automatisch pflegen.** Status und Ausgabe gehören zum
    geprüften Block. Ein fehlender Lauf ist kein bestandener Lauf.
15. **Gegenstand statt Bewertung.** Unbelegte Wertungen und Abgrenzungen
    gegen unerwartete Alternativen streichen. Positiv erklären, was das
    Programm tut, auch wo eine frühere Leitlinie einen Kontrast erlaubte.

## Leserzeit und Bildschirmfläche

Jeder Abschnitt muss seinen Platz durch eine Frage rechtfertigen, die der
Leser an dieser Stelle beantworten will. Die ersten Bildschirme dienen dem
Verständnis des Projekts. Installation, Vorführungen und interne Details
dürfen dafür keine Voraussetzung sein.

- **Ein Beispiel trägt die Erklärung.** Ablauf und Beispielauftrag getrennt
  benennen: `implement` führt Codeänderungen durch; `is_newer` ist ein gewählter
  Auftrag. Allgemeines Verfahren und konkrete Arbeit nicht im selben
  unklaren „soll … reparieren“-Satz zusammenziehen.
- **Ein Hauptweg.** Erst das Zusammenspiel am Minimalbeispiel, dann die
  Einrichtung, dann Stand und Erweiterung. Der nächste Link führt zum
  angekündigten nächsten Schritt.
- **Ein Hauptgericht.** Das Minimalbeispiel läuft mit echten Agenten von
  der Einrichtung bis zum Ergebnis, alle Schritte in der README. Die Demo
  mit vorgegebenen Antworten (`MOCK.md`) ist die Beilage für Leser ohne
  Modellzugang; ihr Hinweis steht dort, wo diese Frage entsteht: bei der
  Voraussetzung „Agenten“.
- **Verstehen vor Ausführen.** Erst erklärt die README, was ein Lauf tut;
  danach folgen die Schritte mit Voraussetzungen vor dem ersten Befehl.
  Vertiefungen (Ablaufregeln, Protokoll, Architektur) stehen in
  `docs/vertiefung.*.md` und sind für den Hauptweg nicht nötig.
- **Inhalt ist eine Landkarte.** Die Einträge bilden Überschriften und
  Reihenfolge ab. Unterschiedliche Lesetätigkeiten nicht als flache Folge
  vermeintlicher Arbeitsschritte durchnummerieren. In der Anleitung sind
  die tatsächlich nacheinander auszuführenden Schritte nummeriert.
- **Nähe spart Sucharbeit.** Einrichtung und Demo bekommen eigene Skripte,
  Tests und Statuszeilen. Eine Statuszeile nach der Demo kann der Leser
  nicht zuverlässig der Einrichtung davor zuordnen. Ein generiertes
  Skript enthält deshalb genau einen Bash-Block.
- **Vertiefung auf Nachfrage.** Lange Profile, Zustandsdiagramme, Protokolle
  und Architekturdetails sind verlinkt. Beim Kürzen ihre Fundstellen
  erhalten; nicht allein durch Einklappen aus dem Blick nehmen.

Für jeden Absatz, Codeblock und Link fragen: Welche Entscheidung ermöglicht
er jetzt? Fehlt sein Vorwissen? Wiederholt er etwas? Erzeugt er einen
Umweg? Gehört er in die Anleitung? Diese Fragen gelten für die gesamte
README; die beobachteten Fehler sind Beispiele, keine abschließende Liste.

## Arbeitsweise

- Den Nutzerauftrag bearbeiten; keine Zwischenfreigabe aus dieser Leitlinie
  ableiten. Fremde Änderungen erhalten.
- README und Anleitung in DE/EN gleich aufbauen. Befehle und zugehörige
  Erklärungen in `readme-scripts/` ändern, mit `scripts/render-readme.py`
  erzeugen. Jedes Skript steht je Sprache genau einmal in README oder
  `docs/vertiefung.*.md`; Links werden passend zur Seite erzeugt.
- `make readme-check` führt die Beispiele in Docker aus und schreibt Status
  und Auszüge genau dieses Laufs in beide READMEs. Ergebnisse nicht von Hand
  umformulieren oder einen Hostlauf als Containerprüfung ausgeben.
  Der pre-push-Hook nutzt dasselbe Ziel.
- `make readme-live` führt das Beispiel mit echten Agenten aus (verbraucht
  Tokens) und legt Ergebnis und Ereignisprotokoll in
  `docs/beispiele/echtlauf/` ab. Die README kennzeichnet es als „Mit echten
  Agenten ausgeführt“, getrennt von der Containerprüfung.
- Ablaufdiagramme mit `scripts/render-flow-diagrams.py` erzeugen.
- Beide Renderer mit `--check` prüfen, dazu `tests/test_doku_links.py`,
  `tests/test_readme_render.py`, `tests/test_readme_walkthrough.py`,
  `tests/test_flow_diagram.py`, `tests/test_readme_profile.py` und
  `tests/test_readme_skizze.py` ausführen.

## Abnahme

Mit vorhandenem `mdman` aus `../mdman` oder Python Rich bei 80 und 100
Spalten lesen. Keine neuen Markdown-Werkzeuge installieren. Verzeichnis,
Listen, Code und Tabellen tatsächlich ansehen. HTML und Mermaid werden im
Terminal nur eingeschränkt dargestellt; diese Grenze benennen.

Beim ersten Bildschirm anhalten: Sind Programmtyp, Zweck und Beispiel
verständlich, ohne späteres Wissen zu ergänzen? Danach den ganzen Leserweg
prüfen: Was ist vor jeder Handlung bekannt, was bleibt mehrdeutig, was
verspricht ein Link, was erklärt eine Ausgabe?

Der [README-Durchlauf](readme-walkthrough.de.md) kann Hinweise liefern.
Ein Agentenurteil und grüne Tests sind keine menschliche DX-Abnahme. Bei
„keine Subagents“ wird kein separater Durchlauf-Agent gestartet. Befunde
und noch nicht mögliche Prüfungen konkret festhalten.

## Vorbilder

- [jq](https://github.com/jqlang/jq/blob/master/README.md): Programmtyp und
  Aufgabe sofort benannt; Bauvoraussetzungen beim Bau aus dem Quellcode.
- [uv](https://github.com/astral-sh/uv/blob/main/README.md): Funktionen mit
  ausführbaren Beispielen und Ergebnissen unmittelbar daneben.

Diese Strukturentscheidungen sind Anregungen. Wortlaut, Funktionsumfang
und Reifeversprechen werden nicht auf ki-dev übertragen.
