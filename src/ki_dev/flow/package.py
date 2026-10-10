"""Ablaufpaket finden: ``ki-dev -f NAME`` sucht wie ``make -f``.

Reihenfolge, die erste Fundstelle gilt und wird angezeigt:

1. ``NAME`` mit ``/`` oder Endung ``.toml``: genau diese Datei.
2. ``./NAME.toml`` im aktuellen Verzeichnis.
3. Die Verzeichnisse aus ``KI_DEV_FLOW_PATH`` (``:``-getrennt wie
   ``PATH``).
4. Das mitgelieferte Paket ``ki_dev/flow/NAME.toml``.

Gelesen wird hier nur der Ort; Laden und Prüfen übernimmt
:func:`~ki_dev.flow.model.load_flow_file`.
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib.resources import as_file, files
from pathlib import Path

from ki_dev.config_sources import ConfigSource
from ki_dev.flow.model import FlowError

SEARCH_ENV = "KI_DEV_FLOW_PATH"
SUFFIX = ".toml"
CONFIG_SOURCE = ConfigSource(
    "-f NAME",
    f"./NAME{SUFFIX}, ${SEARCH_ENV}, mitgeliefert (ki_dev/flow)",
)


def find_flow(
    name: str, cwd: Path, environ: Mapping[str, str]
) -> Path:
    """Pfad der Ablaufdatei zu ``name``; sonst :class:`FlowError` mit
    allen geprüften Orten."""
    if "/" in name or name.endswith(SUFFIX):
        path = cwd / name
        if not path.is_file():
            raise FlowError(f"Ablaufdatei fehlt: {path}")
        return path
    candidates = [cwd / f"{name}{SUFFIX}"]
    candidates += [
        Path(part) / f"{name}{SUFFIX}"
        for part in environ.get(SEARCH_ENV, "").split(":")
        if part
    ]
    for path in candidates:
        if path.is_file():
            return path
    shipped = _shipped(name)
    if shipped is not None:
        return shipped
    tried = ", ".join(str(path) for path in candidates)
    raise FlowError(
        f"Ablauf {name} nicht gefunden (geprüft: {tried}, "
        f"mitgeliefert)"
    )


def _shipped(name: str) -> Path | None:
    resource = files("ki_dev.flow").joinpath(f"{name}{SUFFIX}")
    if not resource.is_file():
        return None
    # Installierte Pakete liegen als Dateien vor (pipx, venv).
    with as_file(resource) as path:
        return Path(path)
