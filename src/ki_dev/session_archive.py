"""Zeitraum auswählen und Snapshots ergänzend archivieren."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import typer

from ki_dev.adapter.executors.session_activity import (
    ActivityBounds,
    raw_activity_bounds,
)
from ki_dev.adapter.executors.session_transcript import TranscriptError
from ki_dev.adapter.executors.transcript import (
    parse_session_source,
    read_session_source,
)
from ki_dev.session_list import select_listing
from ki_dev.session_output import fail
from ki_dev.session_snapshot import SnapshotError, store_snapshot


@dataclass(frozen=True)
class ArchivePeriod:
    """UTC-Grenzen für die letzte protokollierte Sitzungsaktivität."""

    since: datetime | None
    until: datetime | None

    @classmethod
    def parse(
        cls, since: str | None, until: str | None
    ) -> ArchivePeriod:
        lower = _boundary(since, end=False)
        upper = _boundary(until, end=True)
        if lower is not None and upper is not None and lower >= upper:
            fail("--since muss vor --until liegen", code=2)
        return cls(lower, upper)

    def contains(self, timestamp: str | None) -> bool:
        if self.since is None and self.until is None:
            return True
        if timestamp is None:
            raise SnapshotError("last_activity_at für Zeitraum fehlt")
        moment = datetime.fromisoformat(timestamp)
        return (self.since is None or moment >= self.since) and (
            self.until is None or moment < self.until
        )

    def may_contain(self, bounds: ActivityBounds | None) -> bool:
        if bounds is None:
            return True
        return (self.since is None or bounds.latest >= self.since) and (
            self.until is None or bounds.earliest < self.until
        )


def archive_sessions(
    agent: str | None,
    directory: Path,
    title: str | None,
    period: ArchivePeriod,
    include_tests: bool,
) -> None:
    """Einzelfehler melden, übrige Sitzungen trotzdem archivieren."""
    listing = select_listing(agent, None, include_tests)
    saved = errors = outside = 0
    for ref in listing.refs:
        try:
            data = read_session_source(ref)
            if period.since is not None or period.until is not None:
                bounds = raw_activity_bounds(ref.agent, data)
                if not period.may_contain(bounds):
                    outside += 1
                    continue
            loaded = parse_session_source(ref, data)
            if not period.contains(loaded.last_activity_at):
                outside += 1
                continue
            path = store_snapshot(loaded, title, directory)
        except (TranscriptError, SnapshotError) as exc:
            errors += 1
            detail = (
                "; ".join(exc.problems)
                if isinstance(exc, TranscriptError)
                else str(exc)
            )
            typer.echo(
                f"{ref.agent} {ref.session_id}: {detail}", err=True
            )
            continue
        typer.echo(path.as_posix())
        saved += 1
    typer.echo(
        f"{saved} archiviert oder bereits vorhanden; "
        f"{outside} außerhalb des Zeitraums; {errors} Fehler.",
        err=True,
    )
    if errors:
        raise typer.Exit(1)


def _boundary(value: str | None, *, end: bool) -> datetime | None:
    if value is None:
        return None
    try:
        if len(value) == 10:
            day = date.fromisoformat(value)
            moment = datetime.combine(day, datetime.min.time(), UTC)
            return moment + timedelta(days=1) if end else moment
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is None:
            raise ValueError("Zeitzone fehlt")
        return moment.astimezone(UTC)
    except (ValueError, OverflowError):
        option = "--until" if end else "--since"
        fail(
            f"{option}: YYYY-MM-DD oder ISO-Zeitpunkt "
            "mit Zeitzone angeben",
            code=2,
        )
