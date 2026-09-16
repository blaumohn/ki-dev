"""Begrenzte Projektion von Nachweisen fuer einen Review-Turn.

Die vollstaendigen Deltas bleiben die Beweisquelle. Dieses Modul erzeugt
daraus vor dem Agentenaufruf eine kleinere Sicht und kennzeichnet jede
Auslassung.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from ki_dev.deltas import (
    CombinedDelta,
    ControllerContext,
    GitFileChange,
)


@dataclass(frozen=True)
class ProjectionLimits:
    max_file_bytes: int = 16_384
    max_file_lines: int = 200
    max_total_bytes: int = 65_536

    def __post_init__(self) -> None:
        for name, value in (
            ("max_file_bytes", self.max_file_bytes),
            ("max_file_lines", self.max_file_lines),
            ("max_total_bytes", self.max_total_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    f"ProjectionLimits.{name} muss ein int sein"
                )
            if value < 128:
                raise ValueError(
                    f"ProjectionLimits.{name} ist zu klein"
                )


DEFAULT_PROJECTION_LIMITS = ProjectionLimits()


@dataclass(frozen=True)
class Omission:
    reference: str
    reason: str


@dataclass(frozen=True)
class ReviewProjection:
    text: str
    omissions: tuple[Omission, ...]

    @property
    def byte_count(self) -> int:
        return len(self.text.encode("utf-8"))


_DIFF_START = re.compile(r"(?m)^diff --git ")
_BINARY_MARKERS = ("Binary files ", "GIT binary patch")
_SKIP_PARTS = frozenset(
    {
        ".loope",
        ".ki-dev",
        "__pycache__",
        ".pytest_cache",
        ".hypothesis",
        ".ruff_cache",
        ".mypy_cache",
        ".venv",
        "venv",
    }
)


def project_review_context(
    context: ControllerContext,
    *,
    limits: ProjectionLimits = DEFAULT_PROJECTION_LIMITS,
    preferred_paths: tuple[str, ...] = (),
) -> ReviewProjection:
    """Rendere den aktuellen Schrittdelta, optional den Laufdelta.

    ``preferred_paths`` ist der begrenzte Nachlademechanismus: bekannte
    fachliche Pfade werden in einer neuen Projektion zuerst eingeordnet,
    ohne Datei- oder Gesamtgrenzen zu lockern. Laufartefakte bleiben
    ausgeschlossen.
    """
    known_paths = {item.path for item in context.step_delta.git.files}
    unknown = set(preferred_paths) - known_paths
    if unknown:
        raise ValueError(
            "Nachladen nur fuer Pfade des aktuellen Schrittdeltas: "
            + ", ".join(sorted(unknown))
        )

    omissions: list[Omission] = []
    chunks = [
        f"TASK\n{context.task}\n",
        (
            "ROUND\n"
            f"{context.round_status.current}/{context.round_status.limit}\n"
        ),
    ]
    if context.open_objection:
        chunks.append(f"OPEN_OBJECTION\n{context.open_objection}\n")
    if context.checks:

        def render_check() -> list[str]:
            results = []
            for check in context.checks:
                status = "PASS" if check.passed else "FAIL"
                results.append(
                    f"- {check.name}: {status} {check.detail}".rstrip()
                )
            return results

        rendered = "\n".join(render_check())
        chunks.append(f"CHECKS\n{rendered}\n")

    chunks.extend(
        _project_delta(
            context.step_delta,
            limits=limits,
            omissions=omissions,
            preferred_paths=preferred_paths,
        )
    )
    if context.run_delta is not None:
        chunks.extend(
            _project_delta(
                context.run_delta,
                limits=limits,
                omissions=omissions,
                preferred_paths=(),
            )
        )

    omission_text = "".join(
        f"OMITTED [{item.reference}] reason={item.reason}\n"
        for item in omissions
    )
    body = "\n".join(chunks)
    return ReviewProjection(
        text=_fit_total(body, omission_text, limits.max_total_bytes),
        omissions=tuple(omissions),
    )


def _project_delta(
    delta: CombinedDelta,
    *,
    limits: ProjectionLimits,
    omissions: list[Omission],
    preferred_paths: tuple[str, ...],
) -> list[str]:
    label = delta.scope.value.upper()
    chunks = [
        f"{label}_REFS git={delta.git.boundary.base.value}.."
        f"{delta.git.boundary.result.value} beads="
        f"{delta.beads.boundary.base.value}.."
        f"{delta.beads.boundary.result.value}\n"
    ]
    sections = _patch_sections(delta.git.patch, delta.git.files)
    order = {path: index for index, path in enumerate(preferred_paths)}
    files = sorted(
        delta.git.files,
        key=lambda item: (order.get(item.path, len(order)), item.path),
    )
    for change in files:
        ref = f"{label.lower()}:git:{change.path}"
        if _skip_path(change.path):
            omissions.append(
                Omission(ref, "runtime_or_internal_artifact")
            )
            continue
        section = sections.get(change.path, "")
        if _is_binary(section):
            metadata = (
                f"{label}_FILE {change.status} {change.path} "
                "[binary metadata only]\n"
            )
            chunks.append(metadata)
            continue
        limited, reason = _limit_file(section, limits)
        chunks.append(
            f"{label}_FILE {change.status} {change.path}\n{limited}\n"
        )
        if reason:
            omissions.append(Omission(ref, reason))

    if delta.beads.summary:
        limited, reason = _limit_file(delta.beads.summary, limits)
        chunks.append(f"{label}_BEADS\n{limited}\n")
        if reason:
            omissions.append(Omission(f"{label.lower()}:beads", reason))
    elif delta.beads.issues:
        chunks.append(
            f"{label}_BEADS\n"
            + "\n".join(
                f"- {item.change_type}: {item.issue_id}"
                for item in delta.beads.issues
            )
            + "\n"
        )
    return chunks


def _patch_sections(
    patch: str, files: tuple[GitFileChange, ...]
) -> dict[str, str]:
    starts = [match.start() for match in _DIFF_START.finditer(patch)]
    raw_sections = [
        patch[
            start : starts[index + 1]
            if index + 1 < len(starts)
            else None
        ]
        for index, start in enumerate(starts)
    ]
    sections: dict[str, str] = {}
    for section in raw_sections:
        path = _section_path(section)
        if path is not None:
            sections[path] = section
    if len(files) == 1 and files[0].path not in sections:
        sections[files[0].path] = patch
    return sections


def _section_path(section: str) -> str | None:
    for line in section.splitlines():
        if line.startswith("+++ b/"):
            return line[6:]
    first = section.splitlines()[0] if section else ""
    if first.startswith("diff --git a/") and " b/" in first:
        return first.rsplit(" b/", 1)[1]
    return None


def _skip_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if any(part in _SKIP_PARTS for part in parts):
        return True
    return (
        len(parts) >= 2
        and parts[0] == ".beads"
        and parts[1] != "issues.jsonl"
    )


def _is_binary(text: str) -> bool:
    return "\x00" in text or any(
        marker in text for marker in _BINARY_MARKERS
    )


def _limit_file(
    text: str, limits: ProjectionLimits
) -> tuple[str, str | None]:
    lines = text.splitlines(keepends=True)
    reasons: list[str] = []
    if len(lines) > limits.max_file_lines:
        lines = lines[: limits.max_file_lines]
        reasons.append("file_line_limit")
    rendered = "".join(lines)
    raw = rendered.encode("utf-8")
    if len(raw) > limits.max_file_bytes:
        rendered = raw[: limits.max_file_bytes].decode(
            "utf-8", errors="ignore"
        )
        reasons.append("file_byte_limit")
    return rendered.rstrip("\n"), "+".join(reasons) or None


def _fit_total(body: str, omissions: str, maximum: int) -> str:
    trailer = omissions.encode("utf-8")
    if len(trailer) >= maximum:
        marker = b"OMITTED [projection] reason=total_byte_limit\n"
        return (trailer[: maximum - len(marker)] + marker).decode(
            "utf-8", errors="ignore"
        )
    body_raw = body.encode("utf-8")
    room = maximum - len(trailer)
    if len(body_raw) > room:
        marker = b"\nOMITTED [projection] reason=total_byte_limit\n"
        room = max(0, room - len(marker))
        body_raw = body_raw[:room] + marker
    return (body_raw + trailer).decode("utf-8", errors="ignore")
