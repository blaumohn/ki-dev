# ADR: V1-Verbrauchsschutz bis jbr

Stand 2026-09-20, Policy v1/2 (PM-Präzisierung). Beschlossener Entwicklungsvertrag, keine Betriebsfreigabe.
Dieser normative Abschnitt samt [Typvertrag](v1/contracts.pyi) und
[Entscheidungstabellen/Prüffällen](v1/decisions.json) ersetzt widersprechende
V1-Empfehlungen in wu0.3.7 und im Zielbild tokenmessung-estimatoren.de.md.
[Historische Entwürfe und Reviews](v1/review-history.de.md) begründen Entscheidungen,
sind aber nicht verbindlich. Aufgaben und Fortschritt stehen ausschließlich in Beads.
MUSS ist Pflicht, SOLL begründet abweichbar, KANN optional.

## A — Messvertrag und Adaptergrenze

Der Kern MUSS mit normalisierten TokenCounts aus usage.py rechnen: deren total,
keine zusätzliche Addition von Cache-/Reasoning-Untergruppen. Pflichtbindungen:
run_id, call_id, session_id, provider_family, source_revision, task_revision,
family_id/family_revision, profile_hash. Bindung und kumulative Basis werden vor
Dispatch unter RunStore.usage_lock persistiert. Ein Prozess besitzt seine Sitzung
exklusiv; keine historische Mehrbenutzeranalyse. Fehlende Bindung blockiert.

LiveSample enthält eine CALL_TOTAL-Summe (nicht negativ) und einen Status.
Sequenzen sind strikt wachsende positive Ganzzahlen; Alter ist endlich >=0.
OK verlangt Total und Alter; nicht OK ist ein Lückenbeleg und kein neuer
Messwert. Ungültige Werte/Bindungen erzeugen INVALID_INPUT/BINDING_INVALID.
Der Adapter bildet kumulativen Stand minus Basis; Stand unter Basis ODER letztem
bestätigten Stand ergibt MEASUREMENT_DISCONTINUITY und keinen neuen Messwert.
Beispiel 100000 → 135000 = 35000; erneute 135000 = 35000; danach 90000 = Stop,
35000 bleiben bekannt. Alternativ nur native eindeutig belegte Requests summieren;
Zeit, Pfad, Zeile oder gleicher Tokenvektor sind keine Request-Identität.
Teilzeile bleibt unvollständig; letzter bestätigter Wert altert weiter. Wiederholtes
Lesen erneuert NICHT den Quellzeitpunkt. source_age_s muss belegte Aktualität
abbilden; ohne belegten Zeitbezug keine frische Messung. Neustart macht eine
persistierte monotone Uhr ungültig und verlangt frischen Quellenabgleich.

usage_accounting.reconcile_call MUSS Live-/Abschlussbeleg ersetzen/abgleichen,
nicht addieren. Abschluss unter Live-Summe ist Konflikt; bekannter Verbrauch bleibt.
UsageAttribution behält die vorhandenen fünf UsagePurpose-Werte; gemeinsame
Schätz-/Übergabekosten gehören genau einer Familie, nicht jedem Kind.
usage_task im echten CLI-Pfad verlangt bead_id, task_revision, family_id,
family_revision; parent_bead_id ist optional. Unveränderter Resume behält Revisionen
und die bestehende Laufbilanz.

V1-Entscheidung B (Nutzerentscheidung 2026-09-20): Ein geänderter Auftrag verlangt
eine explizite neue task_revision, eine passende neue Schätzung und einen neuen,
vom Menschen ausdrücklich freigegebenen Lauf mit eigener run_id und eigenem Budget.
Die family_id bleibt für denselben fachlichen Zusammenhang erhalten; family_revision
ändert sich nur bei geändertem Familienauftrag. Alte Calls behalten ihre Bindungen.
Ein Lauf umfasst Bau, Review und Reparaturen; er ist kein einzelner Agentenaufruf.
Der neue Lauf verwendet frische, voneinander getrennte Bau-/Review-Sitzungen mit
neuen session_ids. Eine neue run_id allein erzeugt keinen frischen Sitzungskontext.
Benötigte Arbeitsergebnisse und eine begrenzte Übergabe werden explizit übernommen.
usage_task bleibt pro Manifest unveränderlich; V1 bietet keinen Revisionswechsel
über resume_run und keine Revisionshistorie im Manifest.

