"""Lauf-Konfiguration und Befehle des Ausführers für ``implement``.

Ein Profil (TOML) beschreibt Grenzen, Prüfungen, Finalisierung und je
Rolle den Adapter: ``claude`` oder ``codex`` (vorbereitete
Agentensitzung), ``manual`` (Mensch als Bote) oder ``mock``
(vorgegebene Antworten, ohne Anbieterzugang). Den Auftrag (``task``,
``acceptance_criteria``, ``sources``) setzt der Aufrufer aus dem Bead
ein; das Profil darf ihn nicht enthalten.
"""

from __future__ import annotations

import json
import sys
import tomllib
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import cast

from ki_dev.adapter import manual, mock
from ki_dev.adapter.agent import (
    AgentReviewer,
    AgentWorker,
)
from ki_dev.adapter.contract import (
    RunTask,
)
from ki_dev.adapter.executors import (
    Effort,
    Executor,
    ExecutorSpec,
    build_executor,
    cli_transports,
)
from ki_dev.adapter.executors.contract import TurnBudget
from ki_dev.adapter.registry import executor_specs
from ki_dev.config_sources import ConfigSource
from ki_dev.repository_evidence import (
    CheckCommand,
    RepositoryEvidenceCollector,
)
from ki_dev.repository_finalization import RepositoryFinalizer
from ki_dev.review_context import ProjectionLimits
from ki_dev.run_store import RunStore
from ki_dev.runner.machine import IMPLEMENT, Limits
from ki_dev.runner.runtime import (
    RunResult,
    RunRuntime,
    read_run_status,
)
from ki_dev.runner.safety import SafetyLimits
from ki_dev.usage_accounting import metadata

# Profile liegen je Projekt unter .ki-dev/profiles/NAME.toml; ohne
# --profile gilt NAME = default.
PROFILE_DIR = Path(".ki-dev/profiles")
DEFAULT_PROFILE = "default"
CONFIG_SOURCE = ConfigSource(
    "-f implement",
    "--profile NAME → .ki-dev/profiles/NAME.toml",
    path=PROFILE_DIR / f"{DEFAULT_PROFILE}.toml",
)
# Felder des Auftrags: kommen vom Aufrufer (Bead), nie aus dem Profil.
TASK_FIELDS = frozenset({"task", "acceptance_criteria", "sources"})
# Rollen des Laufprofils; jede wählt einen Executor.
ROLES = ("worker", "review")


class RunConfigError(ValueError):
    """Die Laufkonfiguration ist ungültig."""


# Hülle um den Executor einer Rolle (z. B. Live-Ansicht); der Aufrufer
# steckt sie ein, der Ausführer kennt keine Anzeige.
ExecutorWrap = Callable[[Executor, str], Executor]


def _unwrapped(executor: Executor, role: str) -> Executor:
    del role
    return executor


def profile_path(name: str, cwd: Path) -> Path:
    """``NAME`` → ``.ki-dev/profiles/NAME.toml``; ein Wert mit ``/``
    oder Endung ``.toml`` ist der Pfad selbst."""
    if "/" in name or name.endswith(".toml"):
        return cwd / name
    return cwd / PROFILE_DIR / f"{name}.toml"


