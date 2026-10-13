"""step: ein Turn eines Paketablaufs mit dem Executor manual,
zustandslos (``ki-dev -f ABLAUF step BEAD ZUSTAND [ZUSTAND=DATEI …]``).

Für einen Zustand eines Ablaufs wird die Übergabe an die nächste
Sitzung erzeugt oder, mit einer Antwort, die nächste danach (Adapter
manual: der Mensch trägt sie weiter); gespeichert wird nichts.
Prüfungen (Vorlauf) und Rollenrechte gehören zur Übergabe, nicht zu
einer Schleife.
"""
