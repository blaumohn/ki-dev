# Weiter in `app-work`. ki-dev ruft jetzt die Agenten auf; je nach
# Modell dauert das Sekunden bis Minuten. Mit `-v` zeigt ki-dev
# Zustandswechsel und Agentenausgabe live.
#
# ```bash
ki-dev -f implement "$BEAD" --run-id version-fix  # Profil default
# ```
#
# Welcher Übergang auf eine Antwort folgt, legt `implement.toml` fest:
#
# | Antwort | Übergang in `implement` |
# |---|---|
# | `worker` fertig | Tests aus dem Profil ausführen, dann `review` fragen. |
# | `worker` mit offener Frage | Ohne Änderung Halt für dich ([Entscheiden](#5-entscheiden)); mit Änderung prüfen Tests und `review` die Runde. |
# | `review`: `fix` | Befund an `worker`; nach den zwei Korrekturrunden aus dem Profil Halt für dich. |
# | `review`: `PASS` | Bei grünen Tests Abschluss-Commit per Fast-Forward nach `main`; bei roten Tests Halt. |
# | `review`: `decision` | Für deine Entscheidung anhalten. |
#
# Am Ende steht der Endzustand als JSON. Erwartet ist ein Halt für dich;
# wer ihn auslöst, hängt von den Antworten ab: `"waiting_decision"`
# nach einer Frage des `worker` oder `decision` des `review`,
# `"paused_interactive"`, wenn Test-Tor oder Rundengrenze halten. Den
# Grund zeigt `history` in [Schritt 5](#5-entscheiden); `main` bleibt
# unverändert ([Halt und Fortsetzen](docs/ausfuehrer.de.md)).
