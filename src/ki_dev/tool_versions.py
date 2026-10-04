"""Gemeinsame Versionsquelle fuer Image-Build und Python-Paket."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator

from ki_dev.config_sources import ConfigSource

_FILE_NAME = "tool-versions.json"
CONFIG_SOURCE = ConfigSource(
    "loop (Agenten-CLI-Versionen)",
    f"ki_dev/{_FILE_NAME} (Paket)",
    path=Path(str(files("ki_dev").joinpath(_FILE_NAME))),
)

_VERSION_KEYS = (
    "BD_VERSION",
    "CODEX_VERSION",
    "CLAUDE_VERSION",
    "DOLT_VERSION",
    "RUST_VERSION",
    "RUSTUP_VERSION",
    "GO_VERSION",
    "GOLANGCI_LINT_VERSION",
)
_PROPERTIES = {
    **dict.fromkeys(
        _VERSION_KEYS,
        {"type": "string", "pattern": r"^[0-9]+\.[0-9]+\.[0-9]+$"},
    ),
    **dict.fromkeys(
        ("NODE_IMAGE", "PYTHON_IMAGE"),
        {
            "type": "string",
            "pattern": r"^[a-z0-9/.-]+:[a-zA-Z0-9_.-]+$",
        },
    ),
    **dict.fromkeys(
        ("GO_SHA256_AMD64", "GO_SHA256_ARM64"),
        {"type": "string", "pattern": r"^[a-f0-9]{64}$"},
    ),
}
_VALIDATOR = Draft202012Validator(
    {
        "type": "object",
        "properties": _PROPERTIES,
        "required": list(_PROPERTIES),
        "additionalProperties": False,
    }
)


def load_tool_versions() -> dict[str, str]:
    resource = files("ki_dev").joinpath(_FILE_NAME)
    try:
        values = json.loads(resource.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(
            "tool-versions.json: ungueltiges JSON"
        ) from exc
    validate_tool_versions(values)
    return values


def validate_tool_versions(values: object) -> None:
    for error in _VALIDATOR.iter_errors(values):
        path = ".".join(map(str, error.absolute_path)) or "$"
        raise ValueError(
            f"tool-versions.json: {path}: {error.validator}"
        )


if __name__ == "__main__":
    for key, value in load_tool_versions().items():
        print("--build-arg")
        print(f"{key}={value}")
