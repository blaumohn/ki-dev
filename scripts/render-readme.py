"""README-Abschnitte aus readme-scripts/*.sh erzeugen (Vorbild:
lebenslauf-web-vorlage: scripts/gen-readme.py,
scripts/check-readme-en-sync.py).

Ein Skript ist ausführbar und zugleich Markdown: Zeilen, die mit ``#``
beginnen, werden Prosa (auch in einem HERE-Doc), die übrigen Zeilen
Code zwischen ``# ```bash`` und ``# ````. Codezeilen dürfen einen
Halbsatz als Zeilenend-Kommentar tragen (``  # …``); der
Befehlsvergleich DE/EN lässt ihn weg. README.md nimmt
readme-scripts/*.sh, README.en.md readme-scripts/en/*.sh:

    <!-- readme-script: readme-scripts/1-setup.sh -->
    …Prosa und bash-Block aus dem Skript…

    > ✅ Im leeren Container ausgeführt · [Test](tests/readme/…)

    ```text
    …Ausgabeblock…
    ```
    …Prosa aus dem Skript…
    <!-- /readme-script -->

Statuszeile und Ausgabeblock folgen direkt dem letzten bash-Block und
kommen aus einem Lauf von make readme-check (Format:
scripts/readme_results.py); die Statuszeile verlinkt den Test des
Skripts (tests/readme/test_<Name>.sh oder .py). Nur --write DIR setzt
sie aus DIR; ohne --write bleiben sie, wie sie in der README stehen, ein
neuer Block beginnt mit „nicht ausgeführt“. Direkt nach dem letzten
bash-Block darf das Skript selbst keinen text-Block haben.

Standard schreibt abweichende READMEs; --check meldet Abweichungen ohne
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
import re
import sys
from pathlib import Path

from plumbum import local
from readme_results import excerpt, load_results, status_line

ROOT = Path(__file__).resolve().parents[1]
DE_DIR = Path("readme-scripts")
EN_DIR = DE_DIR / "en"
VARIANTS = (("README.md", DE_DIR), ("README.en.md", EN_DIR))
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


def main(argv: list[str]) -> int:
    args = parse_args(argv[1:])
    results = None
    if args.write is not None:
        results, problems = load_results(
            Path(args.write), section_names(DE_DIR)
        )
        if problems:
            return report(problems)
    problems = []
    for readme, scripts_dir in VARIANTS:
        problems += sync_readme(
            readme, scripts_dir, args.check, results
        )
    problems += filename_parity_problems() + command_parity_problems()
    if args.staged:
        problems += staged_change_symmetry_problems()
    return report(problems)


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
    scripts_dir: Path,
    check: bool,
    results: dict[str, list[dict]] | None,
) -> list[str]:
    text = (ROOT / readme).read_text()
    problems = missing_blocks(readme, text, scripts_dir)
    problems += missing_scripts(readme, text)
    problems += output_slot_problems(scripts_dir)
    if problems:
        return problems

    def render(match: re.Match[str]) -> str:
        return render_block(match, readme, results, problems)

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


def missing_blocks(
    readme: str, text: str, scripts_dir: Path
) -> list[str]:
    used = set(BLOCK.findall(text))
    return [
        f"{readme}: kein Block für {script}"
        for script in sorted(map(str, section_paths(scripts_dir)))
        if script not in used
    ]


def missing_scripts(readme: str, text: str) -> list[str]:
    return [
        f"{readme}: Skript {script} fehlt"
        for script in BLOCK.findall(text)
        if not (ROOT / script).is_file()
    ]


def output_slot_problems(scripts_dir: Path) -> list[str]:
    return [
        f"{script}: text-Block direkt nach dem letzten bash-Block "
        "ist der Ausgabe aus make readme-check vorbehalten"
        for script in section_paths(scripts_dir)
        if text_block_after_bash(
            render_body((ROOT / script).read_text())
        )
        is not None
    ]


def render_block(
    match: re.Match[str],
    readme: str,
    results: dict[str, list[dict]] | None,
    problems: list[str],
) -> str:
    script = match.group(1)
    test = test_path(script)
    if results is None:
        line, output = kept_status(match.group(0), readme, test)
    else:
        entries = results.get(Path(script).name)
        line = status_line(readme, entries, test)
        output = excerpt(entries)
    body = render_body((ROOT / script).read_text())
    if bash_close_index(body.split("\n")) is None:
        problems.append(f"{script}: kein bash-Block")
        return match.group(0)
    body = with_status(body, line, output)
    return (
        f"<!-- readme-script: {script} -->\n{body}"
        "<!-- /readme-script -->"
    )


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
