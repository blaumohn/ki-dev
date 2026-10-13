"""Wächter des gemeinsamen Review-Katalogs
(``flow/patterns/review.toml``).

Der Katalog nutzt sie an der Kante ``review --PASS-->`` der Variante
mit Vorlauf: kein PASS nach Teillauf (``full_checks``). Er liest die
Tatsachen des Vorlaufs (``facts``); die Kante deklariert sie als
Eingabe aus dem Vorlauf.
"""

from __future__ import annotations

from ki_dev.runner.protocol import RunModel

FULL_CHECKS = "full_checks"
FACTS = "facts"


class ReviewModel(RunModel):
    def full_checks(self) -> bool:
        """Der letzte Vorlauf lief vollständig (kein Teillauf)."""
        return FULL_CHECKS in (self.data.get(FACTS) or ())
