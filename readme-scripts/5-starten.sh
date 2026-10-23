# Weiter in `calc-work`. ki-dev ruft jetzt die Agenten auf; je nach
# Modell dauert das Sekunden bis Minuten. Mit `-v` zeigt ki-dev
# Zustandswechsel und Agentenausgabe live.
#
# ```bash
ki-dev -f implement "$BEAD" --run-id add-fix  # Profil default
# ```
#
# Am Ende steht der Endzustand als JSON, nach Erfolg mit
# `"status": "passed"`. Hält der Lauf an, nennt `detail` den Grund;
# `ki-dev -f implement resume add-fix` setzt danach fort
# ([Halt und Fortsetzen](docs/ausfuehrer.de.md)).
