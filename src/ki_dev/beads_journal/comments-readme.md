# Kommentar-Journal

Ausgelagerte bd-Kommentare, je Vorgang `comments/<ID>.json`
(Zwischenlösung bis ki-dev-ablauf-dg9e). Beads tragen den aktuellen
Stand; Kommentare landen hier und werden danach in bd gelöscht.

Zustand je Eintrag (`state`):

- `open`: ausgelagert, noch nicht eingebaut.
- `incorporated`: vom Menschen gesichtet und nach Bedarf in den
  Vorgang eingebaut. Eingebaut heißt nicht zwingend, dass der Vorgang
  geändert wurde.

Vorgänge mit offenen Einträgen tragen in bd das Label `comments:open`
(`bd list --label comments:open`).

```bash
# Kommentare aus bd auslagern, je Vorgang committen, dann in bd löschen
.venv/bin/python -m ki_dev.beads_journal comments export
# Einträge eines Vorgangs abschließen (optional nur genannte
# Kommentar-IDs); vorher erneut export
.venv/bin/python -m ki_dev.beads_journal comments mark-incorporated <ID>
# Kommentare in bd und vertragswidrige Dateien (Exit 1),
# offene Einträge als Hinweis
.venv/bin/python -m ki_dev.beads_journal comments lint
```

Nur per Befehl ändern, nie von Hand: `lint` erkennt Verstöße gegen den
Vertrag. Zurücksetzen: `git checkout -- comments/<ID>.json`.