Die Familienauswertung summiert alle zugehörigen Läufe auch über Revisionen hinweg;
sie ist keine laufübergreifende Budgetfreigabe. Frühere Laufkosten bleiben sichtbar,
werden aber nicht erneut vom unabhängig freigegebenen Budget des neuen Laufs
abgezogen. Automatische Ersatzläufe mit frischem Budget sind ausgeschlossen.
Ein Ersatzlauf hebt keine ungeklärte fortlaufende Wirkung des alten Laufs auf;
die bestehenden Stop-/Kontrollprüfungen bleiben Voraussetzung.

Zielmodule: safety_profile/contract.py (Datentypen ohne Providerimporte), safety_profile/validation.py,
safety_policy.py (reine Funktionen), usage_estimation.py; vorhandene loop_safety.py
bleibt einziger Ledger, executors/process.py bleibt Prozessmechanik. Anbieterpakete
executors/providers/claude/ und codex/ besitzen Parser, Versionslisten, Hook-Namen,
Konfigurationsprojektion und Nachweisdescriptor. usage.py und executors/metering.py
behalten delegierende Kompatibilitäts-Reexports; generische Datentypen bleiben
anbieterneutral. Provider importieren Vertrag; Policy/Ledger importieren keine
Providerpakete. dispatch wählt registrierte Adapter; keine feste Namensabbildung
zu Providerfamilien im Ledger. required_usage_fields im Descriptor benennt zusätzlich
erforderliche normalisierte Belege (beispielsweise cost_usd); fehlende Pflichtbelege
sperren unabhängig vom Adapternamen. Bestehende Kosten-/Quota-/Kontextguards bleiben.
Legacy ohne Bindung/Basis/Profil bleibt lesbar, blockiert aber Start/Resume;
keine automatische Nullmigration und keine zweite Safety-Bilanz.

## B — Kontrolle, Prozessende und Resume

Decision umfasst CONTINUE, STOP_AND_PAUSE, BLOCK_START, BLOCK_RESUME.
ReasonCode ist separat. Die vier totalen First-Match-Tabellen liegen als Daten vor.
Gemeinsamer Vorfilter in Reihenfolge: expliziter Stop, unbrauchbarer Schutzvertrag,
unklare Schutzkette. Ergebnisse werden pro Entscheidungspunkt auf BLOCK_START,
BLOCK_RESUME oder STOP_AND_PAUSE abgebildet. Alle weiteren zutreffenden Gründe
werden geordnet als secondary_reasons erhalten. CONTINUE erlaubt nur den lokalen
Entscheidungspunkt; es ist kein eigener Dispatch und keine Resume-Freigabe.
Projektfehler überstimmen niemals Schleifen-/Budget-/Messschutz. V1 verwendet
bestehendes stagnation_reason; kein neuer semantischer Schleifendetektor.
Lebendigkeit, Fortschritt und Verbrauchsgewissheit sind getrennte Beobachtungen.

