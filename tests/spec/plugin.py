"""pytest-Plugin der Anforderungstests (``make spec-test``).

``pytest --spec`` führt nur Tests mit Marker ``requirement`` oder
``control`` aus und schreibt die Ergebnismatrix nach ``--spec-report``
(``report.json``, ``report.md``). Ohne ``--spec`` werden genau diese
Tests abgewählt: Anforderungstests dürfen rot sein und gehören weder in
``make test`` noch in ``make readme-check``. Der Lauf ist nur grün, wenn
jede Katalog-Anforderung ``passed`` ist und jede Kontrolle besteht.

Marker:
  ``requirement("ID")`` prüft die Anforderung ID aus dem Katalog
  (ini ``spec_catalog``); jede ID hat höchstens einen Test.
  ``control(target=..., expect=...)`` prüft den Testprüfer, nicht das
  Produkt: ``target`` ist eine Katalog-ID oder ``scaffold`` (das
  Prüfgerüst), ``expect`` der Status, den der geprüfte Fall ergibt.

Fixtures: ``evidence`` (Befehle, Beobachtungen), ``sandbox``
(isoliertes Repo ohne Anbieterstart, siehe ``sandbox.py``).
"""

from __future__ import annotations

import shlex
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.spec.evidence import Evidence
from tests.spec.report import (
    SCAFFOLD,
    SpecError,
    all_passed,
    checker_state,
    classify,
    clear_report,
    control_row,
    load_catalog,
    merge,
    read_revision,
    render,
    requirement_row,
    write_abort,
    write_report,
)
from tests.spec.sandbox import Sandbox
from tests.spec.schema import STATUSES

MARKERS = ("requirement", "control")
WRITTEN = (
    pytest.ExitCode.OK,
    pytest.ExitCode.TESTS_FAILED,
    pytest.ExitCode.NO_TESTS_COLLECTED,
)


def pytest_addoption(parser):
    group = parser.getgroup("spec", "Anforderungstests")
    group.addoption(
        "--spec",
        action="store_true",
        help="nur Anforderungstests und Kontrollen; Ergebnismatrix",
    )
    group.addoption(
        "--spec-report",
        default=".local/var/spec-test",
        help="Verzeichnis für report.json und report.md",
    )
    parser.addini(
        "spec_catalog",
        "Anforderungskatalog (TOML) relativ zum rootdir",
        default="tests/spec/requirements.toml",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "requirement(id): prüft eine Katalog-Anforderung"
    )
    config.addinivalue_line(
        "markers",
        "control(target, expect): prüft den Testprüfer, nicht das "
        "Produkt",
    )
    if config.getoption("spec"):
        config.pluginmanager.register(SpecSession(config))


def pytest_collection_modifyitems(config, items):
    wanted = config.getoption("spec")
    keep = [item for item in items if is_spec_item(item) == wanted]
    drop = [item for item in items if is_spec_item(item) != wanted]
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep


def is_spec_item(item) -> bool:
    return any(item.get_closest_marker(name) for name in MARKERS)


@pytest.fixture
def evidence():
    return Evidence()


@pytest.fixture
def sandbox(tmp_path, evidence):
    return Sandbox(tmp_path / "sandbox", evidence)


class SpecSession:
    """Sammelt Ergebnisse eines ``--spec``-Laufs und schreibt den
    Bericht."""

    def __init__(self, config):
        self.config = config
        root = config.rootpath
        self.directory = root / Path(config.getoption("spec_report"))
        clear_report(self.directory)
        try:
            self.catalog = load_catalog(
                root / config.getini("spec_catalog")
            )
        except SpecError as error:
            raise pytest.UsageError(str(error)) from error
        self.revision = read_revision(root)
        self.requirement_tests: dict[str, str] = {}
        self.controls: dict[str, tuple[dict, str]] = {}
        self.results: dict = {}
        self.evidence: dict[str, Evidence] = {}
        self.report: dict | None = None

    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(self, items):
        errors = [
            error
            for item in items
            if is_spec_item(item)
            for error in self._register(item)
        ]
        if errors:
            raise pytest.UsageError("\n".join(errors))

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self, item, call):
        report = yield
        if is_spec_item(item):
            self.results[item.nodeid] = merge(
                self.results.get(item.nodeid),
                classify(report, call.excinfo),
            )
            if "evidence" in (item.funcargs or {}):
                self.evidence[item.nodeid] = item.funcargs["evidence"]
        return report

    def pytest_sessionfinish(self, session):
        if session.exitstatus not in WRITTEN:
            write_abort(
                self.directory, session.exitstatus, self.revision
            )
            return
        self.report = self._build_report()
        write_report(self.directory, self.report)
        if not all_passed(self.report):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter):
        if self.report is None:
            return
        terminalreporter.section("Anforderungstests")
        terminalreporter.write(render(self.report))
        terminalreporter.write_line(
            f"Bericht: {self.directory}/report.md, report.json"
        )

    def _register(self, item) -> list[str]:
        requirement = item.get_closest_marker("requirement")
        control = item.get_closest_marker("control")
        where = item.nodeid
        if item.get_closest_marker("xfail"):
            return [f"{where}: xfail verdeckt den Status; entfernen"]
        if requirement and control:
            return [f"{where}: requirement und control zugleich"]
        if requirement:
            return self._register_requirement(where, requirement)
        return self._register_control(where, control, item)

    def _register_requirement(self, where, marker) -> list[str]:
        if len(marker.args) != 1 or marker.kwargs:
            return [f"{where}: requirement erwartet genau eine ID"]
        rid = marker.args[0]
        if rid not in self.catalog:
            return [f"{where}: Anforderung {rid!r} fehlt im Katalog"]
        if rid in self.requirement_tests:
            first = self.requirement_tests[rid]
            return [f"{where}: Anforderung {rid} schon von {first}"]
        self.requirement_tests[rid] = where
        return []

    def _register_control(self, where, marker, item) -> list[str]:
        target = marker.kwargs.get("target")
        expect = marker.kwargs.get("expect")
        errors = []
        if target != SCAFFOLD and target not in self.catalog:
            errors.append(f"{where}: Kontrollziel {target!r} unbekannt")
        if expect not in STATUSES:
            errors.append(f"{where}: expect {expect!r} unbekannt")
        if not errors:
            marker_data = {"target": target, "expect": expect}
            self.controls[where] = (marker_data, _description(item))
        return errors

    def _build_report(self) -> dict:
        controls = [
            control_row(
                nodeid,
                marker,
                description,
                self.results.get(nodeid),
                self.evidence.get(nodeid),
            )
            for nodeid, (marker, description) in self.controls.items()
        ]
        return {
            "generated": _now(),
            "invocation": shlex.join(
                ["pytest", *self.config.invocation_params.args]
            ),
            "revision": self.revision,
            "requirements": [
                self._requirement(rid, entry, controls)
                for rid, entry in self.catalog.items()
            ],
            "controls": controls,
        }

    def _requirement(self, rid, entry, controls) -> dict:
        nodeid = self.requirement_tests.get(rid)
        statuses = [c["status"] for c in controls if c["target"] == rid]
        return requirement_row(
            rid,
            entry,
            nodeid,
            self.results.get(nodeid),
            self.evidence.get(nodeid),
            checker_state(statuses),
            self.revision,
        )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _description(item) -> str:
    doc = (item.obj.__doc__ or "").strip()
    return doc.splitlines()[0] if doc else item.name
