"""Eingesteckte Operationen der Abläufe.

Ein Ablauf deklariert eine Operation mit Namen (``operation = [{ do =
"checks" }]``) und bindet sie an einen Katalognamen
(``[op.checks]``, ``do = "checks.preflight"``); ein Paket hier setzt
sie um. Der Aufrufer steckt die Umsetzung beim Start in den
Ausführer. ``ops`` importiert weder
Ausführer (``runner``) noch Adapter (``adapter``, ``step``).
Kontextquellen für Übergaben (kein Operationsname) liegen in
``ops.context``.
"""