Runner MUSS vor Dispatch reservieren. Crash nach Reservierung ist mehrdeutig und
führt nach Restart zu UNKNOWN_EFFECT, nie automatischem Redispatch.
Stop setzt zuerst dauerhafte Dispatch-Sperre, sendet TERM an die eigene isolierte
Prozessgruppe, nach terminate_grace_s KILL und wartet höchstens kill_wait_s.
Nur Linux/POSIX-Container mit belegter Gruppenisolation ist V1-Ausführungsplattform.
Ein entkommenes/relevantes ungeklärtes Kind verhindert bestätigten Stop.
Unabhängiger call_timeout_s läuft ab Prozessstart auch ohne Hook; Watchdog prüft
alle watchdog_interval_s. Fehlendes erstes Sample darf nur bis zur konfigurierten
startup_sample_timeout_s warten, bei bereits belegter Basis/Fähigkeit. Nachfolgend
stoppt Alter >= max_measurement_age_s; Laufzeit >= call_timeout_s stoppt.
Beim Tick stoppen M>=B, call_measured_tokens>=call_allocation_tokens oder
M+R+P+C>B. Vollständige Belegung M+R+P+C=B allein stoppt nicht.
Lese-/Hookfehler, unbekannter Kontrollzustand und Stoppfehler pausieren.
ProcessControl.tick wird bei jedem Watchdog-Termin ausgeführt; before_stop
persistiert die Dispatch-Sperre vor TERM, after_stop persistiert StopResult.
Fehlschlag eines Kontrollcallbacks erzwingt trotzdem lokalen Abbruch und
UNKNOWN_CONTROL_STATE; er darf den Prozess nicht weiterlaufen lassen. Der
V1-Startpfad MUSS control liefern und timeout_s aus call_timeout_s setzen;
der bisherige 900-s-Default dient nur API-Kompatibilität, nie Profilersatz.
Keine automatischen Modell-Retries, keine Diagnose durch Modellaufrufe.

Entscheidungspunkt und Call-Bezug (normativ):
- admit_start/admit_resume liegen vor Reservierung des neuen Calls. sample=None,
  elapsed_s=0 und call_measured_tokens=call_allocation_tokens=0 sind hier gültig;
  Live-Prädikate werden hier nicht ausgewertet. binding_valid/baseline_verified
  bezeichnen die vor Dispatch belegte neue Call-/Sitzungsbindung und Quellenbasis.
- admit_resume verlangt zusätzlich ledger_reconciled: frühere Calls sind nach
  frischem belegtem Abgleich vollständig verbucht oder fehlende Endabrechnungen
  nach den unten genannten Regeln konservativ belastet. Ein bloßes Wiederlesen
  alter Messdaten ist kein frischer Abgleich. Fehlender Abgleich ergibt UNKNOWN_EFFECT;
  Konflikte ergeben MEASUREMENT_DISCONTINUITY. Neue Basis/Fähigkeit/Quota müssen
  aktuell verifiziert sein; eine alte LiveSample-Pflicht besteht nicht.
- evaluate_tick bezeichnet ausschließlich den gerade laufenden Call. elapsed_s
  läuft monoton ab dessen Prozessstart. Auch ein nach Resume neu gestarteter Call
  erhält die Erstprobenfrist unter denselben Voraussetzungen wie jeder neue Call.
  Die Frist ersetzt niemals den vorgeschalteten Ledger-/Basisabgleich.
- on_phase_complete bezeichnet den letzten Call der abgeschlossenen Phase nach
  bestätigtem Prozessende und Abschlussabgleich, vor atomarer Phasenumbuchung.
  Ohne bestätigtes Ende: UNKNOWN_EFFECT. elapsed_s ist die bis zum Prozessende
  belegte Laufzeit; Nachbearbeitungszeit zählt nicht. sample ist der normalisierte
  Abschlussbeleg dieses Calls; source_age_s bezeichnet dessen belegte Aktualität
  am Prozessende, nicht das spätere Lesen. Ohne solchen Beleg wird pausiert.
  Die ursprüngliche Call-Zuteilung bleibt für die Abschlussprüfung erhalten,
  auch wenn ihre Restreservierung bereits freigegeben wurde.
  Hier stoppt call_measured_tokens>call_allocation_tokens, nicht Gleichheit.
  M>=B und Ledger-Overflow pausieren weiterhin weitere Arbeit.
  STOP_AND_PAUSE bewahrt ein erfolgreiches Arbeitsergebnis; bei bereits beendetem
  Prozess setzt es nur die Dispatch-Sperre und sendet kein nachträgliches TERM.
  CONTINUE ersetzt weder die atomare Umbuchung noch admit_start des nächsten Calls.
  Fehlende belegte Endzeit setzt control_known=False; sie wird nicht erfunden.

