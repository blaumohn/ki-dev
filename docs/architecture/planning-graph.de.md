# Unveränderliche Planungsdeltas und typisierter Planungsgraph

Stand: 2026-09-14. Modellierungsentscheidung aus der laufenden Planung.
Diese Entscheidung betrifft den Planungsspeicher; sie gibt keine zuvor
diskutierten Umsetzungsideen pauschal frei.

## Zweck

Nach jeder Sitzung wird deren Bedeutung einmal aufgelöst und auf betroffene
fachliche Einheiten lokalisiert. Gespeichert wird dieses Delta. Ein Werkzeug
erzeugt daraus deterministisch den Planungsgraphen zu Schritt K. Unbetroffene
Einheiten müssen weder neu interpretiert noch erneut gespeichert werden.

Der Graph G(K) enthält identifizierbare Aussageabschnitte, Beispiele und
typisierte Beziehungen. Eine fachliche Einheit ist nicht zwingend eine
mathematische Zusammenhangskomponente. Identitäten bleiben bei Präzisierungen
erhalten; eine Aufteilung verwendet neue Identitäten und explizite Beziehungen.
Der aktuelle Graph darf wachsen und schrumpfen. Seine Historie wächst nur.

## Unveränderlichkeit und Zeit

Ein Schritt ist eine einzelne JSON-Datei. Er bindet seinen Vorgänger über dessen
SHA-256-Inhaltshash. `append` legt ausschließlich eine neue Datei an und ersetzt
keine vorhandene. Die Schrittfolge ist der logische Zeitparameter; Zeitstempel
sind dafür nicht nötig. `resolve --at K` rekonstruiert genau diesen Stand.

Objektversionen, Typversionen, deren Wertemengen und gespeicherte Schritte
bleiben unverändert. Eine Operation `put` erzeugt eine neue Objektversion unter
derselben fachlichen Kennung; `delete` erzeugt einen historischen
Entfernungseintrag. Jede Änderung nennt die erwartete bisherige Revision.
Dadurch werden Deltas gegen einen anderen Ausgangsstand zurückgewiesen.

Hashketten erkennen Änderungen innerhalb einer vorhandenen Kette, sind aber
kein Schutz vor absichtlichem Neuschreiben einer vollständigen Historie.
Dateirechte/Backups bzw. extern bewahrte Hashes sind außerhalb dieses Schnitts.

## Typen, Werte und Beziehungen

Typdefinitionen haben eine unveränderliche Kennung einschließlich Version,
z.B. `aussage@1`. Sie enthalten `kind: node` oder `kind: edge` und ein
selbstständiges JSON Schema (Draft 2020-12) für das Datenfeld. Andere oder
erweiterte Definitionen erhalten eine neue Kennung. Alte Typen bleiben für
ihre bestehenden Objekte verfügbar; neue Pflichtfelder gelten nicht rückwirkend.

Erlaubte Bereiche oder Module können als `enum` im Schema stehen. Wächst die
Wertemenge, entsteht eine neue Typversion. Haben Bereiche oder Module eigene
Inhalte und Beziehungen, werden sie stattdessen selbst Knoten. Beide Fälle
gehören zum typisierten Modell, aber ein Modul ist nicht automatisch ein Typ.

Beziehungen sind eigenständige versionierte Objekte mit `source` und `target`
als fachlichen Knotenkennungen. Innerhalb eines aufgelösten Graphen beziehen
sie sich auf dessen aktive Knoten. Beim Entfernen eines Knotens müssen seine
Beziehungen ausdrücklich entfernt oder umgehängt werden. Es gibt keine stillen
Kaskaden. Eine Operation darf auf einen im selben Schritt angelegten Knoten
verweisen; geprüft wird der vollständige resultierende Graph.

Planungsobjekte benötigen keinen dynamischen Gültigkeitsstatus. Vorschläge,
Unsicherheiten und offene Entscheidungen bleiben im Inhalt erhalten. Ihre
Quellenrelevanz ist keine Umsetzungsfreigabe.

## Delta und Quellen

Ein Delta enthält `format: 1`, `step`, `parent`, neue `types` und die
Operationslisten `nodes` und `edges`. Jede Operation enthält `id`, `op`,
`expected` und `sources`. `expected` ist beim Anlegen null, ansonsten die
Revision aus dem aufgelösten Bestand. Bei `put` kommen `type`, `data` und bei
Beziehungen die beiden Endpunkte hinzu. Entfernte Kennungen werden in diesem
ersten Schnitt nicht wiederverwendet.

Jeder Knoten führt zusätzlich `location`: einen stabilen, pfadartigen
Ortsbezeichner (z.B. `ki-dev-loop/orchestrator-basis`). Namen und
Bereichspfade dienen der Suche und Darstellung, nicht der Identität — der
Ort einer fachlichen Einheit kann sich über Revisionen hinweg ändern (siehe
`urq.2`, Raumumbau). Beziehungen tragen keinen eigenen Ort; sie sind über
ihre Endpunkte lokalisiert. `location`, `data` und `type` zusammen bilden die
stabile, einbettbare Form, auf der die bereichsübergreifende Kandidatensuche
(`urq.5`) später arbeitet.

Eine Quelle nennt den relativen Repositorypfad, den SHA-256-Hash der Datei
und den inklusiven Zeilenbereich (`start`, `end`, jeweils ab 1). Bei JSONL ist
eine Zeile eine Nachricht. Das Werkzeug kann daraus eine kompakte Leseansicht
mit Rolle und Text erzeugen, ohne wiederholten vorherigen Kontext. Die Originale
werden nicht geändert. Quellenbereiche und Hashes sind technisch prüfbar;
richtige Interpretation und vollständige fachliche Abdeckung prüft der Review.

## Umsetzung und PM

Eine spätere PM-Schicht verweist auf fachliche Kennung plus konkrete Revision.
Damit kann ein abgeschlossener Vorgang zu einer alten Anforderungsversion
nicht stillschweigend die neue Version als umgesetzt ausweisen. Die erste
Implementierung baut keinen zweiten Vorgangstracker und leitet noch keinen
vollständigen Erfüllungsnachweis aus `bd` ab.

## Verarbeitung der bestehenden Planung

Reihenfolge: Designnotizen, Planungsquellen der ersten acht Sitzungen, anschließend Codex-Sitzung 01a08147 (JSONL).
Anlagen zu 005 werden zusammen mit 005 gelesen. Die laufende Entscheidung in
diesem Dokument ist der neue Auftrag für den Planungsspeicher. Frühere Aussagen
über dessen Zurückstellung dürfen diesen Auftrag nicht rückgängig machen.

Loope erhält pro Verarbeitungsschritt die Quelle und den aufgelösten Bestand.
Der Implementierer erzeugt das lokalisierte Delta, der Reviewer prüft Bedeutung,
Zuordnung, Auslassungen und die Behandlung späterer Korrekturen. Das Werkzeug
prüft Schema, Revisionen, Quellen und Endpunkte. Es behauptet keine semantische
Widerspruchsfreiheit. Gleichzeitige Alternativen dürfen ausdrücklich offen
bleiben. Ein lesbarer Bericht benennt Abdeckung und verbleibende Unsicherheiten.

Die gespeicherten Deltas sind das dauerhafte Ergebnis. Aufgelöstes JSON und
Markdown sind reproduzierbare Ansichten. Ein zukünftiger Index/Cache darf die
Auflösung beschleunigen; vollständige Snapshots pro Sitzung sind nicht nötig.
