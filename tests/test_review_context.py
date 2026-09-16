from __future__ import annotations

from ki_dev.deltas import (
    BeadsDelta,
    BeadsIssueChange,
    ChangeMedium,
    CombinedDelta,
    ControllerContext,
    DeltaScope,
    GitDelta,
    GitFileChange,
    RefBoundary,
    RoundStatus,
    VcsRef,
)
from ki_dev.review_context import (
    Omission,
    ProjectionLimits,
    project_review_context,
)


def _context(
    files: list[tuple[str, str]], *, beads: str = ""
) -> ControllerContext:
    git_base = VcsRef(ChangeMedium.GIT, "git-a")
    git_result = VcsRef(ChangeMedium.GIT, "git-b")
    bd_base = VcsRef(ChangeMedium.BEADS, "bd-a")
    bd_result = VcsRef(ChangeMedium.BEADS, "bd-b")
    patch = "".join(content for _, content in files)
    delta = CombinedDelta(
        scope=DeltaScope.STEP,
        git=GitDelta(
            RefBoundary(git_base, git_result),
            tuple(GitFileChange("M", path) for path, _ in files),
            patch,
        ),
        beads=BeadsDelta(
            RefBoundary(bd_base, bd_result),
            (BeadsIssueChange("ki-dev-x", "modified"),)
            if beads
            else (),
            beads,
        ),
    )
    return ControllerContext(
        task="Auftrag",
        step_delta=delta,
        round_status=RoundStatus(1, 2),
    )


def _patch(path: str, body: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n{body}"
    )


def test_projection_keeps_text_and_domain_beads_delta():
    context = _context(
        [("src/app.py", _patch("src/app.py", "+print('neu')\n"))],
        beads="Modified ki-dev-x: fachliche Abnahme",
    )
    projected = project_review_context(context)
    assert "+print('neu')" in projected.text
    assert "Modified ki-dev-x: fachliche Abnahme" in projected.text
    assert "git-a..git-b" in projected.text
    assert "bd-a..bd-b" in projected.text


def test_binary_is_metadata_only():
    binary = _patch(
        "assets/blob.bin", "Binary files a/x and b/x differ\n"
    )
    projected = project_review_context(
        _context([("assets/blob.bin", binary)])
    )
    assert (
        "assets/blob.bin index=unbekannt [binary metadata only]"
        in projected.text
    )
    assert "Binary files" not in projected.text
    assert projected.omissions == (
        Omission("step:git:assets/blob.bin", "binary_content"),
    )


def test_binary_reference_uses_git_blob_hashes_when_present():
    binary = (
        "diff --git a/assets/blob.bin b/assets/blob.bin\n"
        "index f395269..c670d96 100644\n"
        "Binary files a/assets/blob.bin and b/assets/blob.bin differ\n"
    )
    projected = project_review_context(
        _context([("assets/blob.bin", binary)])
    )
    assert "index=f395269..c670d96" in projected.text


def test_lockfile_is_summarized_not_shown_in_full():
    lockfile = _patch(
        "package-lock.json",
        "+\"left-pad\": \"1.0.0\"\n-\"left-pad\": \"0.9.0\"\n",
    )
    projected = project_review_context(
        _context([("package-lock.json", lockfile)])
    )
    assert "left-pad" not in projected.text
    assert "+1/-1 Zeilen" in projected.text
    assert any(
        item.reason == "lockfile_summary"
        for item in projected.omissions
    )


def test_lockfile_full_content_returns_via_preferred_paths():
    lockfile = _patch(
        "package-lock.json",
        "+\"left-pad\": \"1.0.0\"\n",
    )
    context = _context([("package-lock.json", lockfile)])
    summarized = project_review_context(context)
    reloaded = project_review_context(
        context, preferred_paths=("package-lock.json",)
    )
    assert "left-pad" not in summarized.text
    assert "left-pad" in reloaded.text


def test_json_single_line_is_limited_by_bytes():
    huge = _patch("report.json", "+" + "x" * 20_000 + "\n")
    limits = ProjectionLimits(
        max_file_bytes=512, max_file_lines=200, max_total_bytes=4096
    )
    projected = project_review_context(
        _context([("report.json", huge)]), limits=limits
    )
    assert projected.byte_count <= 4096
    assert any(
        "file_byte_limit" in item.reason for item in projected.omissions
    )
    assert "OMITTED [step:git:report.json]" in projected.text


def test_caches_internal_dolt_and_nested_transcripts_are_excluded():
    paths = (
        ".pytest_cache/v/cache/lastfailed",
        ".beads/embeddeddolt/db/journal.idx",
        ".loope/runs/001/reviewer/transcript.jsonl",
        ".ki-dev/runs/002/transcript.jsonl",
    )
    context = _context(
        [(path, _patch(path, "+secret payload\n")) for path in paths]
    )
    projected = project_review_context(context)
    assert "secret payload" not in projected.text
    for path in paths:
        assert path in projected.text
    assert len(projected.omissions) == len(paths)


def test_total_limit_and_bounded_followup():
    files = [
        (
            f"src/{number}.py",
            _patch(f"src/{number}.py", "+" + "z" * 600 + "\n"),
        )
        for number in range(8)
    ]
    limits = ProjectionLimits(
        max_file_bytes=300, max_file_lines=200, max_total_bytes=1400
    )
    context = _context(files)
    first = project_review_context(context, limits=limits)
    followup = project_review_context(
        context, limits=limits, preferred_paths=("src/7.py",)
    )
    assert first.byte_count <= limits.max_total_bytes
    assert followup.byte_count <= limits.max_total_bytes
    assert followup.text.index("src/7.py") < followup.text.index(
        "src/0.py"
    )


def test_followup_cannot_request_an_unobserved_path():
    context = _context([("src/a.py", _patch("src/a.py", "+a\n"))])
    try:
        project_review_context(
            context, preferred_paths=("secrets.txt",)
        )
    except ValueError as exc:
        assert "aktuellen Schrittdeltas" in str(exc)
    else:
        raise AssertionError("unbekannter Pfad wurde nachgeladen")
