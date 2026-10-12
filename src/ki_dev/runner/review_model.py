"""Wächter des gemeinsamen Review-Katalogs
(``flow/patterns/review.toml``).

Der Katalog nutzt sie an der Kante ``review --PASS-->`` der Variante
mit Vorlauf: kein PASS nach Teillauf (``full_checks``) und nur auf dem
geprüften Stand (``unchanged``). Sie lesen die Laufdaten, die der
Vorlauf und die Antwort liefern: ``facts`` (Tatsachen des Vorlaufs),
``checked`` (geprüfter Stand) und ``current`` (Stand bei der Antwort).
"""

from __future__ import annotations

from ki_dev.runner.protocol import RunModel

FULL_CHECKS = "full_checks"
FACTS = "facts"
CHECKED = "checked"
CURRENT = "current"


class ReviewModel(RunModel):
    def full_checks(self) -> bool:
        """Der letzte Vorlauf lief vollständig (kein Teillauf)."""
        return FULL_CHECKS in (self.data.get(FACTS) or ())

    def unchanged(self) -> bool:
        """Geprüfter und aktueller Stand sind bekannt und gleich."""
        checked = self.data.get(CHECKED)
        current = self.data.get(CURRENT)
        return (
            checked is not None
            and current is not None
            and checked == current
        )
