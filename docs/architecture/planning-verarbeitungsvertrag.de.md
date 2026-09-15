# Verarbeitungsvertrag: begrenzter Designnotizen-Versuch

Stand: 2026-09-15. Ergebnis von `ki-dev-ablauf-urq.1`. Dieser Vertrag bindet
ausschließlich den in `ki-dev-ablauf-urq` begrenzten, falsifizierbaren Versuch.
Er ist keine Freigabe der vollständigen Snapshot-Rückstandsverarbeitung und
kein Beginn der Implementierung; er hält lediglich fest, wonach der spätere
Abflachungsagent und dessen Review arbeiten, bevor Prüfbeispiele
(`ki-dev-ablauf-urq.2`), Datenbestand (`urq.3`/`urq.4`) und Ablauf (`urq.5`)
gebaut werden.

Quellen: `ki-dev-ablauf-urq` DESIGN/NOTES; `.loope/runs/0002-hier-ist-eine-vorschlage-ziel-bd/report.md`
(Vorgang 1); `docs/architecture/planning-graph.de.md`.

## Quellauswahl und Vollständigkeit

Die Quellauswahl mit Review legt die genauen relevanten Passagen einer neuen
Sitzung fest. Diese Auswahl ist die einzige Auswahlgrenze. Die anschließende
Zerlegung und Auflösung verarbeitet **alle** ausgewählten Inhalte; es gibt
keine zweite, stillschweigende Filterung danach (z.B. „nur die wichtigsten
Sätze“). Was ausgewählt ist, wird vollständig aufgelöst — nicht nur gezählt.

## Erhaltung und Modalitätstreue

Bedingungen, Ausnahmen, Beispiele und Vorschläge bleiben als Inhalt erhalten,
auch wenn sie (noch) keine Entscheidung sind. Die Modalität einer Aussage
(„Vorschlag“, „Empfehlung“, „Entscheidung“, „Zurückstellungsvorschlag“, …)
wird bedeutungstreu übernommen und nicht beim Verarbeiten verschärft oder
abgeschwächt. Ein späterer Zurückstellungs**vorschlag** darf also nicht als
beschlossene Rücknahme im Bestand erscheinen, solange die Quelle selbst keine
Entscheidung ausweist (siehe LangGraph-Fall in `urq.2`: Empfehlung in
Quellen-Bead ki-dev-ablauf-74lc, Entscheidung in Quellen-Bead ki-dev-ablauf-uxdk, Zurückstellungsvorschlag in
Codex-Sitzung 01a09aef).

## Zuordnung und inhaltliche Operation sind getrennte Urteile

Für jeden Bedeutungsanteil einer Passage sind zwei Urteile zu treffen und
getrennt zu protokollieren:

1. **Zuordnung**: Auf welche bestehende(n) fachliche(n) Einheit(en) bezieht
   sich dieser Anteil, falls überhaupt?
2. **Operation**: Welche inhaltliche Änderung folgt daraus — neuer Knoten,
   neue Revision, Widerspruch, Ergänzung, Zurückstellung, keine Änderung?

Eine automatische Verkettung aus Kandidatenfund zu Operation ist unzulässig;
siehe auch den Abschnitt zu Kandidatensuche unten.

## „Bereits enthalten“ braucht einen Abdeckungsnachweis

Die Einstufung, ein neuer Inhalt sei „bereits enthalten“, ist nur zulässig
mit einem konkreten Nachweis: Verweis auf die bestehende Knoten-/Kantenkennung
samt Revision, deren Datenfeld den neuen Anteil nachweislich abdeckt. Eine
bloße thematische Ähnlichkeit reicht nicht.

## Kandidatensuche, Ähnlichkeitswerte und Beziehungen

Die Lokalisierung (Raumumbau, siehe unten) ordnet die Kandidatensuche ein,
begrenzt sie aber nicht: die Suche nach passenden bestehenden Einheiten läuft
bereichsübergreifend über den gesamten aktuellen Bestand, nicht nur über den
vorab zugeordneten Bereich.

