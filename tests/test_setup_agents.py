"""scripts/setup-agents.sh und make setup-agents: geprüfte Agenten-CLIs
nach .venv/bin, ohne Netz (npm-Double in einer Repo-Kopie)."""

from __future__ import annotations

import shutil
from pathlib import Path

from plumbum import local

from ki_dev.tool_versions import load_tool_versions

ROOT = Path(__file__).resolve().parents[1]

# Legt die beiden CLIs so an, wie npm sie installiert: Programme unter
# node_modules/.bin, die ihre Version melden.
_NPM = """#!/bin/sh
prefix="" ; packages=""
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) prefix="$2"; shift 2 ;;
    @openai/codex@*) codex="${1##*@}"; shift ;;
    @anthropic-ai/claude-code@*) claude="${1##*@}"; shift ;;
    *) shift ;;
  esac
done
echo install >>"$prefix.calls"
mkdir -p "$prefix/node_modules/.bin"
printf '#!/bin/sh\\necho "codex-cli %s"\\n' "$codex" \\
  >"$prefix/node_modules/.bin/codex"
printf '#!/bin/sh\\necho "%s (Claude Code)"\\n' "$claude" \\
  >"$prefix/node_modules/.bin/claude"
chmod +x "$prefix/node_modules/.bin/"*
"""


def _repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts/setup-agents.sh", repo / "scripts")
    venv_bin = repo / ".venv/bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").write_text("#!/bin/sh\n")
    (venv_bin / "python").chmod(0o755)
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "npm").write_text(_NPM)
    (tools / "npm").chmod(0o755)
    return repo, {"PATH": f"{tools}:/usr/bin:/bin"}


def _setup(repo: Path, env: dict[str, str], *versions: str):
    command = local["bash"][repo / "scripts/setup-agents.sh", *versions]
    with local.env(**env):
        return command.run(retcode=None)


def test_installs_pinned_versions_once(tmp_path):
    repo, env = _repo(tmp_path)
    code, out, err = _setup(repo, env, "0.164.0", "2.1.301")
    assert code == 0, err
    assert "codex 0.164.0 und claude 2.1.301" in out
    bin_dir = repo / ".venv/bin"
    assert local[bin_dir / "codex"]("--version") == (
        "codex-cli 0.164.0\n"
    )
    assert local[bin_dir / "claude"]("--version") == (
        "2.1.301 (Claude Code)\n"
    )
    # Zweiter Aufruf mit passendem Stand installiert nichts erneut.
    code, _, err = _setup(repo, env, "0.164.0", "2.1.301")
    assert code == 0, err
    calls = repo / ".venv/agents.calls"
    assert calls.read_text().splitlines() == ["install"]


def test_other_pin_reinstalls(tmp_path):
    repo, env = _repo(tmp_path)
    _setup(repo, env, "0.164.0", "2.1.301")
    code, _, err = _setup(repo, env, "0.165.0", "2.1.301")
    assert code == 0, err
    calls = repo / ".venv/agents.calls"
    assert calls.read_text().splitlines() == ["install", "install"]


def test_missing_npm_is_named(tmp_path):
    repo, _ = _repo(tmp_path)
    without_npm = tmp_path / "ohne-npm"
    without_npm.mkdir()
    (without_npm / "dirname").symlink_to(shutil.which("dirname"))
    code, _, err = _setup(
        repo, {"PATH": str(without_npm)}, "0.164.0", "2.1.301"
    )
    assert code != 0
    assert "npm fehlt" in err


def test_make_passes_versions_from_tool_versions():
    pins = load_tool_versions()
    out = local["make"]("-n", "-C", str(ROOT), "setup-agents")
    assert (
        f"scripts/setup-agents.sh "
        f"{pins['CODEX_VERSION']} {pins['CLAUDE_VERSION']}"
    ) in " ".join(out.replace("\\\n", " ").split())
