---
layout: page
title: Programmierleitlinien
permalink: /de/policies/programmierleitlinien/
---

Diese Leitlinien sollen Code für Review, Wartung und Betrieb klar machen.

## Automatisierte Prüfung

Automatisierbare Stil- und Qualitätsregeln werden in Linter-Konfigurationen
gepflegt, nicht in dieser Leitlinie dupliziert.

Als kompaktes Vorbild für die Art der Stilprüfung dient die
[Pylint-Konfiguration in `lebenslauf-web-vorlage`](https://github.com/blaumohn/lebenslauf-web-vorlage/blob/main/.pylintrc).

Die konkreten Werkzeuge und Werte werden je Repo in den jeweiligen
Linter-Konfigurationen gepflegt.

## Fachliche Stilregeln

Die Regeln gelten für handgeschriebenen Quelltext. Erzeugte Dateien werden
gekennzeichnet und neu erzeugt; übernommener Fremdcode wird getrennt gepflegt.
Die Belege zeigen jeweils das genannte Prinzip. `…` kennzeichnet Auslassungen.

### Funktionen haben eine Aufgabe
{: .policy-subtitle }

- Jede Funktion hat eine klar benennbare Aufgabe; ihr Name beschreibt diese.
- Ablaufsteuerung ruft Teilaufgaben auf, deren Einzelheiten in eigenen
  Funktionen stehen.

**Beispiel – C++ Core Guidelines:**

```cpp
void read_and_print()
{
    auto x = read(cin);
    print(cout, x);
}
```

[Beleg: F.2 – eine logische Operation je Funktion](https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines#Rf-logical).

### Programmfluss bleibt von oben nach unten lesbar
{: .policy-subtitle }

- Zweck und Hauptfluss stehen vor Einzelheiten; Hilfsfunktionen folgen möglichst
  in Aufrufreihenfolge. Sprachvorgaben und feste Projektkonventionen gehen vor.
- Einzelheiten, die den Hauptfluss verdecken, werden ausgelagert. Reine
  Umordnung braucht einen konkreten Nutzen für das Verständnis.

**Beispiel – Uber Go Style Guide, gekürzt:**

```go
func (s *something) Cost() {
    return calcCost(s.weights)
}
…
func calcCost(n []int) int {…}
```

[Beleg: Function Grouping and Ordering](https://github.com/uber-go/guide/blob/master/style.md#function-grouping-and-ordering).

### Fallbacks verdecken keine Fehler
{: .policy-subtitle }

- Ein Ersatzpfad ist nur für einen ausdrücklich benannten, fachlich gültigen
  und getesteten Anlass zulässig.
- Fehlende Pflichtwerte, ungültige Zustände und unerwartete Fehler bleiben
  sichtbar; sie werden nicht durch Standardwerte in scheinbaren Erfolg verwandelt.
- Ersatzpfade ohne gültigen fachlichen Anlass werden entfernt.

**Beispiel – Go-Standardbibliothek, gekürzt; Kommentar übersetzt:**

```go
func handleCopyFileRangeErr(err error, copied, written int64) (bool, error) {
    switch err {
    case syscall.ENOSYS:
        // Bei ENOSYS wurden sicher keine Daten übertragen.
        // Wir melden dem Aufrufer, dass wir die Übertragung
        // nicht ausführen konnten, damit er auf ein
        // allgemeineres Verfahren zurückgreifen kann.
        return false, nil
    …
    }
    return true, err
}
```

[Beleg: handleCopyFileRangeErr – ENOSYS-Zweig](https://go.dev/src/internal/poll/copy_file_range_linux.go).

### Fehler werden nicht pauschal geschluckt
{: .policy-subtitle }

- Nur konkret erwartete Fehler behandeln; alle übrigen weitergeben oder erneut
  werfen. Das gilt für Fehlerwerte ebenso wie für Ausnahmen.
- An einer zentralen Programmgrenze darf ein Fehler gemeldet und die Operation
  erfolglos beendet werden. Ein Fehler darf nicht als Erfolg zurückkehren.

**Beispiel – LLVM, gekürzt:**

```cpp
if (auto Err = handleErrors(processFormattedFile(...), …))
    return Err;
```

`handleErrors` gibt Fehler zurück, für die kein passender Handler vorliegt.
[Beleg: Recoverable Errors](https://llvm.org/docs/ProgrammersManual.html#recoverable-errors).

### Funktionen und Dateien bleiben überschaubar
{: .policy-subtitle }

- Aufgabe, Verzweigungen und Fehlerpfade einer Funktion müssen gemeinsam
  verständlich bleiben. Tiefe Verschachtelung wird vereinfacht.
- Jede Datei bündelt eine zusammenhängende Zuständigkeit. Ab einigen hundert
  Zeilen werden ihre Aufgabenbereiche und Abstraktionsebenen ausdrücklich geprüft.
- **Senkrechter Schnitt:** Einzelheiten unterhalb des Hauptflusses in eigene
  Dateien auslagern; der Hauptfluss behält die Ablaufsteuerung.
- **Waagerechter Schnitt:** Gleichrangige Aufgabenbereiche auf eigene Dateien
  verteilen, auch innerhalb desselben Moduls.
- Nach Zuständigkeit teilen, nicht nach Zeilenzahl. Bleibt eine Datei lang,
  wird begründet, weshalb eine weitere Trennung das Verständnis verschlechtern würde.
- Umfangreiche Daten aus dem Programmcode auslagern; notwendige Datentabellen
  nach ihrem Inhalt gliedern.

**Parnas (1972), sinngemäß:** Module verbergen schwierige oder voraussichtlich
veränderliche Entwurfsentscheidungen vor anderen Modulen.
[On the Criteria To Be Used in Decomposing Systems into Modules](https://dl.acm.org/doi/10.1145/361598.361623).

**Beispiel – CPython:** Aus der zur Aufteilung vorgesehenen, 16.683 Zeilen langen
`Objects/unicodeobject.c` wurde die Zeichenketten-Erzeugung mit
`PyUnicodeWriter` und `_PyUnicodeWriter` nach `Objects/unicode_writer.c`
ausgelagert.
[Anlass: #139353](https://github.com/python/cpython/issues/139353) ·
[Umgesetzte Trennung: #139911](https://github.com/python/cpython/pull/139911).

### Modulgrenzen machen Abhängigkeiten ausdrücklich
{: .policy-subtitle }

- Fachliche Berechnungen erhalten ihre Eingaben ausdrücklich; Dateien,
  Umgebungsvariablen und veränderlicher globaler Zustand werden an benannten
  Ein- und Ausgabegrenzen gelesen.
- Neue Abhängigkeiten und Schnittstellenänderungen werden geprüft.
  Hilfsmodule dürfen keine verdeckte Rückkopplung zum aufrufenden Modul schaffen.

**Beispiel – rust-analyzer:** Der Analysekern erhält Quelltexte und
Projektstruktur als Daten im Speicher und führt selbst keine Ein- oder Ausgabe aus.
[Beleg: Architecture – Bird’s Eye View](https://rust-analyzer.github.io/book/contributing/architecture.html#birds-eye-view).

### Ressourcen werden auch bei frühem Verlassen freigegeben
{: .policy-subtitle }

- Nach erfolgreichem Erwerb die Freigabe unmittelbar absichern, etwa durch
  RAII, `defer` oder `finally`; auch bei früher Rückgabe und Fehlern.
- Fehler bei der Freigabe sichtbar behandeln, ohne einen ursprünglichen Fehler
  unbemerkt zu ersetzen.

**Beispiel – Uber Go Style Guide, gekürzt:**

```go
p.Lock()
defer p.Unlock()
…
```

[Beleg: Defer to Clean Up](https://github.com/uber-go/guide/blob/master/style.md#defer-to-clean-up).

### Tests prüfen Fehler- und Ersatzpfade gezielt
{: .policy-subtitle }

- Für jeden Ersatzpfad den erlaubten Anlass und einen ähnlich aussehenden,
  unzulässigen Fehlerfall prüfen.
- Beobachtbares Verhalten prüfen; interne Umordnung allein darf Tests nicht brechen.
- Testdaten auf den geprüften Fall beschränken und äußere Einflüsse wie Zeit
  und Dateizugriffe kontrollieren.

**Beispiel – rust-analyzer:** Parser-Tests vergleichen kurze Rust-Eingaben mit
zugehörigen erwarteten Syntaxbäumen.
[Beleg: Architecture – crates/syntax](https://rust-analyzer.github.io/book/contributing/architecture.html#cratessyntax).

## Tests & Sicherheit

- Passende Linting- und Testprüfungen müssen erfolgreich laufen, bevor eine
  Änderung als erledigt gilt.
- Tests dort ergänzen, wo Fehler teuer wären (Parsing, I/O, Deploy-Pfade).
- Secrets nie in Logs oder Doku.
- Öffentliche Doku: keine Jira-Cloud-Links und keine personenbezogenen Daten.

## Dokumentation im Code

- Öffentliche Erklärungen in GitHub Pages.
- Runbooks für Schrittfolgen (Betrieb/Wartung/Störung).
- Entscheidungen als ADRs, Vorschläge als KEP-Lite.

## PHPDoc / Docstrings

### Docstrings nur für das, was PHP nicht selbst ausdrücken kann
{: .policy-subtitle }

- PHP drückt Parametertypen, Rückgabetypen, Property-Typen, `readonly`,
  `enum`, `mixed`, `never` und Vereinigungstypen (z. B. `string|false`)
  bereits nativ aus. Eine Docstring, die nur diese Typen wiederholt, entfällt.
- Docstrings sind dort empfohlen, wo PHPs Typsystem an seine Grenzen stößt,
  etwa bei Array-Formen oder eingeschränkten Skalartypen. Die Notation folgt
  PHPStan (Repo-Linter, siehe „Automatisierte Prüfung"), damit die Angaben
  auch tatsächlich geprüft werden, nicht nur als Prosa im Kommentar stehen:
  ```php
  /** @return list<string> */
  public function files(): array { ... }

  /** @param non-empty-string $path */
  public function load(string $path): Config { ... }

  /** @return array<string, mixed> */
  public function toArray(): array { ... }
  ```
- Erklärender Fließtext-Kommentar zu Klassen/Methoden entfällt, wenn Name und
  Struktur den Zweck bereits klar machen.
