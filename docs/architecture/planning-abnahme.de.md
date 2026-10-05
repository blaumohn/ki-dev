# Datenmodell-Abnahme: begrenzter Designnotizen-Versuch

Stand: 2026-09-15. Ergebnis von `ki-dev-ablauf-urq.4`. Nimmt das in `urq.3`
umgesetzte Datenmodell (`src/ki_dev/planning.py`) gegen die in `urq.2`
festgelegten Prüfbeispiele (`docs/architecture/planning-pruefbeispiele.de.md`,
PB-1 bis PB-7) ab, getrennt vom späteren Agentenversuch (`urq.6`). Prüft
ausschließlich strukturelle Darstellbarkeit und Zurückweisung ungültiger
Änderungen — keine semantische Verarbeitung (Zuordnung, Auflösung von
Bedeutungsanteilen) durch einen Agenten.

Quelle der Abnahmefälle: `tests/test_planning.py`.

## Reproduzierte Prüfbeispiele

| Beispiel | Test | Ergebnis |
| --- | --- | --- |
| PB-1 (bedingte Rücknahme/Widerspruch) | `test_pb1_bedingte_ruecknahme_erhaelt_beide_anteile` | beide bedingten Anteile bleiben als getrennte Knoten erhalten |
| PB-2 (Verwerfen/Ersetzen) | `test_pb2_ersetzung_verknuepft_statt_zu_loeschen` | alter Knoten bleibt, `ersetzt_durch`-Kante verknüpft statt zu löschen |
| PB-3 (bereichsübergreifende Dublette) | `test_pb3_dublette_ist_ohne_ortsbindung_verknuepfbar` | Kante zwischen Knoten an entfernten Orten ist ohne Ortsbindung darstellbar |
| PB-4 (LangGraph-Fall L: Empfehlung → Entscheidung → Zurückstellungsvorschlag) | `test_pb4_langgraph_fall_l_haelt_drei_modalitaeten_nebeneinander` | alle drei Modalitäten bleiben als getrennte Knoten bestehen; Vorschlag überschreibt Entscheidung nicht |
| PB-5 (Rücknahme, KONSTRUIERT) | `test_pb5_ruecknahme_ist_neue_kante_auf_bestehende_entscheidung` | widerrufene Entscheidung bleibt erhalten, `hebt_auf`-Kante zeigt Rücknahme an |
| PB-6 (Raumumbau) | `test_pb6_raumumbau_ist_neue_revision_nicht_neue_identitaet` | Ortswechsel ist neue Revision derselben Kennung |

PB-3 und PB-5 verwenden aus Testzwecken echte, strukturell gültige
Quellenverweise, deren zitierter Text nicht wörtlich dem Knotentext
entspricht (PB-3: Kandidatensuche selbst ist nicht Gegenstand dieses Tests,
siehe unten; PB-5 ist ohnehin `KONSTRUIERT`, siehe
`planning-pruefbeispiele.de.md`). Das prüft ausschließlich, ob das Modell die
jeweilige *Struktur* darstellen kann — nicht, ob ein Agent sie später korrekt
erzeugt (`urq.6`).

## PB-7 ist kein Fall für dieses Datenmodell

PB-7 prüft die Abdeckungsnachweis-Pflicht bei „bereits enthalten“: eine
Einstufung „bereits enthalten“ braucht einen Verweis auf eine bestehende
Knoten-/Kantenrevision, die den neuen Anteil nachweislich abdeckt. Nach dem
Vertrag (`planning-verarbeitungsvertrag.de.md`, „Kandidatensuche,
Ähnlichkeitswerte und Beziehungen“) erzeugt eine solche Einstufung *keinen*
neuen Knoten oder keine neue Kante im Bestand — sie ist eine Entscheidung
„keine Änderung“ mit Begründung, die ausschließlich im Kontrollprotokoll des
Agenten-/Reviewablaufs (`urq.5`) geführt wird, nicht im append-only
Planungsgraphen selbst. Der Planungsgraph (`src/ki_dev/planning.py`) hat
dafür bewusst kein Format; ein Kontrollprotokoll-Format ist Gegenstand von
`urq.5`. PB-7 ist damit kein struktureller Abnahmefall für `urq.4`, sondern
ein Abnahmefall für das Kontrollprotokoll in `urq.5` (dort erneut
aufzugreifen).

## Zurückweisung ungültiger Änderungen

Bereits durch die Vorarbeit (`urq.3`) abgedeckt und hier erneut bestätigt:
fehlendes `location` bei Knoten, `location` bei Kanten, konkurrierende
Ersetzung mit falscher `expected`-Revision, hängende Kantenenden, Wieder-
verwendung einer stillgelegten Kennung, veränderte Quelle seit Referenzierung
(`tests/test_planning.py`, `test_node_without_location_is_rejected` bis
`test_source_changed_is_rejected`). Deterministische Auflösung zum Stand `K`
bestätigt durch `test_resolve_at_k_is_deterministic`.

## Gefundene Modell-/Implementierungsfehler

Keine. Alle 13 Tests in `tests/test_planning.py` (7 Prüfbeispiel-Fälle, 6
Fälle für ungültige Änderungen/Determinismus) bestehen gegen die
unveränderte Vorarbeit aus `urq.3`; es waren keine Korrekturen am Modell
nötig.

## Nicht-Umfang dieses Dokuments

Kein Agentenlauf (`urq.6`); keine Erweiterung der Prüfbeispiele über `urq.2`
hinaus; kein Kontrollprotokoll-Format (`urq.5`, siehe PB-7 oben).