def load_profile(path: Path) -> dict[str, object]:
    """Profil lesen; Auftragsfelder darin sind ein Fehler."""
    try:
        profile = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RunConfigError(
            f"Profil {path} nicht lesbar: "
            f"{exc.strerror or type(exc).__name__}"
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise RunConfigError(
            f"Profil {path}: kein gültiges TOML ({exc})"
        ) from exc
    task_fields = sorted(TASK_FIELDS & set(profile))
    if task_fields:
        raise RunConfigError(
            f"Profil {path}: Auftragsfelder {task_fields} kommen aus "
            "dem Bead, nicht aus dem Profil"
        )
    return profile


def start_run(
    config: dict[str, object],
    *,
    run_id: str | None,
    runs_dir: Path,
    wrap: ExecutorWrap = _unwrapped,
) -> RunResult:
    """Neuen Lauf aus Profil und Auftrag (ein Objekt) starten."""
    config = dict(config)
    # Effektive Defaults bleiben ueber Upgrades nachvollziehbar.
    for role in ROLES:
        values = _required_object(config, role)
        spec = executor_specs().get(cast(str, values.get("executor")))
        if spec is not None and not _has_session(spec):
            continue
        config[role] = {
            **values,
            "budget": asdict(_turn_budget(values.get("budget", {}))),
        }
    actual_run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
    task = _task(config, actual_run_id)
    usage_task = _usage_task(config)
    limits = _limits(config.get("limits", {}))
    projection = _projection(config.get("projection_limits", {}))
    with _runtime(
        config, RunStore(runs_dir, actual_run_id), projection, wrap
    ) as runtime:
        return runtime.start(
            task,
            limits,
            manifest_extra={
                "configuration": config,
                # Nur bei explizit konfigurierter Aufgabenbindung; sonst
                # bleibt die Zurechnung sichtbar unvollstaendig
                # (attribution_missing) statt geraten zu werden.
                **(
                    {"usage_task": usage_task}
                    if usage_task is not None
                    else {}
                ),
            },
        )


def resume_run(
    run_id: str,
    *,
    runs_dir: Path,
    answer: str | None,
    reconcile_result: Path | None = None,
    wrap: ExecutorWrap = _unwrapped,
    overrides: dict[str, dict[str, object]] | None = None,
) -> RunResult:
    """Lauf fortsetzen; ``overrides`` ersetzt Rollen nur für diesen
    Aufruf, das write-once-Manifest bleibt unverändert."""
    store = RunStore(runs_dir, run_id)
    manifest = store.load_manifest()
    config = {
        **_required_object(manifest, "configuration"),
        **(overrides or {}),
    }
    projection = _projection(config.get("projection_limits", {}))
    with _runtime(config, store, projection, wrap) as runtime:
        if reconcile_result is not None:
            if answer is not None:
                raise RunConfigError(
                    "--answer und --reconcile-result sind exklusiv"
                )
            artifact = _load_json(reconcile_result)
            current = runtime.result()
            if current.operation_id is None:
                raise RunConfigError(
                    "Lauf hat keine abzugleichende Operation"
                )
            return runtime.reconcile(current.operation_id, artifact)
        return runtime.resume(answer)


def status_run(run_id: str, *, runs_dir: Path) -> RunResult:
    """Lies den Status eines Laufs, ohne ihn fortzusetzen oder zu
    veraendern."""
    store = RunStore(runs_dir, run_id)
    manifest = store.load_manifest()
    _required_object(manifest, "configuration")
    return read_run_status(store)


def result_document(result: RunResult) -> dict[str, object]:
    return {
        "run_id": result.run_id,
        "status": result.status,
        "phase": result.phase.value,
        "round_id": result.round_id,
        "detail": result.detail,
        "operation_id": result.operation_id,
    }


def _runtime(
    config: dict[str, object],
    store: RunStore,
    projection: ProjectionLimits,
    wrap: ExecutorWrap,
) -> RunRuntime:
    build = _required_object(config, "worker")
    review = _required_object(config, "review")
    if (
        "session_id" in build
        and build.get("session_id") == review.get("session_id")
    ):
        raise RunConfigError(
            "Bau und Review brauchen unabhaengige Sitzungen"
        )
    checks = tuple(_check(item) for item in _list(config, "tests"))
    limits = _limits(config.get("limits", {}))
    finalizer = _finalizer(_required_object(config, "finalization"))
    return RunRuntime(
        store=store,
        worker=_adapter(build, "worker", store, wrap),
        reviewer=_adapter(review, "review", store, wrap),
        evidence_collector=RepositoryEvidenceCollector(
            checks=checks,
            round_limit=limits.changes_rounds + 1,
        ),
        finalizer=finalizer,
        limits=projection,
        safety_limits=_safety(config.get("safety_limits", {})),
    )


def _task(config: dict[str, object], run_id: str) -> RunTask:
    expected = {
        "task",
        "acceptance_criteria",
        "sources",
        "workdir",
        "access_profile",
        "env",
        "worker",
        "review",
        "tests",
        "limits",
        "projection_limits",
        "finalization",
        "safety_limits",
        "usage_task",
    }
    extra = set(config) - expected
    if extra:
        raise RunConfigError(
            f"unbekannte Konfigurationsfelder: {sorted(extra)}"
        )
    sources = config.get("sources", [])
    if not isinstance(sources, list) or any(
        not isinstance(item, str) for item in sources
    ):
        raise RunConfigError("sources muss eine Textliste sein")
    criteria = config.get("acceptance_criteria")
    if (
        not isinstance(criteria, list)
        or not criteria
        or any(
            not isinstance(item, str) or not item.strip()
            for item in criteria
        )
    ):
        raise RunConfigError(
            "acceptance_criteria muss eine nichtleere Textliste sein"
        )
    env = config.get("env", {})
    if not isinstance(env, dict) or any(
        not isinstance(k, str) or not isinstance(v, str)
        for k, v in env.items()
    ):
        raise RunConfigError(
            "env muss ein Mapping von Text auf Text sein"
        )
    workdir = Path(_text(config, "workdir")).resolve()
    try:
        return RunTask(
            run_id=run_id,
            task=_text(config, "task"),
            sources=tuple(sources),
            workdir=workdir,
            access_profile=_text(config, "access_profile"),
            acceptance_criteria=tuple(criteria),
            env=dict(env),
        )
    except (TypeError, ValueError) as exc:
        raise RunConfigError(str(exc)) from exc


_USAGE_TASK_REQUIRED = (
    "bead_id",
    "task_revision",
    "family_id",
    "family_revision",
)
_USAGE_TASK_FIELDS = frozenset(
    (*_USAGE_TASK_REQUIRED, "parent_bead_id")
)


def _usage_task(config: dict[str, object]) -> dict[str, str] | None:
    """Explizite Aufgabenbindung fuer die Verbrauchszurechnung.

    ``None`` heisst: keine Bindung konfiguriert (die Zurechnung bleibt
    dann sichtbar unvollstaendig). Ist ``usage_task`` gesetzt, verlangt
    der Vertrag (v1-safety-contract.de.md, A) bead_id, task_revision,
    family_id und family_revision; parent_bead_id ist optional. Die
    Werte landen unveraendert im write-once-Manifest (Leser:
    ``RunRuntime._usage_attribution``); Resume liest sie von dort und
    behaelt damit Revisionen und Laufbilanz. Entscheidung B (Vertrag
    A/C): ein geaenderter Auftrag ist ein ausdruecklich freigegebener
    neuer Lauf mit eigener run_id, eigenem Budget und frischen
    Sitzungen; ``family_id`` verbindet die Laeufe im kumulativen
    Familienbericht. Es gibt weder einen Revisionswechsel ueber
    ``resume_run`` noch eine Revisionshistorie im Manifest.
    """
    if "usage_task" not in config:
        return None
    binding = _mapping(config["usage_task"], "usage_task")
    extra = set(binding) - _USAGE_TASK_FIELDS
    if extra:
        raise RunConfigError(
            f"unbekannte usage_task-Felder: {sorted(extra)}"
        )
    missing = [k for k in _USAGE_TASK_REQUIRED if k not in binding]
    if missing:
        raise RunConfigError(
            f"usage_task ohne Pflichtfelder: {missing}"
        )
    result: dict[str, str] = {}
    for key, item in binding.items():
        # Dieselbe Regel wie UsageAttribution, damit ein Wert nicht erst
        # bei der Aufrufreservierung mit ValueError scheitert.
        try:
            result[key] = cast(str, metadata(item))
        except ValueError as exc:
            raise RunConfigError(f"usage_task.{key}: {exc}") from exc
        if item is None:
            raise RunConfigError(
                f"usage_task.{key} darf nicht null sein"
            )
    return result


def _spec(value: dict[str, object]) -> ExecutorSpec:
    """Deklarierter Executor der Rolle (``executor = NAME``)."""
    name = value.get("executor")
    specs = executor_specs()
    if name not in specs:
        raise RunConfigError(
            f"executor {name!r}: bekannt "
            + ", ".join(sorted(specs))
        )
    return specs[cast(str, name)]


def _has_session(spec: ExecutorSpec) -> bool:
    """CLI-Transporte setzen eine vorbereitete Sitzung fort."""
    return spec.transport in cli_transports()


def adapter_overrides(
    values: list[str],
) -> dict[str, dict[str, object]]:
    """``--adapter [ROLLE=]NAME``: Rollenkonfiguration je ersetzter
    Rolle; ohne ROLLE alle Rollen. Nur Executoren ohne Sitzung."""
    allowed = sessionless_executors()
    result: dict[str, dict[str, object]] = {}
    for value in values:
        role, _, name = value.rpartition("=")
        if name not in allowed:
            raise RunConfigError(
                f"--adapter {value}: per Argument nur "
                f"{', '.join(allowed)}; Executoren mit Sitzung "
                "im Profil festlegen"
            )
        if role and role not in ROLES:
            raise RunConfigError(
                f"--adapter {value}: Rolle {', '.join(ROLES)}"
            )
        for item in (role,) if role else ROLES:
            result[item] = {"executor": name}
    return result


def sessionless_executors() -> tuple[str, ...]:
    """Executoren ohne Sitzungsangaben; nur sie sind per Argument
    (``--adapter``) wählbar, die übrigen stehen im Profil."""
    return tuple(
        sorted(
            name
            for name, spec in executor_specs().items()
            if not _has_session(spec)
        )
    )


def _adapter(
    value: dict[str, object],
    role: str,
    store: RunStore,
    wrap: ExecutorWrap,
) -> object:
    """Adapter einer Rolle aus ihrer Konfiguration bauen."""
    spec = _spec(value)
    if spec.transport in (manual.CONSOLE, manual.INBOX):
        _exact_fields(value, {"executor"}, set(), "Rolle")
        transport = _transport(spec, store)
        return manual.ManualRelay(transport, role, spec)
    if spec.transport == mock.NAME:
        return _mock(value, role, spec)
    agent = _role(value, spec)
    agent["executor"] = wrap(cast(Executor, agent["executor"]), role)
    if role == "worker":
        return AgentWorker(**agent, spec=spec)
    return AgentReviewer(**agent, spec=spec)


def _transport(spec: ExecutorSpec, store: RunStore) -> manual.Transport:
    if spec.transport == manual.INBOX:
        return manual.Inbox(store.run_dir / "inbox")
    return manual.Console(
        write=_stdout,
        stdin=lambda: sys.stdin.buffer,
        notice=_stderr,
    )


def _stdout(text: str) -> None:
    sys.stdout.write(text if text.endswith("\n") else f"{text}\n")
    sys.stdout.flush()


def _stderr(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _mock(
    value: dict[str, object], role: str, spec: ExecutorSpec
) -> object:
    _exact_fields(value, {"executor"}, {"answers", "file"}, "Rolle")
    if role == "worker":
        if "file" in value:
            return mock.MockWorker(spec, path=_text(value, "file"))
        return mock.MockWorker(spec)
    answers = value.get("answers", ["PASS"])
    if not isinstance(answers, list) or not all(
        item in IMPLEMENT.review_events() for item in answers
    ):
        raise RunConfigError(
            "answers: Liste aus "
            + ", ".join(IMPLEMENT.review_events())
        )
    return mock.MockReviewer(spec, list(answers))


def _role(
    value: dict[str, object], spec: ExecutorSpec
) -> dict[str, object]:
    required = {"executor", "session_id", "model", "effort"}
    optional = {"executable", "timeout_s", "budget"}
    _exact_fields(value, required, optional, "Rolle")
    kwargs: dict[str, object] = {}
    if "executable" in value:
        kwargs["executable"] = _text(value, "executable")
    if "timeout_s" in value:
        timeout = value["timeout_s"]
        if not isinstance(timeout, (int, float)) or isinstance(
            timeout, bool
        ):
            raise RunConfigError("timeout_s muss eine Zahl sein")
        kwargs["timeout_s"] = float(timeout)
    try:
        effort = Effort(_text(value, "effort"))
        executor = build_executor(spec.transport, **kwargs)
    except ValueError as exc:
        raise RunConfigError(str(exc)) from exc
    return {
        "executor": executor,
        "session_id": _text(value, "session_id"),
        "model": _text(value, "model"),
        "effort": effort,
        "budget": _turn_budget(value.get("budget", {})),
    }


def _turn_budget(value: object) -> TurnBudget:
    try:
        return TurnBudget(**_mapping(value, "budget"))
    except (TypeError, ValueError) as exc:
        raise RunConfigError(str(exc)) from exc


def _safety(value: object) -> SafetyLimits:
    try:
        return SafetyLimits(**_mapping(value, "safety_limits"))
    except (TypeError, ValueError) as exc:
        raise RunConfigError(str(exc)) from exc


def _check(value: object) -> CheckCommand:
    if not isinstance(value, dict):
        raise RunConfigError("jeder Test muss ein Objekt sein")
    _exact_fields(value, {"name", "argv"}, {"timeout_s"}, "Test")
    argv = value["argv"]
    if not isinstance(argv, list) or any(
        not isinstance(item, str) for item in argv
    ):
        raise RunConfigError("Test.argv muss eine Textliste sein")
    timeout = value.get("timeout_s", 600.0)
    if not isinstance(timeout, (int, float)) or isinstance(
        timeout, bool
    ):
        raise RunConfigError("Test.timeout_s muss eine Zahl sein")
    return CheckCommand(
        _text(value, "name"), tuple(argv), float(timeout)
    )


def _finalizer(value: dict[str, object]) -> RepositoryFinalizer:
    _exact_fields(
        value,
        {"target_workdir", "target_ref", "commit_message", "data_mode"},
        set(),
        "Finalisierung",
    )
    try:
        return RepositoryFinalizer(
            target_workdir=Path(
                _text(value, "target_workdir")
            ).resolve(),
            target_ref=_text(value, "target_ref"),
            commit_message=_text(value, "commit_message"),
            data_mode=_text(value, "data_mode"),
        )
    except ValueError as exc:
        raise RunConfigError(str(exc)) from exc


def _limits(value: object) -> Limits:
    fields = asdict(Limits())
    supplied = _mapping(value, "limits")
    extra = set(supplied) - set(fields)
    if extra:
        raise RunConfigError(f"unbekannte Limits: {sorted(extra)}")
    fields.update(supplied)
    try:
        return Limits(**fields)
    except (TypeError, ValueError) as exc:
        raise RunConfigError(str(exc)) from exc


def _projection(value: object) -> ProjectionLimits:
    fields = asdict(ProjectionLimits())
    supplied = _mapping(value, "projection_limits")
    extra = set(supplied) - set(fields)
    if extra:
        raise RunConfigError(
            f"unbekannte Projektionsgrenzen: {sorted(extra)}"
        )
    fields.update(supplied)
    try:
        return ProjectionLimits(**fields)
    except (TypeError, ValueError) as exc:
        raise RunConfigError(str(exc)) from exc


def _load_json(path: Path) -> object:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunConfigError(
            f"Konfiguration nicht lesbar: {exc}"
        ) from exc
    return value


def _required_object(
    value: dict[str, object], name: str
) -> dict[str, object]:
    item = value.get(name)
    if not isinstance(item, dict):
        raise RunConfigError(f"{name} muss ein Objekt sein")
    return cast(dict[str, object], item)


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RunConfigError(f"{name} muss ein Objekt sein")
    return cast(dict[str, object], value)


def _list(value: dict[str, object], name: str) -> list[object]:
    item = value.get(name, [])
    if not isinstance(item, list):
        raise RunConfigError(f"{name} muss eine Liste sein")
    return item


def _text(value: dict[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item.strip():
        raise RunConfigError(f"{name} muss nichtleerer Text sein")
    return item


def _exact_fields(
    value: dict[str, object],
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    missing = required - set(value)
    extra = set(value) - required - optional
    if missing:
        raise RunConfigError(
            f"{label}: fehlende Felder {sorted(missing)}"
        )
    if extra:
        raise RunConfigError(
            f"{label}: unbekannte Felder {sorted(extra)}"
        )
