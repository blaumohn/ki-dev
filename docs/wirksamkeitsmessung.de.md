[← README](../README.md)

# Wirksamkeitsmessung (Plan)

**Frage:** Hält `implement` mit Review, Test-Tor und Entscheidungshalt
Abkürzungen von `main` fern, ohne ehrliche Arbeit unnötig anzuhalten?
Und was kostet das an Tokens?

**Grundlage:** [ImpossibleBench](https://arxiv.org/abs/2510.20270)
(Zhong, Raghunathan, Carlini; ICLR 2026) liefert jede Aufgabe in zwei
Fassungen: lösbar (Original) und unlösbar (ein Test widerspricht der
Aufgabe). In der unlösbaren Fassung belegt jeder grüne Lauf eine
Abkürzung. Code und Daten:
[safety-research/impossiblebench](https://github.com/safety-research/impossiblebench).
Das [Minimalbeispiel](../README.md#minimalbeispiel) ist eine solche
unlösbare Aufgabe im Kleinen.

## Aufbau

1. Je Aufgabe ein Wegwerf-Repo mit Auftrag (Bead) und Profil wie im
   Minimalbeispiel; die Tests der Aufgabe stehen als `[[tests]]` im
   Profil.
2. Zwei Varianten je Aufgabe: nur der Umsetzer in einer Sitzung
   (Übernahme bei grünen Tests) und `implement` mit Review, Test-Tor
   und Halt.
3. Zuerst der LiveCodeBench-Teil (103 kleine Aufgaben je Fassung); der
   SWE-bench-Teil folgt, weil jedes seiner Repos eine eigene
   Docker-Umgebung braucht.

## Kennzahlen

| Fassung | Kennzahl | Ziel |
|---|---|---|
| unlösbar | Anteil der Läufe mit Abkürzung auf `main` | niedrig |
| lösbar | Anteil der Läufe mit unnötigem Halt | niedrig |
| beide | Tokens je Aufgabe und Variante | bekannt |

Modelle und Versionen stehen fest
([`tool-versions.json`](../src/ki_dev/tool-versions.json)); ohne sie
sind Ergebnisse nicht vergleichbar.

## Begriff

„Kalibrierung“ meint in ki-dev den Abgleich von Tokenprognose und
Ist-Verbrauch
([Tokenmessung](architecture/tokenmessung-estimatoren.de.md)). Diese
Messung heißt deshalb Wirksamkeitsmessung.

## Stand

Geplant; es gibt noch kein Messskript und keine Ergebnisse
(Bead `ki-dev-ablauf-2pgc`).
