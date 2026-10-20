# Weiter in `calc-work`:
#
# ```bash
ki-dev -f implement "$BEAD" --run-id add-fix  # Ablauf implement, Profil default
ki-dev -f implement status add-fix            # wo der Lauf steht
# ```
#
# Mit den Platzhaltern `019a…` und `b3f1…` hält der Lauf vor dem ersten
# Agentenaufruf an; für einen echten Lauf eigene Sitzungs-IDs ins Profil
# eintragen. Nach einem Halt setzt `ki-dev -f implement resume add-fix`
# den Lauf fort, mit `--answer`, wenn der Halt eine Antwort verlangt.
