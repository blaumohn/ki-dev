# Konstruierte Testeingaben (urq.6, budgetierter Testschritt)

Diese Datei enthaelt ausschliesslich handgeschriebene, als `KONSTRUIERT`
markierte Testeingaben aus `docs/architecture/planning-pruefbeispiele.de.md`
(PB-5, PB-6). Sie sind keine echten Projektaussagen und duerfen nicht als
tatsaechliches Sitzungszitat in den Designnotizenbestand geraten. Der
Quellenverweis auf diese Datei macht das fuer jeden Review unmittelbar
sichtbar (siehe PB-5-Anforderung "Quellenverweis zeigt eindeutig auf die
konstruierte Testpassage, nicht auf eine echte Sitzung").

## PB-5 (KONSTRUIERT)

Die in Quellen-Bead ki-dev-ablauf-phdp (Zeile 106) beschlossene Entfernung von Ralphex aus dem
Bootstrap wird aufgehoben. Ralphex bleibt endgueltig Teil des
Bootstrap-Vorgehens; die Bedingung aus Zeile 102 gilt als nicht eingetreten.

## PB-6 (KONSTRUIERT)

Der bisherige Bereich `planungsspeicher` wird in `planungsspeicher/modell`
und `planungsspeicher/agentenablauf` aufgeteilt. Die bestehende Einheit zur
Unveraenderlichkeit gehoert ab jetzt zu `planungsspeicher/modell`.
