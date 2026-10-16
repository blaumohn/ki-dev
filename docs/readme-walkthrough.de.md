# README-Durchlauf (Cognitive Walkthrough)

Prüft, ob das README einen Leser bis zu einer Entscheidung trägt. Kein
Software-Test: ein Mensch oder ein Agent spielt die Personas nach und
notiert je Schritt, was er sieht, welchen Eindruck er hat und was er tut
(weiterlesen, klicken, schließen).

## Personas

| Persona | Zeit | Ziel | Entscheidung |
| --- | --- | --- | --- |
| Tech-Lead sichtet eine Bewerbung | 60 s | Kann die Person Systeme bauen? | zum Gespräch einladen oder nicht |
| Entwickler sucht ein Werkzeug | 5 min | Löst es mein Problem, läuft es bei mir? | ausprobieren oder nicht |
| KI-Agent im Repo | ein Lesedurchgang | Wo stehen Ablauf, Befehle, Stand? | richtige Datei öffnen |

## Schritte

1. Dateiliste auf GitHub (Root): Was fällt auf, bevor das README sichtbar ist?
2. Zeilen 1–15 (5-Sekunden-Test): siehe Bestehenskriterium.
3. Erster Link, den die Persona klicken würde: führt er zu dem, was der
   Linktext verspricht?
4. Erster Shell-Block: versteht man den Ablauf, ohne die Prosa zu lesen?
5. Erste negative Aussage: Wo steht sie, und wie wirkt sie an dieser Stelle?
6. Ende des Pfads: Welche Entscheidung trifft die Persona, nach wie vielen Zeilen?

## Bestehenskriterium

Nach den Zeilen 1–15 beantwortet jede Persona:

- Was ist das?
- Für wen?
- Was ist anders als bei einem Prompt-Skript?
- Wie probiere ich es aus?

Bestanden bei 4 von 4. Dazu: keine negative Aussage ohne Einordnung in den
ersten 15 Zeilen, kein Verweis ins Leere (z. B. Bead-ID ohne Link).

## Protokoll

| Datum | Persona | Entscheidung nach Zeile | 4 Fragen | Befund |
| --- | --- | --- | --- | --- |
| 2026-10-16 | Tech-Lead | 25 (schließt) | 1,5 / 4 | Review-Gate-Lücke im ersten Bildschirm, Demo erst ab Zeile 82 |
