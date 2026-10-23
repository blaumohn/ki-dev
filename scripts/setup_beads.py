"""Passendes bd wiederverwenden oder den gepinnten Quellstand bauen."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from plumbum import local
from plumbum.commands.processes import (
    ProcessExecutionError,
    ProcessTimedOut,
)
from plumbum.machines.local import CommandNotFound


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    # Checkout verwenden, auch wenn ein älteres Paket installiert ist.
    sys.path.insert(0, str(root / "src"))
    from ki_dev.tool_versions import load_tool_versions

    pins = load_tool_versions()
    target = root / ".venv/bin/bd"
    for candidate in candidates(target):
        if matches(candidate, pins, root):
            if candidate != target:
                replace_link(target, candidate)
            print(
                f"bd {pins['BD_VERSION']} ({pins['BD_COMMIT'][:7]}): "
                f"{candidate}"
            )
            return
    print(
        "Kein passendes bd vorhanden; baue den gepinnten Commit.",
        flush=True,
    )
    install(target, pins, root)


def candidates(target: Path):
    """Lokales bd zuerst, danach eindeutige ausführbare PATH-Treffer."""
    seen = set()
    paths = [
        target,
        *(Path(p).absolute() / "bd" for p in os.get_exec_path()),
    ]
    for path in paths:
        resolved = path.resolve()
        if (
            resolved not in seen
            and path.is_file()
            and os.access(path, os.X_OK)
        ):
            seen.add(resolved)
            yield path


def matches(binary: Path, pins: dict[str, str], cwd: Path) -> bool:
    output = run(str(binary), ["--version"], cwd, 10).strip()
    match = re.fullmatch(
        r"bd version (\d+\.\d+\.\d+) \(([^()\n]+)\)", output
    )
    if match is None:
        raise ValueError(
            f"bd-Versionsausgabe nicht erkennbar: {binary}"
        )
    revision = re.search(r"(?:^|[:@] ?)([a-f0-9]{7,40})$", match[2])
    return (
        match[1] == pins["BD_VERSION"]
        and revision is not None
        and pins["BD_COMMIT"].startswith(revision[1])
    )


def replace_link(target: Path, candidate: Path) -> None:
    # Nur das lokale Ziel ersetzen, nachdem der Kandidat geprüft wurde.
    with TemporaryDirectory(
        dir=target.parent, prefix=".bd-link-"
    ) as directory:
        link = Path(directory) / "bd"
        link.symlink_to(candidate.resolve())
        link.replace(target)


def install(target: Path, pins: dict[str, str], root: Path) -> None:
    # Gleiches Dateisystem für temporären Build und atomaren Austausch.
    with TemporaryDirectory(
        dir=target.parent, prefix=".bd-build-"
    ) as directory:
        work = Path(directory)
        source = work / "source"
        source.mkdir()
        run("git", ["init", "--quiet"], source, 10)
        run(
            "git",
            [
                "fetch",
                "--depth=1",
                pins["BD_REPOSITORY"],
                pins["BD_COMMIT"],
            ],
            source,
            120,
        )
        run(
            "git",
            ["checkout", "--quiet", "--detach", "FETCH_HEAD"],
            source,
            10,
        )
        revision = run("git", ["rev-parse", "HEAD"], source, 10).strip()
        if revision != pins["BD_COMMIT"]:
            raise ValueError(
                "Beads-Quellstand entspricht nicht BD_COMMIT."
            )
        binary = work / "bd"
        run(
            "go",
            [
                "build",
                "-tags",
                "gms_pure_go",
                "-ldflags",
                f"-X main.Build={revision[:7]} "
                f"-X main.Commit={revision}",
                "-o",
                str(binary),
                "./cmd/bd",
            ],
            source,
            1800,
            CGO_ENABLED="1",
        )
        if not matches(binary, pins, root):
            raise ValueError(
                "Gebautes bd entspricht nicht Version und Commit."
            )
        binary.replace(target)


def run(
    program: str, args: list[str], cwd: Path, timeout: int, **env: str
) -> str:
    """Prozessfehler ohne ungefilterte Fremdausgaben melden."""
    try:
        with local.cwd(cwd), local.env(**env):
            return local[program].run(
                args=args, retcode=0, timeout=timeout
            )[1]
    except CommandNotFound as exc:
        raise RuntimeError(f"Programm fehlt: {program}") from exc
    except ProcessTimedOut as exc:
        raise RuntimeError(
            f"Zeitgrenze überschritten: {program}"
        ) from exc
    except ProcessExecutionError as exc:
        raise RuntimeError(
            f"{program} fehlgeschlagen (Exit {exc.retcode})."
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"{program} konnte nicht gestartet werden "
            f"(errno {exc.errno})."
        ) from exc


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as error:
        print(f"Beads-Setup: {error}", file=sys.stderr)
        sys.exit(1)
