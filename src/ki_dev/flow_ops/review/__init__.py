"""Ops des Review-Musters (``flow/patterns/review.toml``).

Der Katalog nennt dieses Modul als ``ops`` aller Abläufe auf dem
Muster; ``ki-dev -f ABLAUF step`` holt sich hier mit :func:`step_ops`,
was die Zustandsarten des Musters für den Boten bedeuten: Schreiben
und Korrektur enden mit ``done``, das Review mit einem geprüften
Urteil, die Entscheidung mit ihrem Ereignis; der Vorlauf ist die
Katalogoperation ``checks.preflight``.
"""

from __future__ import annotations

from ki_dev.flow.model import Flow
from ki_dev.flow.review_flow import ReviewFlow
from ki_dev.flow_ops.review.step import ReviewOps


def step_ops(flow: Flow) -> ReviewOps:
    return ReviewOps(ReviewFlow(flow))
