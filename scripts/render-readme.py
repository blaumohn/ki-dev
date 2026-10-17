"""README-Abschnitte aus readme-scripts/*.sh erzeugen (Vorbild:
lebenslauf-web-vorlage: scripts/gen-readme.py,
scripts/check-readme-en-sync.py).

Ein Skript ist ausführbar und zugleich Markdown: ``# ``-Zeilen werden
Prosa, die übrigen Zeilen Code zwischen ``# ```bash`` und ``# ````.
Codezeilen tragen keine Kommentare; Erklärungen stehen als Prosa davor.
README.md nimmt readme-scripts/*.sh, README.en.md
readme-scripts/en/*.sh:

    <!-- readme-script: readme-scripts/1-setup.sh -->
    …erzeugt…
    <!-- /readme-script -->

Standard schreibt abweichende READMEs; --check meldet Abweichungen ohne
zu schreiben. --staged prüft zusätzlich, dass eine gestagte deutsche
Datei ihre englische Entsprechung mitbringt (pre-commit). Exit 1 bei
Abweichung, fehlendem Skript, Skript ohne Block, fehlender Übersetzung
oder abweichenden Befehlen zwischen Deutsch und Englisch.

Jeder Block beginnt mit einer Statuszeile aus readme-scripts/status.toml
(eine Quelle für DE und EN, Schlüssel = Skriptname):

    ["1-setup.sh"]
    status = "passed"   # passed | xfail | unchecked | draft
    date = "2026-10-16" # Pflicht bei passed und xfail
    command = "make demo"

Die Zeile beschreibt nur den Funktionslauf, nicht die Synchronisierung.
``draft`` braucht keinen Block (Hinweis ``[i]`` auf stderr, Exit 0);
ein Entwurf mit Block, ein Skript ohne Eintrag, ein Eintrag ohne Skript,
ein unbekannter status oder passed/xfail ohne date ergeben Exit 1.

    .venv/bin/python scripts/render-readme.py [--check] [--staged]
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from plumbum import local

ROOT = Path(__file__).resolve().parents[1]
DE_DIR = Path("readme-scripts")
EN_DIR = DE_DIR / "en"
VARIANTS = (("README.md", DE_DIR), ("README.en.md", EN_DIR))
STATUS_FILE = DE_DIR / "status.toml"
STATUSES = ("passed", "xfail", "unchecked", "draft")
DATED = ("passed", "xfail")
STATUS_TEXT = {
    "README.md": {
        "verify": "selbst prüfen",
        "bench": "[Stand](#stand)",
        "passed": "✅ bestanden",
        "xfail": "❌ rot, erwartet (Spezifikation)",
        "unchecked": "nicht ausgeführt",
    },
    "README.en.md": {
        "verify": "verify",
        "bench": "[Status](#status)",
        "passed": "✅ passed",
        "xfail": "❌ red, expected (spec)",
        "unchecked": "not run",
    },
}
STRIP_PREFIX = re.compile(r"^# ?")
FENCE_MARKER = "```"
BLOCK = re.compile(
    r"^<!-- readme-script: (\S+) -->\n.*?^<!-- /readme-script -->$",
    re.MULTILINE | re.DOTALL,
)


def main(argv: list[str]) -> int:
    check = "--check" in argv[1:]
    statuses, problems = load_statuses()
    if problems:
        return report(problems)
    for readme, scripts_dir in VARIANTS:
        problems += sync_readme(readme, scripts_dir, check, statuses)
    problems += filename_parity_problems() + command_parity_problems()
    if "--staged" in argv[1:]:
        problems += staged_change_symmetry_problems()
    return report(problems)


def report(problems: list[str]) -> int:
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


def load_statuses() -> tuple[dict[str, dict], list[str]]:
    path = ROOT / STATUS_FILE
    if not path.is_file():
        return {}, [f"{STATUS_FILE} fehlt"]
    statuses = tomllib.loads(path.read_text())
    names = section_names(DE_DIR)
    problems = [
        f"{STATUS_FILE}: kein Eintrag für {DE_DIR / name}"
        for name in sorted(names - statuses.keys())
    ]
    problems += [
        f"{STATUS_FILE}: Eintrag {name} ohne Skript in {DE_DIR}/"
        for name in sorted(statuses.keys() - names)
    ]
    for name, entry in sorted(statuses.items()):
        problems += entry_problems(name, entry)
    return statuses, problems


def entry_problems(name: str, entry: dict) -> list[str]:
    status = entry.get("status")
    if status not in STATUSES:
        return [f"{STATUS_FILE}: {name}: unbekannter status {status!r}"]
    problems = []
    if status in DATED and not entry.get("date"):
        problems.append(f"{STATUS_FILE}: {name}: {status} ohne date")
    if status != "draft" and not entry.get("command"):
        problems.append(f"{STATUS_FILE}: {name}: {status} ohne command")
    return problems


def is_draft(statuses: dict[str, dict], script: Path | str) -> bool:
    entry = statuses.get(Path(script).name, {})
    return entry.get("status") == "draft"


def status_line(readme: str, entry: dict) -> str:
    text = STATUS_TEXT[readme]
    status = entry["status"]
    parts = [text[status]]
    if status in DATED:
        parts.append(entry["date"])
    parts.append(f"{text['verify']}: {entry['command']}")
    if status == "xfail":
        parts.append(text["bench"])
    return "> " + " · ".join(parts)


def sync_readme(
    readme: str,
    scripts_dir: Path,
    check: bool,
    statuses: dict[str, dict],
) -> list[str]:
    text = (ROOT / readme).read_text()
    problems = missing_blocks(readme, text, scripts_dir, statuses)
    problems += missing_scripts(readme, text)
    problems += draft_block_problems(readme, text, statuses)
    if problems:
        return problems

    def render(match: re.Match[str]) -> str:
        return render_block(match, readme, statuses)

    rendered = BLOCK.sub(render, text)
    if rendered == text:
        return []
    if check:
        return [
            f"{readme}: weicht ab; "
            ".venv/bin/python scripts/render-readme.py ausführen"
        ]
    (ROOT / readme).write_text(rendered)
    return []


def missing_blocks(
    readme: str,
    text: str,
    scripts_dir: Path,
    statuses: dict[str, dict],
) -> list[str]:
    used = set(BLOCK.findall(text))
    problems = []
    for script in sorted(map(str, section_paths(scripts_dir))):
        if script in used:
            continue
        if is_draft(statuses, script):
            note = f"[i] {script}: Entwurf, übersprungen"
            print(note, file=sys.stderr)
        else:
            problems.append(f"{readme}: kein Block für {script}")
    return problems


def draft_block_problems(
    readme: str, text: str, statuses: dict[str, dict]
) -> list[str]:
    return [
        f"{readme}: Entwurf {script} darf keinen Block haben"
        for script in BLOCK.findall(text)
        if is_draft(statuses, script)
    ]


def missing_scripts(readme: str, text: str) -> list[str]:
    return [
        f"{readme}: Skript {script} fehlt"
        for script in BLOCK.findall(text)
        if not (ROOT / script).is_file()
    ]


def render_block(
    match: re.Match[str], readme: str, statuses: dict[str, dict]
) -> str:
    script = match.group(1)
    line = status_line(readme, statuses[Path(script).name])
    body = render_body((ROOT / script).read_text())
    return (
        f"<!-- readme-script: {script} -->\n{line}\n\n{body}"
        "<!-- /readme-script -->"
    )


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
        line.rstrip()
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