Lokaler Hook-Transport: private Unix-Domain-Socket je Run in einem 0700-Verzeichnis,
0600-Socket, Peer-UID prüfen; Run/Call/Session/Profilbindung und steigende Sequenz
prüfen. Maximal 16 KiB JSON je Nachricht, nur normalisierte erlaubte Felder; keine
Prompts, Toolargumente, Rohfehler oder Secrets. Provider-Helfer verwirft Rohfelder
vor Versand. ACK erst nach persistierter Kontrolle. Timeout/EOF/ungültige Nachricht
führt beim Runner zu Stop, nicht zur Freigabe. Hook-Client wartet höchstens
watchdog_interval_s; eine versäumte ACK löst keine Modellwiederholung aus.
Hook-Deny allein gilt nicht als Prozessende. Watchdog pollt die gebundene Quelle
auch ohne Hooks. Budgetpolitik liegt ausschließlich im Runner/Kern.

Resume MUSS ausdrückliche, an Run/Checkpoint/Profilrevision gebundene Freigabe,
frische Vorprüfungen, bestehenden Verbrauch und reservierten Resume-Kontextaufwand
prüfen. UNKNOWN_EFFECT trennt (1) ungeklärte fortlaufende Wirkung und (2) fehlende
Endabrechnung. Eine menschliche CONSERVATIVE_CHARGE darf nur (2) budgetseitig
ersetzen: bestätigtes Wirkungsende oder unabhängig belegte vollständige Restschranke
bleibt Voraussetzung. Buchung enthält event_id, call_id, Betrag, Operatorreferenz,
Begründungsreferenz und UTC-Zeit. Sie ist keine Messung, keine Kostenschranke und
keine automatische Freigabe. Unbegrenzte fortlaufende Wirkung bleibt gesperrt.
Späterer belegter Abgleich ersetzt die Buchung atomar, auch bei höherem Istwert.
Ein bloßes max_tokens-Feld belegt keine vollständige Restschranke.

## C — Budget, Reserven und Schätzung

Tokenzählmaß: TokenCounts.total; alle Beträge ganzzahlig, nicht negativ, keine bools.
Schätzungen verlangen schema_version=1, task/family_revision, profile_hash,
estimator_id/revision/model, assumptions_id, source_ref sowie obere Gesamt- und
Phasengrenzen. Phasen sind estimate, build, review, repair, handoff (estimate → ESTIMATION, build → IMPLEMENTATION, review → REVIEW, repair → REPAIR,
handoff → HANDOFF im Startpfad).
expected_estimators ist eine nichtleere Liste eindeutiger IDs aus dem Auftrag;
fehlende Urteile, unterschiedliche Bindungen/assumptions_id oder ungültige Werte
blockieren mit ESTIMATE_INVALID. V1 löst Annahmenkonflikte nicht automatisch.
Alle fünf Phasenfelder sind Pflicht (explizite Null erlaubt), ihre Summe darf die
Gesamtobergrenze nicht überschreiten. Ergebnis enthält Quellen und Strategieversion.

max_upper_v1/1: U=max(upper_tokens), je Phase P=max(phase_upper_tokens).
Falls Summe(P)>U, blockieren: kein erfundener passender Phasenschnitt.
B=ceil(U*reserve_factor), Dezimalarithmetik ohne Float-Abschneidung.
U>X erzwingt externe Aufteilung; U=X ist zulässig. B>task_cap_tokens blockiert;
kein min mit Kappe. Faktor 1.0 bedeutet bewusst keinen zusätzlichen Puffer.
B deckt in V1 den ausdrücklich freigegebenen Bau–Review-Lauf einschließlich
Reparaturen, Übergabe und der diesem Lauf zugeordneten Schätzung ab. Bereits
verbuchte, diesem Lauf zugeordnete Schätzkosten zählen genau einmal gegen B.
Gemeinsame Schätzkosten werden genau einem Lauf zugerechnet und in der Familie
nicht je Kind oder Ersatzlauf vervielfacht. M/R/P/C und task_cap_tokens gelten
für diesen Lauf; die Familie führt die kumulative Verbrauchsauswertung.
Beispiel: Lauf A verbraucht 20000 Tokens. Ein ausdrücklich freigegebener Lauf B
mit eigenem Budget 30000 kann weitere 30000 verbrauchen (abzüglich seiner eigenen
bereits verbuchten Kosten/Reservierungen); der Familienbericht weist dann bis zu
50000 aus. Resume von Lauf A behält dagegen dessen Verbrauch und Restbudget.
Nicht freigegebene Phasen halten P als geschützte Reserve; Übergang gibt deren
Rest unter derselben Sperre frei. Restbudgets dürfen nie doppelt erzeugt werden.
Der aktuelle Call verlangt explizites required_call_tokens>0; Zuteilung ist
min(B-M-R-P-C, call_cap_tokens, required_call_tokens). Unterdeckung blockiert.

