"""Schichtrichtung: Ablauf → Ausführer → Adapter, nie rückwärts.

Geprüft wird die transitive Hülle der Importe im Quelltext (AST, auch
Importe innerhalb von Funktionen), nicht nur direkte Importe: ein
Umweg über ein Hilfsmodul ist ebenso eine Abhängigkeit.

- ``ki_dev.ablauf`` kennt weder Ausführer noch Adapter: Abläufe sind
  Daten, die nichts ausführen.
- ``ki_dev.adapter`` kennt weder Ausführer noch Ablauf: ein Adapter
  transportiert Eingabe und formale Ausgabe, mehr nicht.
- ``ki_dev.step`` projiziert den Planungsablauf auf einen Übergang und
  nutzt dafür Ablauf und Adapter, aber keinen Ausführer.
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


def _layer(prefix: str) -> list[str]:
    return sorted(m for m in MODULES if m.startswith(prefix))


@pytest.mark.parametrize(
    ("layer", "forbidden"),
    [
        ("ki_dev.ablauf", ("ki_dev.ausfuehrer", "ki_dev.adapter")),
        ("ki_dev.adapter", ("ki_dev.ausfuehrer", "ki_dev.ablauf")),
        ("ki_dev.step", ("ki_dev.ausfuehrer",)),
    ],
)
def test_layers_never_import_upwards(layer, forbidden):
    violations = {
        module: sorted(
            target
            for target in _closure(module)
            if target.startswith(forbidden)
        )
        for module in _layer(layer)
    }
    assert {m: v for m, v in violations.items() if v} == {}


def test_no_module_is_named_after_a_loop():
    """Die Schleife ist eine Rückkante im Ablauf, kein Modul."""
    assert [m for m in MODULES if "loop" in m.rsplit(".", 1)[-1]] == []
