# Kommentar-Journal

Ausgelagerte bd-Kommentare, je Vorgang `comments/<ID>.json`
(Zwischenlösung bis ki-dev-ablauf-dg9e). Beads tragen den aktuellen
Stand; Kommentare landen hier und werden danach in bd gelöscht.

Zustand je Eintrag (`state`):

- `open`: ausgelagert, noch nicht eingebaut.
- `incorporated`: vom Menschen gesichtet und nach Bedarf in den
  Vorgang eingebaut. Eingebaut heißt nicht zwingend, dass der Vorgang
  geändert wurde.

bd erfährt vom Zustand nichts (kein Label): Beads tragen nur den
aktuellen Stand, Historie liegt hier. Offene Einträge blockieren den
Commit im Projekt-Repo (pre-commit: erst `export`, dann `lint`), bis
sie eingebaut und abgeschlossen sind.

```bash
# Kommentare aus bd auslagern, je Vorgang committen, dann in bd löschen
.venv/bin/python -m ki_dev.beads_journal comments export
# Einträge eines Vorgangs abschließen (optional nur genannte
# Kommentar-IDs); vorher erneut export
.venv/bin/python -m ki_dev.beads_journal comments mark-incorporated <ID>
# reine Prüfung, Exit 1 bei Kommentaren in bd, vertragswidrigen
# Dateien oder offenen Einträgen
.venv/bin/python -m ki_dev.beads_journal comments lint
```

Nur per Befehl ändern, nie von Hand: `lint` erkennt Verstöße gegen den
Vertrag. Zurücksetzen: `git checkout -- comments/<ID>.json`.