Ledger bezeichnet M=gemessenen Verbrauch, R=offene, noch nicht verbrauchte
Call-Reservierungen, P=geschützte Phasenreserven, C=konservative Belastungen.
Zulassungsinvariante: M+R+P+C <= B vor jeder neuen Freigabe, auch nach Recovery.
Messzuwachs reduziert die zugehörige Restreservierung bis null, er addiert sich
nicht zu deren ursprünglicher Vollhöhe. Phasenfreigabe ist Umbuchung; idempotente
Ereignis-IDs und atomarer Ersatz verhindern Doppelzählung beim Replay.
Eine echte Messung KANN wegen Verzögerung M+R+P+C>B offenlegen. Dann MUSS die
Bilanz den vollständigen Wert behalten, OVER_BUDGET speichern und stoppen.
OVER_BUDGET und RECONCILIATION_CONFLICT sind LedgerFlag-Werte, keine ReasonCodes;
der Snapshot speichert eine Menge solcher Flags plus auslösende Ereignis-/Belegreferenzen.
OVER_BUDGET meldet BUDGET_EXHAUSTED. Abschluss unter bestätigter Live-Summe setzt
RECONCILIATION_CONFLICT; ledger_conflict meldet an allen vier Punkten
MEASUREMENT_DISCONTINUITY und sperrt weitere Arbeit. Bekannter Verbrauch bleibt.
Ein Konflikt wird nur durch belegten atomaren Quellenabgleich aufgelöst, weder
durch erneutes Lesen noch durch eine konservative Belastung verdeckt.
OVER_BUDGET wird erst nach belegtem Abgleich mit wieder zulässiger Belegung
entfernt; dies hebt eine Dispatch-Sperre nicht automatisch auf.
Die Review-Formel ist daher keine garantierte Echtzeitinvariante für externen
Verbrauch. Property-Tests prüfen Zulassung, Erhaltung beim Umbuchen, Replay und
wahrheitsgemäßen Overflow getrennt. Keine Kappung von Istwerten.

Persistenz: manifest.safety_profile enthält schema_version=1, policy_version=
v1/2, wirksame Werte, Herkunft je Feld und SHA-256. Profilhash über UTF-8 JSON mit
sortierten Keys, kompakten Separatoren, ohne NaN, Zeiten/Faktoren als kanonische
Dezimalstrings; keine Zugangsdaten. Unter usage_lock eine versionierte Ledger-
Snapshotdatei safety-ledger-v1.json atomar ersetzen (temp, fsync, rename, Verzeichnis-
fsync); applied_event_ids, M/R/P/C nach Call/Phase, Zustand und letzter bestätigter
Samplebezug darin speichern. Bestehende Call-/Usage-Artefakte bleiben Belege;
Snapshot ist materialisierte Sicht, kein unabhängiger Budgettopf. Beschädigte oder
nicht zum Manifest passende Sicht blockiert und verlangt belegbaren Abgleich.

## D — SafetyProfile und Präzedenz

SafetyProfile/1 verlangt alle im Typvertrag genannten Zeit-/Budgetwerte.
Betriebswerte sind REQUIRED_NO_DEFAULT: fehlend blockiert vor Reservierung.
Sekundenwerte sind endlich >0, Versuche positive ganze Zahl, Faktor >=1,
Tokenkappen/X positive ganze Zahl; call_cap<=task_cap, watchdog_interval<=
max_measurement_age und <=startup_sample_timeout, startup_sample_timeout<=
call_timeout. Stop-Wartezeit kommt zum Call-Timeout hinzu und ist endlich.
Diagnose ist lokal begrenzt; unveränderter Fehler ohne neue Evidenz beendet sie
auch vor diagnostic_attempts. Nachgewiesene externe Sperre stoppt sofort.

