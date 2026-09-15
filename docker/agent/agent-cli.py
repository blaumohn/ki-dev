#!/usr/local/bin/python
"""Use Docker's isolation when loope supplies restrictive agent CLI flags."""
import os
from pathlib import Path
import sys

CLAUDE_SETTINGS = "/home/agent/.claude/settings.json"


def rewrite_args(name: str, args: list[str]) -> list[str]:
    """Replace host sandbox flags with the container's isolation policy."""
    # Authentication and diagnostics should retain their normal CLI behavior.
    passthrough = {"--help", "-h", "--version", "-V", "login", "logout", "auth", "doctor"}
    if any(arg in passthrough for arg in args):
        return args

    options = {"--sandbox", "-s", "--ask-for-approval", "-a", "--permission-mode"}
    filtered = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            filtered.extend(args[index:])
            break
        if arg in options:
            index += 2
            continue
        if any(arg.startswith(option + "=") for option in options):
            index += 1
            continue
        if arg not in {"--full-auto", "--dangerously-bypass-approvals-and-sandbox",
                       "--dangerously-skip-permissions"}:
            filtered.append(arg)
        index += 1
    if name == "codex":
        return ["--dangerously-bypass-approvals-and-sandbox", "-c", "features.hooks=false", *filtered]

    # Load only the container policy file. User/project settings and their hooks
    # stay excluded even though the host auth directory is mounted.
    return [
        "--dangerously-skip-permissions",
        "--setting-sources",
        "",
        "--settings",
        CLAUDE_SETTINGS,
        *filtered,
    ]


def main() -> None:
    name = Path(sys.argv[0]).name
    args = sys.argv[1:]
    if os.environ.get("KI_DEV_AGENT_CONTAINER") != "1" or not Path("/.dockerenv").exists():
        sys.exit("This launcher runs only inside the agent Docker container.")

    args = rewrite_args(name, args)
    os.execv("/usr/local/bin/" + name, [name, *args])


if __name__ == "__main__":
    main()
