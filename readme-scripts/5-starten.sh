# ```bash
ki-dev -f implement "$BEAD" --run-id add-fix
ki-dev -f implement status add-fix
# ```
#
# Ablauf `implement` mit dem Profil `default` aus Schritt 2, Lauf
# `add-fix`; `status` zeigt, wo er steht. Nach einem Halt setzt
# `ki-dev -f implement resume add-fix` ihn fort, mit `--answer`, wenn der
# Halt eine Antwort verlangt. Mit den Platzhaltern `019a…` und `b3f1…`
# hält der Lauf vor dem ersten Agentenaufruf an; für einen echten Lauf
# eigene Sitzungs-IDs ins Profil eintragen.
