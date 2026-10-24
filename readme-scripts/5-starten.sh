# Weiter in `versions-work`. ki-dev ruft jetzt die Agenten auf; je nach
# Modell dauert das Sekunden bis Minuten. Mit `-v` zeigt ki-dev
# Zustandswechsel und Agentenausgabe live.
#
# ```bash
ki-dev -f implement "$BEAD" --run-id version-fix  # Profil default
# ```
#
# Die Review-Antwort bestimmt den nächsten Übergang:
#
# | Review-Antwort | Reaktion von ki-dev |
# |---|---|
# | `fix` | Befund an `worker`; nach den zwei Korrekturrunden aus dem Profil Halt für dich. |
# | `PASS` | Bei grünen Tests Abschluss-Commit vorbereiten und per Fast-Forward nach `main` übernehmen; bei roten Tests anhalten. |
# | `decision` | Für deine Entscheidung anhalten; weiter unter [Entscheiden](#5-entscheiden). |
#
# Am Ende steht der Endzustand als JSON. Erwartet ist ein Halt für dich:
# `"status": "waiting_decision"`, wenn das Review eine Entscheidung
# verlangt, sonst `"paused_interactive"`, und `detail` nennt den Grund:
# `checks_failed`, wenn das Review trotz roter Tests `PASS` gemeldet hat,
# oder die aufgebrauchten Korrekturrunden, wenn es `fix` gemeldet hat.
# In jedem Fall bleibt `main` unverändert
# ([Halt und Fortsetzen](docs/ausfuehrer.de.md)).
