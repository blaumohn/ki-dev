"""Schichtrichtung: Ablauf → Ausführer → Adapter, nie rückwärts.

Geprüft wird die transitive Hülle der Importe im Quelltext (AST, auch
Importe innerhalb von Funktionen), nicht nur direkte Importe: ein
Umweg über ein Hilfsmodul ist ebenso eine Abhängigkeit.

- ``ki_dev.flow`` kennt weder Ausführer noch Adapter: Abläufe sind
  Daten, die nichts ausführen.
- ``ki_dev.adapter`` kennt weder Ausführer noch Ablauf: ein Adapter
  transportiert Eingabe und formale Ausgabe, mehr nicht.
- ``ki_dev.step`` ist die Projektion des Ausführers mit dem Adapter
  manual: es nutzt ``ki_dev.runner`` (den einen Ausführer), der
  Ausführer kennt step nie; Maschinenoperationen reicht step als
  Bindung herein.
- ``ki_dev.ops`` setzt deklarierte Operationen um (``checks``) und
  liefert Kontextquellen (``context``: Bead-Eingabe, Leitlinien,
  Grenzen, Beads-Leser); es kennt weder Ausführer noch Adapter noch
  step: eingesteckt wird es von außen.
- ``ki_dev.flow_ops`` setzt die Ablaufpakete zusammen (``ops`` eines
  Ablaufs): es nutzt Ausführer, Ops-Bausteine und Adapter; keine
  andere Schicht und kein Kernmodul kennt es.
- Kernmodule außerhalb der Schichten (Deltas, Verbrauch, Nachweise)
  kennen weder Ausführer noch ``step`` noch die Kommandozeile; ein
  Modul, das nur eine Schicht nutzt, liegt in dieser Schicht.
- Kein Importzyklus, auch nicht über ``TYPE_CHECKING`` oder lokale
  Importe (die AST-Analyse sieht beide).
"""

from __future__ import annotations

import ast
from functools import cache
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"


def _module_name(path: Path) -> str:
    parts = path.relative_to(SRC).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


MODULES = {
    _module_name(path): path for path in (SRC / "ki_dev").rglob("*.py")
}


@cache
def _direct(module: str) -> frozenset[str]:
    path = MODULES[module]
    package = (
        module
        if path.name == "__init__.py"
        else module.rpartition(".")[0]
    )
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: len(anchor) - node.level + 1]
                base = ".".join([*anchor, base] if base else anchor)
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return frozenset(name for name in found if name in MODULES)


def _closure(module: str) -> set[str]:
    seen: set[str] = set()
    pending = [module]
    while pending:
        current = pending.pop()
        for target in _direct(current) - seen:
            seen.add(target)
            pending.append(target)
    return seen


def _within(module: str, packages: str | tuple[str, ...]) -> bool:
    """Modul gehört zu einem der Pakete (``ki_dev.flow_ops`` gehört
    nicht zu ``ki_dev.flow``)."""
    if isinstance(packages, str):
        packages = (packages,)
    return any(
        module == package or module.startswith(f"{package}.")
        for package in packages
    )


def _layer(prefix: str) -> list[str]:
    return sorted(m for m in MODULES if _within(m, prefix))


@pytest.mark.parametrize(
    ("layer", "forbidden"),
    [
        ("ki_dev.flow", ("ki_dev.runner", "ki_dev.adapter")),
        ("ki_dev.adapter", ("ki_dev.runner", "ki_dev.flow")),
        ("ki_dev.runner", ("ki_dev.step", "ki_dev.ops")),
        (
            "ki_dev.ops",
            ("ki_dev.runner", "ki_dev.adapter", "ki_dev.step"),
        ),
    ],
)
def test_layers_never_import_upwards(layer, forbidden):
    violations = {
        module: sorted(
            target
            for target in _closure(module)
            if _within(target, forbidden)
        )
        for module in _layer(layer)
    }
    assert {m: v for m, v in violations.items() if v} == {}


def test_no_module_is_named_after_a_loop():
    """Die Schleife ist eine Rückkante im Ablauf, kein Modul."""
    assert [m for m in MODULES if "loop" in m.rsplit(".", 1)[-1]] == []


@pytest.mark.parametrize(
    "parked", ["ki_dev.pilot", "ki_dev.safety_profile"]
)
def test_parked_packages_are_not_wired_yet(parked):
    """Abgelegte Pakete künftiger Features (urq, wu0.10.5): das übrige
    Paket nutzt sie noch nicht; die Anbindung ist eigene Arbeit."""
    users = sorted(
        module
        for module in MODULES
        if not _within(module, parked)
        and any(_within(target, parked) for target in _direct(module))
    )
    assert users == []


