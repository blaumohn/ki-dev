"""Git- und ``bd``-/Dolt-Schrittdeltas pro Worker-Schritt.

Oeffentliche Nutzung durch den spaeteren Orchestrator:

* :func:`capture_media_refs` -- Basisreferenzen vor dem Schritt bzw. die
  Laufbasis zu Laufbeginn
* :func:`checkpoint_step_result` -- Schritt abschliessen und
  Ergebnisreferenzen erfassen
* :func:`build_step_delta` / :func:`build_run_delta` -- getrennte
  Sichten
* :func:`assess_step_delta` -- No-op-/Ergebnispruefung bei leerem
  Delta
* :data:`SUPPORTED_BD_VERSION` / :func:`verify_bd_version` -- gepinnte
  Beads-Version
"""

from __future__ import annotations

from .beads_changes import (
    BD_DIFF_INTERFACE,
    SUPPORTED_BD_VERSION,
    build_beads_delta,
    capture_beads_ref,
    installed_bd_version,
    verify_bd_version,
)
from .command import (
    HOST_GIT,
    CommandOutput,
    DeltaCommandError,
    run_command,
)
from .contract import (
    BeadsDelta,
    BeadsIssueChange,
    ChangeMedium,
    CheckOutcome,
    CombinedDelta,
    ControllerContext,
    DeltaScope,
    GitDelta,
    GitFileChange,
    MediaRefs,
    RefBoundary,
    RoundStatus,
    StepDeltaAssessment,
    VcsRef,
    WorkerSignal,
)
from .git_changes import (
    build_git_delta,
    capture_git_ref,
    checkpoint_git_step,
)
from .step_delta import (
    assess_step_delta,
    build_run_delta,
    build_step_delta,
    capture_media_refs,
    checkpoint_step_result,
)

__all__ = [
    "BD_DIFF_INTERFACE",
    "SUPPORTED_BD_VERSION",
    "BeadsDelta",
    "BeadsIssueChange",
    "ChangeMedium",
    "CheckOutcome",
    "CombinedDelta",
    "CommandOutput",
    "ControllerContext",
    "DeltaCommandError",
    "DeltaScope",
    "GitDelta",
    "GitFileChange",
    "MediaRefs",
    "RefBoundary",
    "RoundStatus",
    "StepDeltaAssessment",
    "VcsRef",
    "WorkerSignal",
    "assess_step_delta",
    "build_beads_delta",
    "build_git_delta",
    "build_run_delta",
    "build_step_delta",
    "capture_beads_ref",
    "capture_git_ref",
    "capture_media_refs",
    "checkpoint_git_step",
    "checkpoint_step_result",
    "installed_bd_version",
    "HOST_GIT",
    "run_command",
    "verify_bd_version",
]
