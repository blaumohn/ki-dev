"""Ablaufpaket finden: ``ki-dev -f NAME`` sucht wie ``make -f``.

Reihenfolge, die erste Fundstelle gilt und wird angezeigt:

1. ``NAME`` mit ``/`` oder Endung ``.toml``: genau diese Datei.
2. ``./NAME.toml`` im aktuellen Verzeichnis.
3. Die Verzeichnisse aus ``KI_DEV_FLOW_PATH`` (``:``-getrennt wie
   ``PATH``).
4. Das mitgelieferte Paket ``ki_dev/flow/NAME.toml``.

Gelesen wird hier der Ort; Laden und Prüfen übernimmt
:func:`~ki_dev.flow.model.load_flow_file`. :func:`import_ops` lädt die
Ops eines Ablaufs: ``ops = "./PFAD"`` relativ zur Ablaufdatei (Datei
oder Python-Paketverzeichnis), sonst ein importierbarer Modulname.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from collections.abc import Mapping
from importlib import import_module
from importlib.resources import as_file, files
from pathlib import Path
from types import ModuleType

from ki_dev.config_sources import ConfigSource
from ki_dev.flow.model import Flow, FlowError

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


def import_ops(flow: Flow) -> ModuleType:
    """Ops-Modul des Ablaufs; ein fehlendes ist ein Fehler, ein
    Rückfall auf das Gerüst findet nicht statt."""
    if flow.ops is None:
        raise FlowError(f"{flow.name}.toml: kein ops-Modul")
    try:
        if flow.ops.startswith("./"):
            return _import_local(flow.ops, Path(str(flow.root)))
        return import_module(flow.ops)
    except ImportError as exc:
        raise FlowError(
            f"{flow.name}.toml: ops-Modul {flow.ops} nicht ladbar "
            f"({exc})"
        ) from exc


def _import_local(ops: str, root: Path) -> ModuleType:
    """``./DATEI`` (``DATEI.py``) oder ``./PAKET[/MODUL…]``: das
    Paketverzeichnis wird unter einem eigenen Namen je Ort geladen,
    damit relative Importe darin gelten und zwei Orte sich nicht
    überdecken; Module darin dann über diesen Namen."""
    head, *rest = ops.removeprefix("./").split("/")
    path = (root / head).resolve()
    digest = hashlib.sha256(str(path).encode()).hexdigest()[:12]
    name = f"ki_dev_ops_{digest}"
    if name not in sys.modules:
        _load(name, path, package=bool(rest) or path.is_dir())
    return import_module(".".join((name, *rest)))


def _load(name: str, path: Path, *, package: bool) -> None:
    if package:
        init = path / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            name, init, submodule_search_locations=[str(path)]
        )
    else:
        init = path.with_suffix(".py")
        spec = importlib.util.spec_from_file_location(name, init)
    if spec is None or spec.loader is None or not init.is_file():
        raise ImportError(f"{init} fehlt")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