_LAYERS = (
    "ki_dev.flow_ops",
    "ki_dev.runner",
    "ki_dev.step",
    "ki_dev.flow",
    "ki_dev.adapter",
    "ki_dev.pilot",
    "ki_dev.safety_profile",
    "ki_dev.beads_journal",
)
_TOP = {"ki_dev", "ki_dev.cli", "ki_dev.config_cli"}
_UPPER = (
    "ki_dev.flow_ops",
    "ki_dev.runner",
    "ki_dev.step",
    "ki_dev.cli",
    "ki_dev.config_cli",
)


def test_core_modules_never_import_runner_step_or_cli():
    core = [
        m
        for m in MODULES
        if not _within(m, _LAYERS) and m not in _TOP
    ]
    violations = {
        module: sorted(
            t for t in _closure(module) if _within(t, _UPPER)
        )
        for module in core
    }
    assert {m: v for m, v in violations.items() if v} == {}


def test_no_import_cycles():
    """Ein Modul erreicht sich über seine Importe nie selbst."""
    assert sorted(m for m in MODULES if m in _closure(m)) == []


def test_generic_package_runner_knows_no_roles_or_catalog():
    """Der generische Runner kennt Bindungen, keinen Fachkatalog."""
    forbidden = (
        "ki_dev.adapter",
        "ki_dev.flow_ops.implement.ops",
        "ki_dev.flow_ops.implement.machine",
        "ki_dev.flow_ops.implement.runtime",
    )
    assert not [
        m
        for m in _closure("ki_dev.runner.package")
        if _within(m, forbidden)
    ]


# --- Grenze Gerüst/Paket ----------------------------------------------

# Gerüstwörter, die auch als Rolle oder Zustandsart vorkommen: review
# ist Modus von ``--step review``, Zustandsart des Review-Katalogs und
# Schlüssel der Leitlinienquelle; source und finished sind Zustände des
# gemeinsamen Katalogs.
_FRAMEWORK_WORDS = {"review", "source", "finished"}
# Bedienvorgaben der CLI mit Begründung (``ki_dev.step``): Vorgabe von
# ``--step review`` und die Form ``ki-dev step map --agent`` des
# Sitzungsimports.
_ALLOWED = {
    ("ki_dev.step.choices", "implement"),
    ("ki_dev.step.forms", "map"),
}


def _package_words() -> set[str]:
    """Ablauf-, Phasen- und Rollennamen der mitgelieferten Pakete und
    ihre zusammengesetzten Zustandsnamen (``worker_step``,
    ``map.review``), aus den Abläufen selbst gelesen. Einfache
    Zustandswörter wie ``start`` oder ``error`` sind kein
    Paketwissen."""
    from ki_dev.flow.model import load_flow
    from ki_dev.flow.review_flow import review_flow_files

    words: set[str] = set(review_flow_files())
    for path in (SRC / "ki_dev" / "flow").glob("*.toml"):
        flow = load_flow(path.stem)
        words.add(flow.name)
        words |= {s for s in flow.states if "_" in s or "." in s}
        words |= {
            b.role for b in flow.bindings.values() if b.role is not None
        }
    return words - _FRAMEWORK_WORDS


def _literals(module: str) -> set[str]:
    """Zeichenketten im Code eines Moduls, ohne Docstrings."""
    path = SRC / Path(*module.split("."))
    if path.is_dir():
        path = path / "__init__.py"
    else:
        path = path.with_suffix(".py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node,
            (
                ast.Module,
                ast.ClassDef,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docs
    }


@pytest.mark.parametrize(
    "layer", ["ki_dev.runner", "ki_dev.ops", "ki_dev.step"]
)
def test_framework_knows_no_package_names(layer):
    """Das Gerüst kennt keine Rollen- und Phasennamen; sie stehen nur
    als Daten in den Abläufen (Paket → Gerüst, nie umgekehrt)."""
    words = _package_words()
    found = {
        (module, value)
        for module in _layer(layer)
        for value in _literals(module)
        if value in words or value.partition(".")[0] in words
    }
    assert found - _ALLOWED == set()


def test_package_words_cover_phases_roles_and_flows():
    """Die Prüfung oben greift: Phasen, Rollen und Abläufe stehen in
    der Wortliste, Gerüstwörter nicht."""
    words = _package_words()
    assert {"map", "implement", "implement_review", "worker"} <= words
    assert {"worker_step", "map.review"} <= words
    assert not words & _FRAMEWORK_WORDS