Gefundene Kandidaten sind selbst keine Beziehungen. Eine Kante und ihr Typ
entstehen ausschließlich aus dem geprüften Urteil über Zuordnung und
Operation (siehe oben). Ähnlichkeitswerte ordnen Kandidaten für die Prüfung;
sie begründen keine automatische Beziehung, Zusammenführung, Ersetzung oder
Entfernung, und sie werden nicht als Kantengewicht in den Designnotizenbestand
übernommen — sie erscheinen ausschließlich im Kontrollprotokoll des Laufs.

## Zerlegung in Bedeutungsanteile

Die Zerlegung einer Passage in ihre Bedeutungsanteile wird vor deren
inhaltlicher Verarbeitung gesondert gegen die Passage geprüft: Ist die
Anteilsliste vollständig? Diese Prüfung ist von der späteren Delta-Prüfung
(Zuordnung, Operation, Schema) getrennt und geht ihr voraus.

## Zuständigkeiten: strukturell vs. semantisch

Das Werkzeug (`src/ki_dev/planning.py`) prüft strukturell: Schema, erwartete
Revision, Quellenhash/-bereich, Kantenendpunkte, Typregister. Es behauptet
keine semantische Widerspruchsfreiheit (siehe `planning-graph.de.md`,
Abschnitt „Delta und Quellen“). Die semantische Prüfung — richtige Zuordnung,
vollständige Abdeckung, Modalitätstreue, Behandlung von Korrekturen — ist
Aufgabe des Reviews, nicht des Werkzeugs.

## Drei vorläufige Regeln für den Versuch

Diese drei Regeln sind ausdrücklich vorläufig. Sie gelten für den Versuch,
sind aber nicht als endgültig gelöst zu behandeln. `ki-dev-ablauf-urq.7`
bewertet nach dem Lauf (`urq.6`) für jede Regel: beibehalten, ändern oder
weiterhin offen.

### Raumumbau

Regel: Vor der Inhaltszuordnung entsteht eine vorgeprüfte Arbeitskarte
(welche Bereiche/Module der neuen Passage betroffen sein könnten); erst
danach erfolgt die eigentliche Inhaltszuordnung; die Übernahme ins Delta
erfolgt gemeinsam für eine Passage, nicht Anteil für Anteil unabhängig
committet.

Auswertungsfrage für Vorgang 7: Hat die vorgeprüfte Arbeitskarte im Lauf
falsche Bereiche ausgeschlossen oder relevante Kandidaten außerhalb der Karte
übersehen (siehe „begrenzt aber nicht die Kandidatensuche“ oben)?

### Abdeckungsgranularität

Regel: Abdeckung wird an identifizierten Bedeutungsanteilen mit ihrer
jeweiligen Ergebniszuordnung gemessen, nicht an der bloßen Anzahl erzeugter
Operationen (eine Operation kann mehrere Anteile abdecken oder ein Anteil
mehrere Operationen erfordern).

Auswertungsfrage für Vorgang 7: Ließ sich für jeden in `urq.2` als
Prüfbeispiel markierten Bedeutungsanteil eindeutig angeben, welche Operation
(falls keine, warum keine) ihn abdeckt — ohne auf die Operationszahl
auszuweichen?

### Korrekturrunden

Regel: Entwürfe und Reviewbefunde bleiben unterscheidbare, protokollierte
Objekte. Übernommen in den Bestand wird ausschließlich der abgenommene
Entwurf; Erstentwurf und Korrektur werden nicht als zwei unabhängige
Beobachtungen desselben Sachverhalts vermischt.

Auswertungsfrage für Vorgang 7: Ließen sich im Lauf Erstentwurf, Reviewbefund
und korrigierter Entwurf im Kontrollprotokoll eindeutig auseinanderhalten,
und wurde nur der abgenommene Entwurf tatsächlich per `append` übernommen?

## Nicht-Umfang dieses Vertrags

Keine endgültige Lösung der drei offenen Fragen. Keine Umsetzung des
Datenbestands oder Agentenablaufs (das sind `urq.3`–`urq.5`). Kein
Agentenlauf (`urq.6`). Keine Freigabe der vollständigen
Snapshot-Rückstandsverarbeitung.
