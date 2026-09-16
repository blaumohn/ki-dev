from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from ki_dev.executors.claude_cli import ClaudeCliAdapter
from ki_dev.executors.codex_cli import CodexCliAdapter
from ki_dev.executors.contract import Effort, TurnRequest

REPO = Path(__file__).parents[1]
REPO_SETTINGS = REPO / "docker" / "agent-settings"

CLAUDE_DEFAULTS = {
    "model": "sonnet",
    "effortLevel": "high",
    "modelSettings": {"claude-opus-5": {"effortLevel": "xhigh"}},
    "advisorModel": "opus",
    "language": "German",
}
CODEX_DEFAULTS = {"model": "gpt-b", "model_reasoning_effort": "low"}
POLICY = {
    "claude": {
        "settings": {
            "skipDangerousModePermissionPrompt": True,
            "disableAllHooks": True,
        }
    },
    "codex": {"config": {"features.hooks": False}},
}


def _load_agent_cli():
    path = REPO / "docker" / "agent" / "agent_cli.py"
    spec = importlib.util.spec_from_file_location("agent_cli", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


agent_cli = _load_agent_cli()


@pytest.fixture
def dirs(tmp_path):
    settings = agent_cli.SettingsDirs.under(tmp_path)
    for directory in (
        settings.access,
        settings.model,
        settings.generated,
    ):
        directory.mkdir()
    _replace_json(settings.access / "policy.json", POLICY)
    _replace_json(settings.model / "claude.json", CLAUDE_DEFAULTS)
    _replace_json(settings.model / "codex.json", CODEX_DEFAULTS)
    return settings


def _replace_json(path: Path, data: object) -> None:
    # Editors save atomically: write a sibling file, then rename it.
    partial = path.with_name(path.name + ".tmp")
    partial.write_text(json.dumps(data), encoding="utf-8")
    os.replace(partial, path)


def _claude_settings(args: list[str]) -> dict:
    assert args[:4] == [
        "--dangerously-skip-permissions",
        "--setting-sources",
        "",
        "--settings",
    ]
    return json.loads(Path(args[4]).read_text(encoding="utf-8"))


def _codex_overlay(args: list[str]) -> dict:
    overlay = {}
    for index, arg in enumerate(args):
        if arg == "-c":
            overlay.update(tomllib.loads(args[index + 1]))
    return overlay


# --- Claude ---------------------------------------------------------


def test_claude_loads_only_generated_settings(dirs):
    args = agent_cli.build_args("claude", ["--print", "Hallo"], dirs)

    assert Path(args[4]).parent == dirs.generated
    assert args[5:] == ["--print", "Hallo"]
    assert _claude_settings(args) == {
        **CLAUDE_DEFAULTS,
        **POLICY["claude"]["settings"],
    }


def test_interactive_claude_gets_settings(dirs):
    args = agent_cli.build_args("claude", [], dirs)

    assert len(args) == 5
    assert _claude_settings(args)["model"] == "sonnet"


def test_claude_diagnostics_passthrough(tmp_path):
    missing = agent_cli.SettingsDirs.under(tmp_path / "missing")

    args = agent_cli.build_args("claude", ["auth", "status"], missing)

    assert args == ["auth", "status"]


@pytest.mark.parametrize(
    ("name", "caller"),
    [
        ("claude", ["login"]),
        ("claude", ["auth", "status"]),
        ("claude", ["--help"]),
        ("claude", ["--version"]),
        ("codex", ["doctor"]),
        ("codex", ["logout"]),
        ("codex", ["-h"]),
    ],
)
def test_diagnostics_passthrough_at_command_position(
    tmp_path, name, caller
):
    missing = agent_cli.SettingsDirs.under(tmp_path / "missing")

    args = agent_cli.build_args(name, caller, missing)

    assert args == caller


@pytest.mark.parametrize(
    ("name", "caller"),
    [
        # "login"/"doctor" is a value here, not the subcommand: the
        # launcher must still apply A/B, not pass the call through
        # as-is.
        ("claude", ["-p", "login"]),
        ("codex", ["exec", "doctor"]),
        # "--" marks the end of launcher-relevant args; a literal
        # "--help" after it is not a top-level flag.
        ("codex", ["exec", "--", "--help"]),
    ],
)
def test_keyword_outside_command_position_is_not_passthrough(
    dirs, name, caller
):
    args = agent_cli.build_args(name, caller, dirs)

    assert args != caller
    assert args[-len(caller) :] == caller


def test_claude_filters_host_sandbox_flags(dirs):
    args = agent_cli.build_args(
        "claude",
        ["--permission-mode", "plan", "-p", "--", "--permission-mode"],
        dirs,
    )

    assert args[5:] == ["-p", "--", "--permission-mode"]


@pytest.mark.parametrize(
    ("caller", "removed"),
    [
        (["--model", "opus"], {"model"}),
        (["--model=opus"], {"model"}),
        (["--effort", "low"], {"effortLevel", "modelSettings"}),
        (["--effort=max"], {"effortLevel", "modelSettings"}),
    ],
)
def test_claude_caller_values_beat_defaults(dirs, caller, removed):
    args = agent_cli.build_args("claude", caller, dirs)

    settings = _claude_settings(args)
    assert args[5:] == caller
    assert removed.isdisjoint(settings)
    assert set(CLAUDE_DEFAULTS) - removed <= set(settings)


@pytest.mark.parametrize(
    "caller",
    [
        ["--settings", '{"hooks": {}}'],
        ["--settings=/tmp/other.json"],
        ["--setting-sources", "user,project"],
    ],
)
def test_claude_rejects_extra_settings(dirs, caller):
    with pytest.raises(agent_cli.SettingsError, match="--settings"):
        agent_cli.build_args("claude", caller, dirs)

    assert list(dirs.generated.iterdir()) == []


def test_claude_calls_get_separate_files(dirs):
    first = agent_cli.build_args("claude", [], dirs)
    _replace_json(
        dirs.model / "claude.json", {**CLAUDE_DEFAULTS, "model": "opus"}
    )
    second = agent_cli.build_args("claude", [], dirs)

    assert first[4] != second[4]
    assert _claude_settings(first)["model"] == "sonnet"
    assert _claude_settings(second)["model"] == "opus"


def test_claude_removes_files_of_ended_runs(dirs):
    with subprocess.Popen([sys.executable, "-c", "pass"]) as finished:
        finished.wait()
    stale = dirs.generated / f"claude-{finished.pid}-abcd.json"
    running = dirs.generated / f"claude-{os.getpid()}-abcd.json"
    stale.write_text("{}", encoding="utf-8")
    running.write_text("{}", encoding="utf-8")

    agent_cli.build_args("claude", [], dirs)

    assert not stale.exists()
    assert running.exists()


# --- Codex ----------------------------------------------------------


def test_codex_uses_native_config_overlay(dirs):
    args = agent_cli.build_args(
        "codex", ["exec", "--sandbox", "read-only", "-"], dirs
    )

    assert args[0] == "--dangerously-bypass-approvals-and-sandbox"
    assert args[-2:] == ["exec", "-"]
    assert _codex_overlay(args) == {
        "features": {"hooks": False},
        **CODEX_DEFAULTS,
    }
    assert list(dirs.generated.iterdir()) == []


@pytest.mark.parametrize(
    ("caller", "removed"),
    [
        (["-m", "gpt-x"], {"model"}),
        (["--model=gpt-x"], {"model"}),
        (["-c", 'model="gpt-x"'], {"model"}),
        (
            ["--config=model_reasoning_effort=high"],
            {"model_reasoning_effort"},
        ),
        (
            ["-c", "model_reasoning_effort = 'high'"],
            {"model_reasoning_effort"},
        ),
        (["--profile", "fast"], {"model", "model_reasoning_effort"}),
        (["--oss"], {"model", "model_reasoning_effort"}),
    ],
)
def test_codex_caller_values_beat_defaults(dirs, caller, removed):
    args = agent_cli.build_args("codex", ["exec", *caller, "-"], dirs)

    assert args[-len(caller) - 2 :] == ["exec", *caller, "-"]
    default_args = args[: -len(caller) - 2]
    overlay = _codex_overlay(default_args)
    assert removed.isdisjoint(overlay)
    assert set(CODEX_DEFAULTS) - removed <= set(overlay)


@pytest.mark.parametrize(
    "caller",
    [
        ["-c", "features.hooks=true"],
        ["--config=features.hooks=true"],
        ["--enable", "hooks"],
        ["--disable=hooks"],
        # Inline table, quoted keys and dotted spacing all resolve to
        # the same path as the plain dotted-key spelling above.
        ["-c", "features={hooks=true}"],
        ["-c", '"features"."hooks"=true'],
        ["-c", "features . hooks = true"],
        ["-c", 'features."hooks"=true'],
    ],
)
def test_codex_rejects_policy_overrides(dirs, caller):
    with pytest.raises(agent_cli.SettingsError, match="features.hooks"):
        agent_cli.build_args("codex", ["exec", *caller], dirs)


@pytest.mark.parametrize(
    "caller",
    [
        # A dotted-key assignment only ever addresses its own leaf; it
        # must not be rejected merely for sharing the "features"
        # parent with the protected "features.hooks".
        ["-c", "features.web_search=false"],
        ["--config=features.other_key=true"],
        # A quoted key may itself contain a literal ".": the whole
        # quoted string is one segment, unrelated to the two-segment
        # features.hooks path, and must neither crash nor be flagged.
        ["-c", '"features.hooks"=true'],
        ["-c", 'features."guardianv2.thread_context"=true'],
    ],
)
def test_codex_allows_sibling_feature_overrides(dirs, caller):
    args = agent_cli.build_args("codex", ["exec", *caller], dirs)

    assert args[-len(caller) - 1 :] == ["exec", *caller]


def test_codex_rejects_invalid_config_key(dirs):
    with pytest.raises(agent_cli.SettingsError, match="invalid -c"):
        agent_cli.build_args(
            "codex", ["exec", "-c", "invalid key=value"], dirs
        )


def test_codex_drops_sandbox_config(dirs):
    caller = [
        "exec",
        "-c",
        "sandbox_mode=read-only",
        "--config=approval_policy=never",
        "-a",
        "on-request",
        "--full-auto",
        "-c",
        "tui.theme=dark",
        "-",
    ]

    args = agent_cli.build_args("codex", caller, dirs)

    assert args[-4:] == ["exec", "-c", "tui.theme=dark", "-"]


def test_codex_rereads_defaults_per_call(dirs):
    first = agent_cli.build_args("codex", ["exec", "-"], dirs)
    _replace_json(dirs.model / "codex.json", {"model": "gpt-neu"})
    second = agent_cli.build_args("codex", ["exec", "-"], dirs)

    assert _codex_overlay(first)["model"] == "gpt-b"
    assert _codex_overlay(second) == {
        "features": {"hooks": False},
        "model": "gpt-neu",
    }


def test_codex_encodes_toml_strings(dirs):
    model = 'a"b\\c\nd ä'
    _replace_json(dirs.model / "codex.json", {"model": model})

    args = agent_cli.build_args("codex", ["exec"], dirs)

    assert _codex_overlay(args)["model"] == model


# --- ki-dev adapters ------------------------------------------------


def test_ki_dev_turn_values_beat_defaults(dirs):
    request = TurnRequest(
        session_id="s-1",
        message="m",
        model="haiku",
        effort=Effort.LOW,
        workdir=Path("/work"),
    )

    claude = agent_cli.build_args(
        "claude", ClaudeCliAdapter().build_argv(request), dirs
    )
    codex = agent_cli.build_args(
        "codex", CodexCliAdapter().build_argv(request), dirs
    )

    settings = _claude_settings(claude)
    assert {"model", "effortLevel", "modelSettings"}.isdisjoint(
        settings
    )
    assert claude[5:] == ClaudeCliAdapter().build_argv(request)
    codex_defaults = codex[
        : -len(CodexCliAdapter().build_argv(request))
    ]
    assert _codex_overlay(codex_defaults) == {
        "features": {"hooks": False}
    }


# --- Invalid sources ------------------------------------------------


@pytest.mark.parametrize(
    ("file_name", "content", "message"),
    [
        ("claude.json", "{", "invalid JSON"),
        ("claude.json", "[]", "expected a JSON object"),
        ("claude.json", '{"hooks": {}}', "unsupported keys"),
        ("claude.json", '{"effortLevel": "max"}', "effortLevel"),
        # Unhashable JSON types must not reach the frozenset membership
        # check with a bare TypeError; they fail the same as any other
        # invalid value.
        ("claude.json", '{"effortLevel": []}', "effortLevel"),
        ("claude.json", '{"effortLevel": {}}', "effortLevel"),
        (
            "claude.json",
            '{"modelSettings": {"opus": {"effortLevel": []}}}',
            "effortLevel",
        ),
        ("claude.json", '{"model": ""}', "model"),
        (
            "claude.json",
            '{"modelSettings": {"opus": {"maxEffortLevel": "low"}}}',
            "unsupported keys",
        ),
        ("codex.json", '{"sandbox_mode": "read-only"}', "unsupported"),
        ("codex.json", '{"model": 5}', "model"),
    ],
)
def test_invalid_model_defaults_fail(dirs, file_name, content, message):
    (dirs.model / file_name).write_text(content, encoding="utf-8")
    name = file_name.removesuffix(".json")

    with pytest.raises(agent_cli.SettingsError, match=message):
        agent_cli.build_args(name, [], dirs)

    assert list(dirs.generated.iterdir()) == []


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        ({"claude": POLICY["claude"]}, "policy must be an object"),
        (
            {**POLICY, "claude": {"settings": {"model": "opus"}}},
            "unsupported keys",
        ),
        (
            {**POLICY, "codex": {"config": {"model": "gpt"}}},
            "unsupported keys",
        ),
        (
            {
                **POLICY,
                "codex": {"config": {"features.hooks": {"x": 1}}},
            },
            "boolean, integer or string",
        ),
        # An empty section is structurally an object, but it drops the
        # execution policy the bead requires (hooks stay disabled).
        (
            {**POLICY, "claude": {"settings": {}}},
            "disableAllHooks must be true",
        ),
        (
            {
                **POLICY,
                "claude": {
                    "settings": {
                        "skipDangerousModePermissionPrompt": True,
                        "disableAllHooks": False,
                    }
                },
            },
            "disableAllHooks must be true",
        ),
        (
            {
                **POLICY,
                "claude": {
                    "settings": {
                        "skipDangerousModePermissionPrompt": False,
                        "disableAllHooks": True,
                    }
                },
            },
            "skipDangerousModePermissionPrompt must be true",
        ),
        (
            {
                **POLICY,
                "claude": {
                    "settings": {
                        "skipDangerousModePermissionPrompt": [],
                        "disableAllHooks": True,
                    }
                },
            },
            "skipDangerousModePermissionPrompt must be true",
        ),
        (
            {
                **POLICY,
                "claude": {
                    "settings": {
                        "skipDangerousModePermissionPrompt": "yes",
                        "disableAllHooks": True,
                    }
                },
            },
            "skipDangerousModePermissionPrompt must be true",
        ),
        (
            {
                **POLICY,
                "claude": {
                    "settings": {
                        "skipDangerousModePermissionPrompt": True,
                        "disableAllHooks": True,
                        "features.hooks": True,
                    }
                },
            },
            "unsupported keys",
        ),
        ({**POLICY, "codex": {"config": {}}}, "must be false"),
        (
            {**POLICY, "codex": {"config": {"features.hooks": True}}},
            "must be false",
        ),
    ],
)
def test_invalid_policy_fails(dirs, policy, message):
    _replace_json(dirs.access / "policy.json", policy)

    with pytest.raises(agent_cli.SettingsError, match=message):
        agent_cli.build_args("claude", [], dirs)


def test_missing_source_fails(dirs):
    (dirs.model / "codex.json").unlink()

    with pytest.raises(agent_cli.SettingsError, match="cannot read"):
        agent_cli.build_args("codex", ["exec"], dirs)


# --- Repository sources ---------------------------------------------


def test_repository_sources_are_valid(tmp_path):
    shutil.copytree(REPO_SETTINGS, tmp_path, dirs_exist_ok=True)
    (tmp_path / "generated").mkdir()
    dirs = agent_cli.SettingsDirs.under(tmp_path)

    claude = agent_cli.build_args("claude", [], dirs)
    codex = agent_cli.build_args("codex", ["exec"], dirs)

    assert _claude_settings(claude)["disableAllHooks"] is True
    assert _codex_overlay(codex)["features"] == {"hooks": False}


def test_old_single_file_settings_removed():
    assert not (REPO / "docker" / "claude-settings.json").exists()
