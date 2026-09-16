"""Konfigurations- und Befehlsadapter fuer den persistenten Loop."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import cast

from ki_dev.executors import Effort, build_executor
from ki_dev.executors.contract import TurnBudget
from ki_dev.loop import AgentBuildMode, AgentReviewer, LoopTask
from ki_dev.loop_runtime import (
    LoopRunResult,
    LoopRuntime,
    read_run_status,
)
from ki_dev.loop_safety import SafetyLimits
from ki_dev.machine import Limits
from ki_dev.repository_evidence import (
    CheckCommand,
    RepositoryEvidenceCollector,
)
from ki_dev.repository_finalization import RepositoryFinalizer
from ki_dev.review_context import ProjectionLimits
from ki_dev.run_store import RunStore


class LoopConfigError(ValueError):
    """Die explizite Loop-Konfiguration ist ungueltig."""


def start_from_config(
    path: Path,
    *,
    run_id: str | None,
    runs_dir: Path,
) -> LoopRunResult:
    config = _load_object(path)
    # Effektive Defaults bleiben ueber Upgrades nachvollziehbar.
    for role in ("build", "review"):
        values = _required_object(config, role)
        config[role] = {
            **values,
            "budget": asdict(_turn_budget(values.get("budget", {}))),
        }
    actual_run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
    task = _task(config, actual_run_id)
    limits = _limits(config.get("limits", {}))
    projection = _projection(config.get("projection_limits", {}))
    with _runtime(
        config, RunStore(runs_dir, actual_run_id), projection
    ) as runtime:
        return runtime.start(
            task,
            limits,
            manifest_extra={"configuration": config},
        )


def resume_run(
    run_id: str,
    *,
    runs_dir: Path,
    answer: str | None,
    reconcile_result: Path | None = None,
) -> LoopRunResult:
    store = RunStore(runs_dir, run_id)
    manifest = store.load_manifest()
    config = _required_object(manifest, "configuration")
    projection = _projection(config.get("projection_limits", {}))
    with _runtime(config, store, projection) as runtime:
        if reconcile_result is not None:
            if answer is not None:
                raise LoopConfigError(
                    "--answer und --reconcile-result sind exklusiv"
                )
            artifact = _load_json(reconcile_result)
            current = runtime.result()
            if current.operation_id is None:
                raise LoopConfigError(
                    "Lauf hat keine abzugleichende Operation"
                )
            return runtime.reconcile(current.operation_id, artifact)
        return runtime.resume(answer)


def status_run(run_id: str, *, runs_dir: Path) -> LoopRunResult:
    """Lies den Status eines Laufs, ohne ihn fortzusetzen oder zu
    veraendern."""
    store = RunStore(runs_dir, run_id)
    manifest = store.load_manifest()
    _required_object(manifest, "configuration")
    return read_run_status(store)


def result_document(result: LoopRunResult) -> dict[str, object]:
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
) -> LoopRuntime:
    build = _role(_required_object(config, "build"))
    review = _role(_required_object(config, "review"))
    if build["session_id"] == review["session_id"]:
        raise LoopConfigError(
            "Bau und Review brauchen unabhaengige Sitzungen"
        )
    checks = tuple(_check(item) for item in _list(config, "tests"))
    limits = _limits(config.get("limits", {}))
    finalizer = _finalizer(_required_object(config, "finalization"))
    return LoopRuntime(
        store=store,
        builder=AgentBuildMode(**build),
        reviewer=AgentReviewer(**review),
        evidence_collector=RepositoryEvidenceCollector(
            checks=checks,
            round_limit=limits.changes_rounds + 1,
        ),
        finalizer=finalizer,
        limits=projection,
        safety_limits=_safety(config.get("safety_limits", {})),
    )


def _task(config: dict[str, object], run_id: str) -> LoopTask:
    expected = {
        "task",
        "acceptance_criteria",
        "sources",
        "workdir",
        "access_profile",
        "env",
        "build",
        "review",
        "tests",
        "limits",
        "projection_limits",
        "finalization",
        "safety_limits",
    }
    extra = set(config) - expected
    if extra:
        raise LoopConfigError(
            f"unbekannte Konfigurationsfelder: {sorted(extra)}"
        )
    sources = config.get("sources", [])
    if not isinstance(sources, list) or any(
        not isinstance(item, str) for item in sources
    ):
        raise LoopConfigError("sources muss eine Textliste sein")
    criteria = config.get("acceptance_criteria")
    if (
        not isinstance(criteria, list)
        or not criteria
        or any(
            not isinstance(item, str) or not item.strip()
            for item in criteria
        )
    ):
        raise LoopConfigError(
            "acceptance_criteria muss eine nichtleere Textliste sein"
        )
    env = config.get("env", {})
    if not isinstance(env, dict) or any(
        not isinstance(k, str) or not isinstance(v, str)
        for k, v in env.items()
    ):
        raise LoopConfigError(
            "env muss ein Mapping von Text auf Text sein"
        )
    workdir = Path(_text(config, "workdir")).resolve()
    try:
        return LoopTask(
            run_id=run_id,
            task=_text(config, "task"),
            sources=tuple(sources),
            workdir=workdir,
            access_profile=_text(config, "access_profile"),
            acceptance_criteria=tuple(criteria),
            env=dict(env),
        )
    except (TypeError, ValueError) as exc:
        raise LoopConfigError(str(exc)) from exc


def _role(value: dict[str, object]) -> dict[str, object]:
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
            raise LoopConfigError("timeout_s muss eine Zahl sein")
        kwargs["timeout_s"] = float(timeout)
    try:
        effort = Effort(_text(value, "effort"))
        executor = build_executor(_text(value, "executor"), **kwargs)
    except ValueError as exc:
        raise LoopConfigError(str(exc)) from exc
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
        raise LoopConfigError(str(exc)) from exc


def _safety(value: object) -> SafetyLimits:
    try:
        return SafetyLimits(**_mapping(value, "safety_limits"))
    except (TypeError, ValueError) as exc:
        raise LoopConfigError(str(exc)) from exc


def _check(value: object) -> CheckCommand:
    if not isinstance(value, dict):
        raise LoopConfigError("jeder Test muss ein Objekt sein")
    _exact_fields(value, {"name", "argv"}, {"timeout_s"}, "Test")
    argv = value["argv"]
    if not isinstance(argv, list) or any(
        not isinstance(item, str) for item in argv
    ):
        raise LoopConfigError("Test.argv muss eine Textliste sein")
    timeout = value.get("timeout_s", 600.0)
    if not isinstance(timeout, (int, float)) or isinstance(
        timeout, bool
    ):
        raise LoopConfigError("Test.timeout_s muss eine Zahl sein")
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
        raise LoopConfigError(str(exc)) from exc


def _limits(value: object) -> Limits:
    fields = asdict(Limits())
    supplied = _mapping(value, "limits")
    extra = set(supplied) - set(fields)
    if extra:
        raise LoopConfigError(f"unbekannte Limits: {sorted(extra)}")
    fields.update(supplied)
    try:
        return Limits(**fields)
    except (TypeError, ValueError) as exc:
        raise LoopConfigError(str(exc)) from exc


def _projection(value: object) -> ProjectionLimits:
    fields = asdict(ProjectionLimits())
    supplied = _mapping(value, "projection_limits")
    extra = set(supplied) - set(fields)
    if extra:
        raise LoopConfigError(
            f"unbekannte Projektionsgrenzen: {sorted(extra)}"
        )
    fields.update(supplied)
    try:
        return ProjectionLimits(**fields)
    except (TypeError, ValueError) as exc:
        raise LoopConfigError(str(exc)) from exc


def _load_object(path: Path) -> dict[str, object]:
    value = _load_json(path)
    if not isinstance(value, dict):
        raise LoopConfigError("Konfiguration muss ein JSON-Objekt sein")
    return value


def _load_json(path: Path) -> object:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LoopConfigError(
            f"Konfiguration nicht lesbar: {exc}"
        ) from exc
    return value


def _required_object(
    value: dict[str, object], name: str
) -> dict[str, object]:
    item = value.get(name)
    if not isinstance(item, dict):
        raise LoopConfigError(f"{name} muss ein Objekt sein")
    return cast(dict[str, object], item)


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise LoopConfigError(f"{name} muss ein Objekt sein")
    return cast(dict[str, object], value)


def _list(value: dict[str, object], name: str) -> list[object]:
    item = value.get(name, [])
    if not isinstance(item, list):
        raise LoopConfigError(f"{name} muss eine Liste sein")
    return item


def _text(value: dict[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item.strip():
        raise LoopConfigError(f"{name} muss nichtleerer Text sein")
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
        raise LoopConfigError(
            f"{label}: fehlende Felder {sorted(missing)}"
        )
    if extra:
        raise LoopConfigError(
            f"{label}: unbekannte Felder {sorted(extra)}"
        )
