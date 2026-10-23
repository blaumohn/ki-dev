"""README und Anleitung aus readme-scripts/*.sh erzeugen (Vorbild:
lebenslauf-web-vorlage: scripts/gen-readme.py,
scripts/check-readme-en-sync.py).

Ein Skript ist ausführbar und zugleich Markdown: Zeilen, die mit ``#``
beginnen, werden Prosa (auch in einem HERE-Doc), die übrigen Zeilen
Code zwischen ``# ```bash`` und ``# ````. Codezeilen dürfen einen
Halbsatz als Zeilenend-Kommentar tragen (``  # …``); der
Befehlsvergleich DE/EN lässt ihn weg. README.md und die deutsche
Anleitung nehmen readme-scripts/*.sh; ihre englischen Fassungen nehmen
readme-scripts/en/*.sh. Jedes Skript steht genau einmal je Sprache:

    <!-- readme-script: readme-scripts/1-setup.sh -->
    …Prosa und bash-Block aus dem Skript…

    > ✅ Im leeren Container ausgeführt · [Test](tests/readme/…)

    ```text
    …Ausgabeblock…
    ```
    …Prosa aus dem Skript…
    <!-- /readme-script -->

Ein Skript enthält genau einen bash-Block. Statuszeile und Ausgabe
folgen direkt diesem Block und kommen aus make readme-check (Format:
scripts/readme_results.py), für Skripte mit eingechecktem Ergebnis
eines echten Laufs (make readme-live, docs/beispiele/echtlauf/) aus
diesem; die Statuszeile verlinkt den Test des
Skripts (tests/readme/test_<Name>.sh oder .py). Nur --write DIR setzt
sie aus DIR; ohne --write bleiben sie, wie sie im Dokument stehen, ein
neuer Block beginnt mit „nicht ausgeführt“. Direkt nach dem bash-Block
darf das Skript selbst keinen text-Block haben. Prosa-Links im Skript
gelten ab Repo-Wurzel; der Renderer passt sie an den Dokumentort an.

Standard schreibt abweichende Dokumente; --check meldet sie ohne
zu schreiben. --staged prüft zusätzlich, dass eine gestagte deutsche
Datei ihre englische Entsprechung mitbringt (pre-commit). Exit 1 bei
Abweichung, fehlendem Skript, Skript ohne Block, fehlender Übersetzung,
abweichenden Befehlen zwischen Deutsch und Englisch oder ungültigen
Ergebnissen.

    .venv/bin/python scripts/render-readme.py [--check] [--staged]
        [--write DIR]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from plumbum import local
from readme_results import LIVE_DIR, excerpt, load_results, status_line

ROOT = Path(__file__).resolve().parents[1]
DE_DIR = Path("readme-scripts")
EN_DIR = DE_DIR / "en"
VARIANTS = (
    ("README.md", DE_DIR),
    ("README.en.md", EN_DIR),
    ("docs/vertiefung.de.md", DE_DIR),
    ("docs/vertiefung.en.md", EN_DIR),
)
STRIP_PREFIX = re.compile(r"^# ?")
FENCE_MARKER = "```"
BASH_FENCE = "```bash"
TEXT_FENCE = "```text"
TESTS_DIR = Path("tests/readme")
TEST_SUFFIXES = (".sh", ".py")
LINE_COMMENT = re.compile(r"\s+# .*$")
TEST_LINK = re.compile(r" · \[[Tt]est\]\([^)]*\)$")
BLOCK = re.compile(
    r"^<!-- readme-script: (\S+) -->\n.*?^<!-- /readme-script -->$",
    re.MULTILINE | re.DOTALL,
)
LINK_TARGET = re.compile(r"(?<=\]\()([^\s)]+)(?=\))")


def main(argv: list[str]) -> int:
    args = parse_args(argv[1:])
    results = None
    if args.write is not None:
        results, problems = load_results(
            Path(args.write), section_names(DE_DIR)
        )
        if problems:
            return report(problems)
    live, problems = live_results()
    problems += coverage_problems()
    for scripts_dir in (DE_DIR, EN_DIR):
        problems += output_slot_problems(scripts_dir)
    if problems:
        return report(problems)
    for readme, _ in VARIANTS:
        problems += sync_readme(readme, args.check, results, live)
    problems += filename_parity_problems() + command_parity_problems()
    if args.staged:
        problems += staged_change_symmetry_problems()
    return report(problems)


def live_results() -> tuple[dict[str, list[dict]], list[str]]:
    """Eingecheckte Ergebnisse eines Laufs mit echten Agenten."""
    if not (ROOT / LIVE_DIR).is_dir():
        return {}, []
    return load_results(ROOT / LIVE_DIR, section_names(DE_DIR))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="render-readme.py")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--write", metavar="DIR")
    return parser.parse_args(argv)


def report(problems: list[str]) -> int:
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


def sync_readme(
    readme: str,
    check: bool,
    results: dict[str, list[dict]] | None,
    live: dict[str, list[dict]],
) -> list[str]:
    text = (ROOT / readme).read_text()
    problems = missing_scripts(readme, text)
    if problems:
        return problems

    def render(match: re.Match[str]) -> str:
        return render_block(match, readme, results, live, problems)

    rendered = BLOCK.sub(render, text)
    if problems or rendered == text:
        return problems
    if check:
        return [
            f"{readme}: weicht ab; "
            ".venv/bin/python scripts/render-readme.py ausführen"
        ]
    (ROOT / readme).write_text(rendered)
    return []


def coverage_problems() -> list[str]:
    """Jedes Skript genau einmal je Sprache, auch über Seiten hinweg."""
    problems = []
    for scripts_dir in (DE_DIR, EN_DIR):
        documents = [
            name for name, directory in VARIANTS
            if directory == scripts_dir
        ]
        used = []
        for name in documents:
            path = ROOT / name
            if not path.is_file():
                problems.append(f"{name}: Dokument fehlt")
                continue
            used += BLOCK.findall(path.read_text())
        for script in map(str, section_paths(scripts_dir)):
            if used.count(script) == 0:
                problems.append(
                    f"{documents[0]}: kein Block für {script}"
                )
            elif used.count(script) > 1:
                problems.append(f"{script}: mehrfach eingebunden")
    return problems


def missing_scripts(readme: str, text: str) -> list[str]:
    return [
        f"{readme}: Skript {script} fehlt"
        for script in BLOCK.findall(text)
        if not (ROOT / script).is_file()
    ]


def output_slot_problems(scripts_dir: Path) -> list[str]:
    problems = []
    for script in section_paths(scripts_dir):
        body = render_body((ROOT / script).read_text())
        if body.splitlines().count(BASH_FENCE) > 1:
            problems.append(
                f"{script}: mehrere bash-Blöcke; "
                "je Prüfabschnitt ein eigenes Skript verwenden"
            )
        if text_block_after_bash(body) is not None:
            problems.append(
                f"{script}: text-Block direkt nach dem letzten "
                "bash-Block ist der Ausgabe aus make readme-check "
                "vorbehalten"
            )
    return problems


def render_block(
    match: re.Match[str],
    readme: str,
    results: dict[str, list[dict]] | None,
    live: dict[str, list[dict]],
    problems: list[str],
) -> str:
    script = match.group(1)
    test = test_path(script)
    language = (
        "README.en.md" if readme.endswith(".en.md") else "README.md"
    )
    if Path(script).name in live:
        entries = live[Path(script).name]
        line = status_line(language, entries, test, live=True)
        output = excerpt(entries)
    elif results is None:
        line, output = kept_status(match.group(0), language, test)
    else:
        entries = results.get(Path(script).name)
        line = status_line(language, entries, test)
        output = excerpt(entries)
    body = relative_links(
        render_body((ROOT / script).read_text()), readme
    )
    line = relative_links(line, readme)
    if bash_close_index(body.split("\n")) is None:
        problems.append(f"{script}: kein bash-Block")
        return match.group(0)
    body = with_status(body, line, output)
    return (
        f"<!-- readme-script: {script} -->\n{body}"
        "<!-- /readme-script -->"
    )


def relative_links(text: str, document: str) -> str:
    """Skript-Prosa verlinkt ab Repo-Wurzel, Code bleibt unverändert."""
    def rebase(match: re.Match[str]) -> str:
        target = match.group(0)
        if re.match(r"(?:[a-z]+:|#|/)", target):
            return target
        path, separator, anchor = target.partition("#")
        relative = os.path.relpath(
            ROOT / path, (ROOT / document).parent
        )
        return relative + separator + anchor

    lines = []
    fenced = False
    for line in text.splitlines(keepends=True):
        if line.startswith(FENCE_MARKER):
            fenced = not fenced
        elif not fenced:
            line = LINK_TARGET.sub(rebase, line)
        lines.append(line)
    return "".join(lines)


def test_path(script: str) -> str | None:
    """Test des Skripts über den Dateinamen, wie tests/readme/lib.sh."""
    stem = Path(script).stem.replace("-", "_")
    for suffix in TEST_SUFFIXES:
        test = TESTS_DIR / f"test_{stem}{suffix}"
        if (ROOT / test).is_file():
            return test.as_posix()
    return None


def kept_status(
    block: str, readme: str, test: str | None
) -> tuple[str, list[str] | None]:
    """Statuszeile und Ausgabeblock, wie sie in der README stehen; der
    Testlink folgt dem aktuellen Dateinamen."""
    line, output = rendered_status(block)
    if line is None:
        return status_line(readme, None, test), output
    link = status_line(readme, None, test).removeprefix(
        status_line(readme, None)
    )
    return TEST_LINK.sub("", line) + link, output


def rendered_status(block: str) -> tuple[str | None, list[str] | None]:
    """Statuszeile und Ausgabe direkt nach dem letzten bash-Block."""
    lines = block.splitlines()
    close = bash_close_index(lines)
    if close is None:
        return None, None
    after = lines[close + 1 : close + 3]
    if len(after) == 2 and after[0] == "" and after[1].startswith("> "):
        return after[1], text_block_at(lines, close + 3)
    return None, text_block_at(lines, close + 1)


def with_status(body: str, line: str, output: list[str] | None) -> str:
    lines = body.split("\n")
    close = bash_close_index(lines)
    block = ["", line]
    if output:
        block += ["", TEXT_FENCE, *output, FENCE_MARKER]
    return "\n".join(lines[: close + 1] + block + lines[close + 1 :])


def text_block_after_bash(text: str) -> list[str] | None:
    lines = text.splitlines()
    close = bash_close_index(lines)
    return None if close is None else text_block_at(lines, close + 1)


def text_block_at(lines: list[str], index: int) -> list[str] | None:
    """Zeilen eines text-Blocks nach einer Leerzeile bei index."""
    if lines[index : index + 2] != ["", TEXT_FENCE]:
        return None
    start = index + 2
    end = lines.index(FENCE_MARKER, start)
    return lines[start:end]


def bash_close_index(lines: list[str]) -> int | None:
    """Index des schließenden Zauns des letzten bash-Blocks."""
    opening = [i for i, line in enumerate(lines) if line == BASH_FENCE]
    if not opening:
        return None
    return lines.index(FENCE_MARKER, opening[-1] + 1)


def render_body(text: str) -> str:
    lines = text.splitlines()
    stripped = (STRIP_PREFIX.sub("", line) for line in lines)
    return "\n".join(stripped) + "\n"


def filename_parity_problems() -> list[str]:
    de_names = section_names(DE_DIR)
    en_names = section_names(EN_DIR)
    missing = (
        f"{DE_DIR / n} hat keine Entsprechung in {EN_DIR}/"
        for n in de_names - en_names
    )
    orphaned = (
        f"{EN_DIR / n} ist verwaist (keine Entsprechung in {DE_DIR}/)"
        for n in en_names - de_names
    )
    return sorted(missing) + sorted(orphaned)


def command_parity_problems() -> list[str]:
    pairs = (
        (de, EN_DIR / de.name)
        for de in section_paths(DE_DIR)
        if (ROOT / EN_DIR / de.name).is_file()
    )
    return [
        f"{de} und {en}: Befehle weichen voneinander ab"
        for de, en in pairs
        if extract_commands(de) != extract_commands(en)
    ]


def extract_commands(script: Path) -> list[str]:
    body = render_body((ROOT / script).read_text())
    return [
        LINE_COMMENT.sub("", line).rstrip()
        for block in fenced_blocks(body)
        for line in block.splitlines()
        if line.strip()
    ]


def fenced_blocks(body: str) -> list[str]:
    lines = body.splitlines()
    fence_lines = [
        i
        for i, line in enumerate(lines)
        if line.strip().startswith(FENCE_MARKER)
    ]
    # Ungerade Zahl von Zäunen ist ein Fehler im Skript, kein Grenzfall.
    pairs = zip(fence_lines[0::2], fence_lines[1::2], strict=True)
    return ["\n".join(lines[start + 1 : end]) for start, end in pairs]


def staged_change_symmetry_problems() -> list[str]:
    staged = set(staged_files())
    de_changed = (path for path in staged if is_de_section(path))
    return sorted(
        f"{path} geändert, aber {en_counterpart(path)} "
        "nicht mit committet"
        for path in de_changed
        if en_counterpart(path) not in staged
    )


def staged_files() -> list[str]:
    output = local["git"].run(
        args=["-C", ROOT, "diff", "--cached", "--name-only"],
        retcode=0,
        timeout=10,
    )[1]
    return output.splitlines()


def is_de_section(path: str) -> bool:
    return Path(path).parent == DE_DIR and path.endswith(".sh")


def en_counterpart(path: str) -> str:
    return (EN_DIR / Path(path).name).as_posix()


def section_paths(directory: Path) -> list[Path]:
    return sorted(
        path.relative_to(ROOT)
        for path in (ROOT / directory).glob("*.sh")
    )


def section_names(directory: Path) -> set[str]:
    return {path.name for path in section_paths(directory)}


if __name__ == "__main__":
    sys.exit(main(sys.argv))
