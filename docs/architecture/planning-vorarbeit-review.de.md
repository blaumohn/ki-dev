# Vorarbeit-Review: minimaler dateibasierter Bestand

Stand: 2026-09-15. Ergebnis von `ki-dev-ablauf-urq.3`. Prüft die vorhandene
ungetestete Vorarbeit (`docs/architecture/planning-graph.de.md`,
`src/ki_dev/planning.py`, `src/ki_dev/planning_cli.py`) gegen
`docs/architecture/planning-verarbeitungsvertrag.de.md` (`urq.1`) und
`docs/architecture/planning-pruefbeispiele.de.md` (`urq.2`), statt sie zu
ignorieren oder neu zu bauen (`urq` NOTES, Neuzuschnitt 15.09.2026).

## Übernommen, unverändert

- **Unveränderliche gespeicherte Einträge**: `append()` legt ausschließlich
  neue Dateien `NNNNNN.json` an (`xb`-Modus, kein Überschreiben);
  `resolve()` bindet jeden Schritt über den SHA-256-Hash seines Vorgängers
  (`delta["parent"] == previous["head"]`). Erfüllt die Vertragsanforderung
  „unveränderliche gespeicherte Einträge“ und „deterministische Auflösung
  zum Stand K“ (`resolve(store, at=K)`).
- **Typisierte Referenzfelder**: Kanten (`edges`) tragen `source`/`target`
  als fachliche Kennungen; `_apply_operation` prüft nach jedem Delta, dass
  keine Kante auf einen fehlenden Knoten zeigt (`dangling edge`).
- **Stabile Einheitenkennungen**: `_ID`-Muster erlaubt stabile,
  wiederverwendbare fachliche Kennungen unabhängig vom Ort.
- **Prüfungen für erwarteten Ausgangsstand / konkurrierende Ersetzungen**:
  `operation["expected"]` muss der aktuellen Revision entsprechen, sonst
  `revision mismatch`. Das deckt PB-5 (Rücknahme als neue, gegen die
  richtige Revision geprüfte Änderung) und die in `urq.3` geforderte Prüfung
  konkurrierender Ersetzungen.
- **Prüfungen für Referenzziele**: `source_ref()` bindet jede Quelle an
  Dateipfad, SHA-256 und Zeilenbereich; ein späterer Abgleich
  (`_apply_operation`, wenn `root` gesetzt ist) lehnt Deltas ab, deren Quelle
  sich seither geändert hat (`source changed`).
- **Zuständigkeitstrennung strukturell/semantisch**: Das Werkzeug prüft
  Schema, Revisionen, Endpunkte, Quellenhashes; es behauptet keine
  semantische Widerspruchsfreiheit (`planning-graph.de.md`, „Delta und
  Quellen“) — deckt sich mit der in `urq.1` festgehaltenen Zuständigkeit.

## Angepasst

- **„Jede Einheit stellt Inhalt, Ort und Typ in stabiler, einbettbarer Form
  bereit“** (`urq.3`-Umfang) war in der Vorarbeit nicht erfüllt: Knoten
  hatten `type` und `data`, aber kein strukturelles Ortsfeld. Ergänzt:
  Pflichtfeld `location` bei Knoten-`put`-Operationen (stabiler,
  pfadartiger String), ausdrücklich verboten bei Kanten (Kanten sind über
  ihre Endpunkte lokalisiert). Siehe `src/ki_dev/planning.py`
  (`_apply_operation`, `_PUT`-Schema) und `planning-graph.de.md`. Dies ist
  eine additive Erweiterung des bestehenden Schemas (neue optionale
  Eigenschaft `location`), keine Änderung bestehender gespeicherter
  Einträge — mit den bereits gespeicherten Verträgen dieses Versuchs
  kompatibel, da noch kein Schritt abgelegt wurde.
- **Ausdrücklich erlaubte Orts-/Typerweiterungen** (`urq.3`-Umfang): Ein
  Ortswechsel einer bestehenden fachlichen Einheit ist eine neue Revision
  unter derselben Kennung (`put` mit passendem `expected`), keine neue
  Identität — siehe `test_pb6_raumumbau_ist_neue_revision_nicht_neue_identitaet`
  in `tests/test_planning.py`. Typerweiterungen entstehen als neue
  Typkennung (`aussage@2` usw.); bestehende Typen bleiben unverändert
  (bereits in der Vorarbeit so vorgesehen, jetzt durch Tests abgenommen).

## Begründet nicht übernommen / verworfen

- Kein allgemeines Graphframework (NetworkX): nicht nötig für Speicherung,
  Auflösung und die in `urq.2` geforderten strukturellen Prüfungen; explizit
  `urq.3`-Nicht-Umfang.
- Kein Cross-Encoder, keine Kalibrierung, keine Embedding-Suche: gehört zu
  `urq.5`, nicht zu diesem Bestand.

## Kandidatenpaar-Referenzierbarkeit

Kandidatenpaare (für `urq.5`) sind über Einheitenkennung und die in
`node["revision"]` geführte Revision eindeutig referenzierbar; beides ist
bereits Teil des aufgelösten Zustands (`state["nodes"][id]["revision"]`).
Keine weitere Änderung nötig.

## Ergebnis

Die Vorarbeit erfüllt den überwiegenden Teil des Vertrags aus `urq.1`
bereits; die einzige strukturelle Lücke (`location`) ist geschlossen und
durch `tests/test_planning.py` gegen die Prüfbeispiele aus `urq.2`
abgenommen (siehe `ki-dev-ablauf-urq.4`). Kein Bestandteil der Vorarbeit
wurde verworfen und neu gebaut.
