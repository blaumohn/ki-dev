#!/usr/local/bin/python
"""Start agent CLIs with the container policy and model defaults.

The access policy (A) is mounted read-only, the model defaults (B)
read-write. Both are read and validated again on every regular call.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

SETTINGS_ROOT = Path("/opt/agent-settings")
POLICY_FILE = "policy.json"
CLIS = ("claude", "codex")

# Authentication and diagnostics keep their normal CLI behavior.
PASSTHROUGH = frozenset(
    {
        "--help",
        "-h",
        "--version",
        "-V",
        "login",
        "logout",
        "auth",
        "doctor",
    }
)

# Host sandbox options that the container isolation replaces.
SANDBOX_OPTIONS = (
    "--sandbox",
    "-s",
    "--ask-for-approval",
    "-a",
    "--permission-mode",
)
SANDBOX_FLAGS = frozenset(
    {
        "--full-auto",
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-skip-permissions",
    }
)
SANDBOX_CONFIG_KEYS = frozenset({"sandbox_mode", "approval_policy"})

CLAUDE_MODEL_KEYS = frozenset(
    {
        "model",
        "effortLevel",
        "modelSettings",
        "advisorModel",
        "language",
    }
)
CLAUDE_TEXT_KEYS = ("model", "advisorModel", "language")
CLAUDE_EFFORTS = frozenset({"low", "medium", "high", "xhigh"})
CODEX_MODEL_KEYS = frozenset({"model", "model_reasoning_effort"})

CONFIG_OPTIONS = ("-c", "--config")
GENERATED_NAME = re.compile(r"claude-(\d+)-[0-9a-f]+\.json")


class SettingsError(Exception):
    """An access policy or model default source is unusable."""


@dataclass(frozen=True)
class SettingsDirs:
    access: Path
    model: Path
    generated: Path

    @classmethod
    def under(cls, root: Path) -> SettingsDirs:
        return cls(root / "access", root / "model", root / "generated")


@dataclass(frozen=True)
class Option:
    index: int
    width: int
    name: str
    value: str


def main() -> None:
    name = Path(sys.argv[0]).name
    if (
        os.environ.get("KI_DEV_AGENT_CONTAINER") != "1"
        or not Path("/.dockerenv").exists()
    ):
        sys.exit("This launcher runs only inside the agent container.")
    try:
        args = build_args(
            name, sys.argv[1:], SettingsDirs.under(SETTINGS_ROOT)
        )
    except SettingsError as error:
        sys.exit(f"agent-cli: {error}")
    os.execv("/usr/local/bin/" + name, [name, *args])


def build_args(
    name: str, args: list[str], dirs: SettingsDirs
) -> list[str]:
    if name not in CLIS:
        raise SettingsError(f"unsupported CLI {name!r}")
    if any(arg in PASSTHROUGH for arg in args):
        return args
    policy = load_policy(dirs.access)[name]
    defaults = load_model_defaults(dirs.model, name)
    caller = remove_sandbox_options(args)
    if name == "codex":
        return codex_args(policy, defaults, caller)
    return claude_args(policy, defaults, caller, dirs.generated)


# --- Claude ---------------------------------------------------------


def claude_args(
    policy: dict, defaults: dict, args: list[str], generated: Path
) -> list[str]:
    # Only the generated file is loaded. User/project settings and their
    # hooks stay excluded although the host auth directory is mounted.
    if find_options(args, ("--settings", "--setting-sources")):
        raise SettingsError(
            "--settings/--setting-sources would replace the container "
            "policy; change the model defaults instead"
        )
    chosen = claude_caller_choices(args)
    settings = {**without_keys(defaults, chosen), **policy["settings"]}
    path = write_settings(generated, settings)
    return [
        "--dangerously-skip-permissions",
        "--setting-sources",
        "",
        "--settings",
        str(path),
        *args,
    ]


def claude_caller_choices(args: list[str]) -> set[str]:
    chosen = set()
    for option in find_options(args, ("--model", "--effort")):
        if option.name == "--model":
            chosen.add("model")
        else:
            chosen.update({"effortLevel", "modelSettings"})
    return chosen


def write_settings(directory: Path, settings: dict) -> Path:
    remove_stale_settings(directory)
    target = directory / (
        f"claude-{os.getpid()}-{secrets.token_hex(4)}.json"
    )
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=directory,
            prefix=".partial-",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        ) as handle:
            json.dump(settings, handle, indent=2)
        os.replace(handle.name, target)
    except OSError as error:
        raise SettingsError(
            f"cannot write settings to {directory}: {error}"
        ) from error
    return target


def remove_stale_settings(directory: Path) -> None:
    # A running CLI may reread its settings file, so only files of
    # finished launcher processes are removed.
    for path in directory.glob("claude-*.json"):
        match = GENERATED_NAME.fullmatch(path.name)
        if match and not process_alive(int(match.group(1))):
            path.unlink(missing_ok=True)


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# --- Codex ----------------------------------------------------------


def codex_args(
    policy: dict, defaults: dict, args: list[str]
) -> list[str]:
    config = policy["config"]
    caller = remove_config_keys(args, SANDBOX_CONFIG_KEYS)
    reject_codex_policy_overrides(config, caller)
    chosen = codex_caller_choices(caller)
    return [
        "--dangerously-bypass-approvals-and-sandbox",
        *config_overlay(config),
        *config_overlay(without_keys(defaults, chosen)),
        *caller,
    ]


def reject_codex_policy_overrides(
    config: dict, args: list[str]
) -> None:
    names = (*CONFIG_OPTIONS, "--enable", "--disable")
    for option in find_options(args, names):
        if option.name in CONFIG_OPTIONS:
            key = config_key(option.value)
        else:
            key = f"features.{option.value}"
        if key in config:
            raise SettingsError(
                f"{option.name} {option.value} conflicts with the "
                f"access policy key {key!r}"
            )


def codex_caller_choices(args: list[str]) -> set[str]:
    # A profile or local provider selects its own model setup.
    if "--oss" in leading_args(args):
        return set(CODEX_MODEL_KEYS)
    chosen = set()
    names = ("-m", "--model", "-p", "--profile", *CONFIG_OPTIONS)
    for option in find_options(args, names):
        if option.name in {"-m", "--model"}:
            chosen.add("model")
        elif option.name in {"-p", "--profile"}:
            chosen.update(CODEX_MODEL_KEYS)
        elif config_key(option.value) in CODEX_MODEL_KEYS:
            chosen.add(config_key(option.value))
    return chosen


def remove_config_keys(args: list[str], keys: frozenset) -> list[str]:
    options = [
        option
        for option in find_options(args, CONFIG_OPTIONS)
        if config_key(option.value) in keys
    ]
    return remove_spans(args, options)


def config_overlay(values: dict) -> list[str]:
    pairs = []
    for key, value in values.items():
        pairs.extend(["-c", f"{key}={toml_value(value)}"])
    return pairs


def config_key(assignment: str) -> str:
    return assignment.partition("=")[0].strip()


def toml_value(value: bool | int | str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    # JSON string escapes are a subset of TOML basic string escapes.
    return json.dumps(value, ensure_ascii=False)


# --- Argument handling ----------------------------------------------


def remove_sandbox_options(args: list[str]) -> list[str]:
    kept = remove_spans(args, find_options(args, SANDBOX_OPTIONS))
    leading = leading_args(kept)
    return [arg for arg in leading if arg not in SANDBOX_FLAGS] + kept[
        len(leading) :
    ]


def find_options(
    args: list[str], names: tuple[str, ...]
) -> list[Option]:
    """Find ``NAME VALUE`` or ``NAME=VALUE`` options before ``--``."""
    found = []
    index = 0
    end = len(leading_args(args))
    while index < end:
        option = read_option(args, index, names)
        if option is None:
            index += 1
            continue
        found.append(option)
        index += option.width
    return found


def read_option(
    args: list[str], index: int, names: tuple[str, ...]
) -> Option | None:
    arg = args[index]
    name, separator, value = arg.partition("=")
    if name not in names:
        return None
    if separator:
        return Option(index, 1, name, value)
    if index + 1 < len(args):
        return Option(index, 2, name, args[index + 1])
    return Option(index, 1, name, "")


def remove_spans(args: list[str], options: list[Option]) -> list[str]:
    dropped = {
        index
        for option in options
        for index in range(option.index, option.index + option.width)
    }
    return [
        arg for index, arg in enumerate(args) if index not in dropped
    ]


def leading_args(args: list[str]) -> list[str]:
    return args[: args.index("--")] if "--" in args else args


def without_keys(values: dict, keys: set[str]) -> dict:
    return {
        key: value for key, value in values.items() if key not in keys
    }


# --- Access policy (A) ----------------------------------------------


def load_policy(access_dir: Path) -> dict:
    path = access_dir / POLICY_FILE
    policy = read_json_object(path)
    check_exact_keys(path, "policy", policy, {"claude", "codex"})
    claude = policy["claude"]
    check_exact_keys(path, "claude", claude, {"settings"})
    check_policy_section(
        path, "claude.settings", claude["settings"], CLAUDE_MODEL_KEYS
    )
    codex = policy["codex"]
    check_exact_keys(path, "codex", codex, {"config"})
    check_policy_section(
        path, "codex.config", codex["config"], CODEX_MODEL_KEYS
    )
    for key, value in codex["config"].items():
        if not isinstance(value, bool | int | str):
            raise SettingsError(
                f"{path}: codex.config.{key} must be a boolean, "
                "integer or string"
            )
    return policy


def check_policy_section(
    path: Path, label: str, section: object, model_keys: frozenset
) -> None:
    if not isinstance(section, dict):
        raise SettingsError(f"{path}: {label} must be an object")
    overlap = sorted(model_keys & section.keys())
    if overlap:
        raise SettingsError(
            f"{path}: {label} must not set model defaults {overlap}"
        )


# --- Model defaults (B) ---------------------------------------------


def load_model_defaults(model_dir: Path, name: str) -> dict:
    path = model_dir / f"{name}.json"
    defaults = read_json_object(path)
    if name == "codex":
        check_allowed_keys(path, defaults, CODEX_MODEL_KEYS)
        for key, value in defaults.items():
            check_text(path, key, value)
        return defaults
    check_allowed_keys(path, defaults, CLAUDE_MODEL_KEYS)
    for key in CLAUDE_TEXT_KEYS:
        if key in defaults:
            check_text(path, key, defaults[key])
    if "effortLevel" in defaults:
        check_effort(path, "effortLevel", defaults["effortLevel"])
    if "modelSettings" in defaults:
        check_model_settings(path, defaults["modelSettings"])
    return defaults


def check_model_settings(path: Path, model_settings: object) -> None:
    if not isinstance(model_settings, dict):
        raise SettingsError(f"{path}: modelSettings must be an object")
    for model, entry in model_settings.items():
        label = f"modelSettings.{model}"
        if not isinstance(entry, dict):
            raise SettingsError(f"{path}: {label} must be an object")
        check_allowed_keys(path, entry, {"effortLevel"})
        if "effortLevel" in entry:
            check_effort(
                path, f"{label}.effortLevel", entry["effortLevel"]
            )


def check_effort(path: Path, label: str, value: object) -> None:
    if value not in CLAUDE_EFFORTS:
        raise SettingsError(
            f"{path}: {label} must be one of {sorted(CLAUDE_EFFORTS)}"
        )


def check_text(path: Path, label: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SettingsError(
            f"{path}: {label} must be a non-empty string"
        )


# --- JSON sources ---------------------------------------------------


def read_json_object(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SettingsError(f"cannot read {path}: {error}") from error
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise SettingsError(f"{path}: invalid JSON: {error}") from error
    if not isinstance(data, dict):
        raise SettingsError(f"{path}: expected a JSON object")
    return data


def check_exact_keys(
    path: Path, label: str, section: object, keys: set[str]
) -> None:
    if not isinstance(section, dict) or section.keys() != keys:
        raise SettingsError(
            f"{path}: {label} must be an object with keys "
            f"{sorted(keys)}"
        )


def check_allowed_keys(path: Path, values: dict, keys: set) -> None:
    unknown = sorted(values.keys() - keys)
    if unknown:
        raise SettingsError(
            f"{path}: unsupported keys {unknown}; "
            f"allowed: {sorted(keys)}"
        )


if __name__ == "__main__":
    main()