Präzedenz: versionierte Projektdefaults < benanntes Profil < explizite Aufrufwerte
innerhalb dokumentierter Autorisierung. Jede Ebene wird strikt validiert; unbekannte
Keys/Modi, NaN/Infinity, negative Werte und bool als Zahl sind Fehler. Kein Environment-
Override oder Hot-Reload. Snapshot vor Start; Resume übernimmt ihn nur unverändert
oder mit ausdrücklicher protokollierter Änderungsfreigabe und erneuter Zulassung.
Offline-Fixtures KÖNNEN 1/5/5/60 Sekunden für Watchdog/TERM/KILL/Diagnose,
1 Diagnoseversuch und Faktor 1.0 setzen, aber niemals als Betriebsfallback.

quota_mode default REQUIRE_VERIFIED_QUOTA; SUPERVISED_MANUAL nur mit gesonderter
Freigabereferenz, benannter Betreuung, Konto-/Fensterbeleg, endlichem quota_evidence_ttl_s
und aktuellen Start-/Resume-/Tick-Prüfungen. Kein IGNORE_QUOTA. evidence_mode default
EXISTING_ARTIFACTS_ONLY; AUTHORIZED_REAL_WORK verlangt konkreten realen Auftrag und
Freigabe, ist keine Testausnahme. him bleibt gültig. Mode-Wahl schafft keine Erlaubnis.

Notsteuerung im lokalen authentisierten Orchestrierungskanal (gleiche UID/Bindung,
persistierte Revision und idempotente event_id): STOP immer; nur folgende Änderungen
sind geordnet: task_cap_tokens, call_cap_tokens, max_measurement_age_s,
terminate_grace_s, kill_wait_s, call_timeout_s dürfen sinken oder gleich bleiben.
Andere Felder/Modi werden abgelehnt, auch wenn intuitiv strenger. Kürzere Frist
bezieht sich auf ursprünglichen Beginn; bereits abgelaufen bedeutet sofort Stop.
Kappe <= Verbrauch oder unter zugesagter Belegung stoppt; Reserven nicht abschneiden.
Profilbasis bleibt unverändert, effektive Verschärfungsereignisse werden separat
replayed und im Handoff referenziert. Keine Lockerung/Resume über diesen Kanal.

## Entwicklungsabschluss und Betriebsnachweis

Die vier Teilentscheidungen sind durch Schema, Einheiten, Validierung, Tabellen,
Typ-Stubs und Offline-Prüffälle abnehmbar. Reale Zahlen/Fähigkeiten sind kein
Abnahmekriterium dieser Entscheidung. Es gibt keinen universellen CLI-/Hook-Fallback.
Je Provider erfasst ein CapabilityDescriptor Version, Quellrevision, tatsächliche
Konfigurationspräzedenz, eigene Hook-Datei/Registrierung, Rechte/Mounts, modellfreie
Wirksamkeitsprobe, Rückbau und Evidenzreferenzen. Unverifizierter Descriptor sperrt
reale Ausführung; lokale Fakes dürfen ihn explizit simulieren.

wu0.10.2 ermittelt/implementiert diesen installationsabhängigen Beleg; .10.3 trennt
Nachweisautorisierung von abschließender Profilfreigabe. Erstere kann vor realer
Messung vorliegen. .3.6.3 erbringt vorhandene bzw. ausdrücklich autorisierte Belege;
abschließende .10.3-Freigabe leitet daraus Zahlen mit beobachtetem Aktualisierungs-
intervall, akzeptierter Messlücke und Begründung je Parameter ab. Ohne belastbare
Gesamtkostenschranke wird nur begrenztes akzeptiertes Risiko bestätigt.
Keine zyklische Abhängigkeit von Profilfreigabe und deren Belegen.

## Manueller Entwicklungsablauf bis zum wirksamen ki-dev loop

