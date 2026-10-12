"""Gemeinsame Optionen der Ablaufpakete (Gerüst, nicht Paket).

``--adapter [ROLLE=]NAME`` ist nicht ablaufabhängig: jedes Paket bindet
die Option ein und reicht die Werte an
:func:`ki_dev.flow_ops.implement.cli.adapter_overrides`, das sie prüft.
"""

from __future__ import annotations

from typing import Annotated

import typer

ADAPTER_OPTION = Annotated[
    list[str] | None,
    typer.Option(
        "--adapter",
        metavar="[ROLLE=]NAME",
        help="Executor je Rolle (worker, review) ersetzen; ohne Rolle "
        "alle. NAME: ein Executor ohne Sitzungsangaben, z. B. manual "
        "(stdout/stdin), inbox oder mock. Bei resume nur für diesen "
        "Aufruf.",
    ),
]
