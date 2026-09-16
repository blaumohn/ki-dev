"""Schritt- und Laufdelta pro Worker-Runde.

Diese Ebene verkabelt Git- und ``bd``-/Dolt-Referenzen zu den zwei
getrennten Sichten aus Anlage B:

* ``step_delta`` -- Wirkung genau der aktuellen Worker-Runde
* ``run_delta``  -- kumulierte Wirkung seit Laufbeginn

Beide entstehen aus demselben Aufbau (Basisreferenz, Ergebnisreferenz,
Delta) und unterscheiden sich nur in der Basis und in der Beschriftung
:class:`DeltaScope`.

Die Zustandsmaschine, die Schleifenverkabelung und die Git-Finalisierung
nach ``PASS`` gehoeren nicht hierher.
"""

from __future__ import annotations

from pathlib import Path

from .beads_changes import build_beads_delta, capture_beads_ref
from .contract import (
    CombinedDelta,
    DeltaScope,
    MediaRefs,
    RefBoundary,
    StepDeltaAssessment,
    WorkerSignal,
)
from .git_changes import (
    build_git_delta,
    capture_git_ref,
    checkpoint_git_step,
)


def capture_media_refs(repo: Path) -> MediaRefs:
    """Erfasse Git- und ``bd``-/Dolt-Referenz zum selben Zeitpunkt.

    Vor einem Worker-Schritt liefert dies die Basisreferenzen; zu
    Laufbeginn zusaetzlich die Laufbasis.
    """
    return MediaRefs(
        git=capture_git_ref(repo),
        beads=capture_beads_ref(repo),
    )


def checkpoint_step_result(repo: Path, *, message: str) -> MediaRefs:
    """Schliesse einen Worker-Schritt ab, erfasse die Ergebnisrefs.

    Git erhaelt genau einen angehaengten Checkpoint-Commit. Dolt
    versioniert Beads-Schreibzugriffe bereits selbst; die
    ``bd``-Ergebnisreferenz wird nur gelesen.
    """
    return MediaRefs(
        git=checkpoint_git_step(repo, message=message),
        beads=capture_beads_ref(repo),
    )


def build_step_delta(
    repo: Path,
    base: MediaRefs,
    result: MediaRefs,
) -> CombinedDelta:
    """Bilde den Delta genau der aktuellen Worker-Runde."""
    return _build_delta(repo, base, result, DeltaScope.STEP)


def build_run_delta(
    repo: Path,
    run_base: MediaRefs,
    result: MediaRefs,
) -> CombinedDelta:
    """Bilde den kumulierten Delta seit Laufbeginn."""
    return _build_delta(repo, run_base, result, DeltaScope.RUN)


def assess_step_delta(
    step_delta: CombinedDelta,
    worker_signal: WorkerSignal | None = None,
) -> StepDeltaAssessment:
    """Wende die No-op-/Ergebnispruefung auf einen Schrittdelta an.

    Ein leerer Delta ist nie automatisch ein Erfolg (Planerausgabe 15).
    Ohne Worker-Sonderfall fuehrt er zu
    :data:`StepDeltaAssessment.EMPTY_UNEXPLAINED`; der Aufrufer muss
    daraus Rueckkopplung oder Eskalation ableiten.
    """
    if step_delta.scope is not DeltaScope.STEP:
        raise ValueError("assess_step_delta erwartet einen STEP-Delta")
    if not step_delta.is_empty:
        return StepDeltaAssessment.EFFECTIVE
    if worker_signal is None:
        return StepDeltaAssessment.EMPTY_UNEXPLAINED
    return StepDeltaAssessment.EMPTY_WITH_SIGNAL


def _build_delta(
    repo: Path,
    base: MediaRefs,
    result: MediaRefs,
    scope: DeltaScope,
) -> CombinedDelta:
    git_delta = build_git_delta(repo, RefBoundary(base.git, result.git))
    beads_delta = build_beads_delta(
        repo, RefBoundary(base.beads, result.beads)
    )
    return CombinedDelta(scope=scope, git=git_delta, beads=beads_delta)
