# Verbrauchsanalyse uar-2-02

Stand: 16. September 2026. Bezug: `ki-dev-ablauf-047`.

Der Verbrauch entstand durch eine unzureichend begrenzte innere
Agentenschleife und die wiederholte Verwendung eines wachsenden
Sitzungsverlaufs. Die Zahl der aeusseren Bauversuche bildet die Zahl
der Modellanfragen nicht ab. Ein erforderlicher Aufwand dieser Groesse
fuer das Statuskommando ist damit nicht begruendet.

## Nachweis

Quelle ist das lokale Claude-Transkript der im Laufmanifest genannten
Bausitzung `f76a069d-40b4-4328-905c-9b68ebc57363`. Die Auswertung beginnt
beim Bauauftrag fuer diesen Lauf; die beiden vorbereitenden Antworten
werden ausgeschlossen. Mehrere Streaming-Bloecke derselben
`message.id` werden einmal gezaehlt. Synthetische Fehlermeldungen
werden nicht als Modellverbrauch gezaehlt.

| Runde | Modellanfragen | Kontext je Anfrage, min.–max. | Cache-Lesetokens | Ausgabetokens |
| --- | ---: | ---: | ---: | ---: |
| 1 | 47 | 28.765–83.009 | 3.011.895 | 20.801 |
| 2 | 41 | 85.281–146.481 | 4.780.642 | 32.904 |
| 3 | 27 | 149.408–185.387 | 4.550.807 | 24.566 |
| 4 | 27 | 187.720–221.800 | 5.570.776 | 23.063 |
| 5 | 19 | 224.188–250.882 | 4.583.664 | 18.795 |
| 6, abgebrochen | 19 | 253.609–272.413 | 4.985.201 | 10.994 |
| Gesamt | **180** | | **27.482.985** | **131.123** |

Zusaetzlich: 244.608 Cache-Schreibtokens und 360 ungecachte
Eingabetokens. Cache-Lesetokens sind wiederholte Verarbeitung desselben
Verlaufs, nicht 27 Millionen unterschiedliche Tokens und auch nicht
gleichzusetzen mit voll berechneten ungecachten Tokens.

Um `13:25:11.016 UTC` meldet Claude `rate_limit`, HTTP 429 und
`rateLimitType: five_hour`. Der letzte Laufcheckpoint um
`13:25:11.271 UTC` steht in Runde 6 auf `paused_interactive`, jedoch
mit der unzureichenden Erklaerung `process_retries_exhausted` und
`RuntimeError: CLI endete mit Exitstatus 1`.

Die abgeschlossenen maschinellen Testlaeufe dauerten jeweils etwa
17 Sekunden. Sie erklaeren die vielen Modellanfragen nicht. Die
Review-Artefakte fordern nacheinander Korrekturen am lesenden SQLite-
Zugriff, an WAL-/SHM-Faellen und an konkurrierenden Datenbankkopien.
Das sind Implementierungsbeanstandungen. In den untersuchten
Claude-Toolfehlern ist kein Berechtigungsblocker als Ausloeser dieser
Korrekturfolge belegt. Die Ursache des frueheren allgemeinen
Reviewer-Exitfehlers ist daraus nicht bestimmbar.

Reproduktion ohne Modellaufruf (Claude-Sitzung f76a069d):

```bash
python scripts/analyze_claude_usage.py \
  ~/.claude/projects/-workspace/<SESSION_ID>.jsonl \
  --run-id uar-2-02
```

Die vom Nutzer beobachteten 80 % des Fuenfstundenkontingents sind
keine aus diesen Zaehlern berechenbare Groesse. Nicht im Transkript
sichtbare serverseitige Zusatzarbeit wird nicht geschaetzt.

## Fehler in der Orchestrierung

1. `worker_attempt` zaehlte CLI-Prozesse; der erste enthielt bereits
   47 Modellanfragen. Die erlaubten fuenf Korrekturrunden ermoeglichten
   sechs solche Bauaufrufe.
2. Jeder Aufruf setzte dieselbe Sitzung per `--resume` fort. Vor einem
   weiteren Aufruf wurde weder deren Kontextgroesse noch der bisherige
   Verbrauch geprueft.
3. Der Claude-Adapter verwendete Textausgabe, keine interne Turn- oder
   Kostengrenze und standardmaessig einen 900-Sekunden-Prozesstimeout.
4. Verbrauch und strukturierte Abbruchgruende kamen nicht im
   Laufcheckpoint an. Fehler wurden auf einen allgemeinen Exitstatus
   reduziert und konnten erneut ausgefuehrt werden.

## Korrektur und Reichweite

Die [Laufdokumentation](../ausfuehrer.de.md#verbrauchsschutz) beschreibt
die jetzt implementierten Schranken. Die Grenzen sind konservative,
konfigurierbare Betriebsvorgaben, keine aus dem Abo abgeleiteten Werte.

Ein neuer Loop-Aufruf begrenzt Claude intern, prueft vor Resume den
letzten nachgewiesenen Sitzungskontext, liest strukturierte Ergebnisse
beider Adapter und speichert Start, Ausgang und Verbrauch jedes
Agentenaufrufs. Fehler stoppen ohne automatischen Agenten-Retry.
Aufruf-, Token-, Claude-Kosten- und Korrekturgrenzen bleiben ueber
Neustarts erhalten. Ungeklaerter Verbrauch erlaubt keine weiteren
Aufrufe. Gleichzeitige Budgetreservierungen werden serialisiert.

Die Tokenbilanz wird an CLI-Schrittgrenzen geprueft; sie ist kein
exakter Tokenabbruch innerhalb einer laufenden Modellanfrage.
Codex hat hier eine Zeitgrenze, aber keine native Turn-/USD-Grenze.
Die Grenzen gelten pro Lauf, nicht fuer alle manuellen Sitzungen oder
andere gleichzeitig laufende Aufgaben desselben Abokontos.

Die Umsetzung wurde ohne kostenpflichtigen Echtlauf getestet. Der
bestehende Lauf und seine Scratch-Worktrees wurden nicht fortgesetzt
oder nachtraeglich als erfolgreich markiert. Ein alter Checkpoint
ohne Verbrauchsbilanz darf mit der neuen Laufsteuerung nicht blind
weiterarbeiten; alte installierte Codekopien erhalten die Aenderung
nicht automatisch.

Validierung: 605 Tests bestanden; Ruff fuer alle geaenderten
Python-Dateien ohne Befund. Ein zusaetzlicher Test gegen das echte
Transkript und mit einem gesperrten Prozess-Runner ergab
`Sitzungskontext 272413 >= Grenze 80000` bei **null CLI-Aufrufen**.
Die neuen Tests pruefen unter anderem sofortige Fehlerpause,
Cache-Bilanzierung, native Budgetargumente, persistierende Grenzen,
gleichzeitige Reservierungen und den Verbrauchsabgleich nach Abbruch.