ki-dev loop steht für diesen Entwicklungsablauf noch nicht zur Verfügung.
Ziel ist vollständige, überprüfbare Software mit beherrschbarem Gesamtaufwand.
Tokenmessung und Stopmechanik sind Mittel dazu; niedriger Verbrauch oder erfolgreiche
Modellaufrufe allein sind kein Softwareerfolg. Teilumsetzung, Fehler, Nacharbeit,
wiederholter Kontext und offene Abnahmen bleiben sichtbar.

1. Der Umsetzer wählt einen bereiten Blattvorgang aus
   `bd ready --label v1:jbr --label workflow:implementation`, liest `bd show <id>`
   ohne den Beads-Status zu ändern. Ein Mensch kann die Auswahl vorgeben. workflow:gate und
   workflow:evidence gehören nicht in diese Umsetzungswarteschlange.
2. Eine manuell gestartete Sitzung bearbeitet nur dieses Blatt und seine direkten
   Offline-Tests. Kein ki-dev-loop-Aufruf und keine automatische Sitzungsverkettung.
   Fehlende normative Entscheidungen werden als konkrete Vertragslücke gemeldet.
3. Im gemeinsamen Arbeitsbaum ist die Beads-ID die normale vollständige Übergabe:
   `Setze <id> um.` Der Umsetzer liest AGENTS.md, `bd show <id>`, den dort genannten
   Vertrag und den vorhandenen Arbeitsstand. Ergebnis und Prüfnachweise stehen
   in Commit/Diff und Commitnachricht, nicht als Fortschrittschronik in Beads.
   Ohne Commit wird der uncommittete Stand ausdrücklich benannt; daraus folgt
   keine zusätzliche Erlaubnis für automatische Commits. Der Umsetzer verändert
   weder Auftrag noch Status. Nur `notes` darf er als temporäre Kurzmitteilung
   bis 600 Zeichen ersetzen. Der nächste Handoff-Schritt ersetzt oder leert
   diese nach Verarbeitung; kein Anhängen und keine Fortschrittskommentare.
   Zusatztext ist nur nötig, wenn der
   tatsächliche Änderungsstand nicht zugänglich ist oder vom Vorgang abweicht.
4. Nach jeder Umsetzersitzung startet ein Mensch eine getrennte Review-Agent-Sitzung
   mit `Reviewe <id>.` Auch hier sind Beads-ID und gemeinsamer Arbeitsbaum die
   Übergabe; Gesprächstranskripte werden nicht kopiert. Der Review-Agent prüft den
   tatsächlichen Stand und Diff gegen Auftrag, Vertrag und dokumentierte Prüfungen.
   Fehlender Änderungsstand erlaubt keine Abnahmebehauptung. Das Review liefert
   begründete zusätzliche Sichtpunkte; es ist nicht autoritativer als der Umsetzer.
   Jeder Befund wird mit Beleg übernommen, begründet verworfen oder bei fehlender
   Entscheidung an PM/Mensch zurückgegeben. Reviewtext allein ändert keinen Vertrag.
5. Bis zur Auswertung bleibt der Status unverändert. Claim und Abschluss liegen
   beim Menschen beziehungsweise beauftragten Planer, nicht beim Umsetzer.
   Erst vollständige Abnahmen und ausgewertete relevante Befunde erlauben bd close.
   Nötige Korrekturen bleiben im Auftrag oder erhalten einen expliziten Folgeauftrag
   mit passender Blockerabhängigkeit; unerfüllte Pflichtabnahmen werden nicht verschoben,
   um das Blatt zu schließen. Danach wird der nächste bereite Auftrag gewählt.
   Eltern schließen erst nach allen Pflichtkindern und eigener Abnahme.

Die Fall-IDs in decisions.json besitzen zuständige Beads-Blätter (owner_beads).
Dort sind die Prosaorakel in ausführbare Offline-Tests zu übersetzen. Policytests
müssen jede Tabellenzeile erreichbar prüfen, First-Match bei mehreren Fehlern,
geordnete eindeutige secondary_reasons und Grenzwerte unter/gleich/über Grenze.
Andere CONTINUE-Zeilen liefern keinen zusätzlichen Fehlergrund OK.
Diese PM-Materialisierung implementiert und testet keine Runtime und erteilt
keine Betriebsfreigabe. Reale Nachweise bleiben gesonderte autorisierte Arbeit.
