"""Projektkonfiguration der Rohsitzungsquellen und Listenfilter."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path

from jsonschema import Draft202012Validator

from ki_dev.config_sources import ConfigSource

CONFIG_SOURCE = ConfigSource(
    command="session",
    location="pyproject.toml",
    section="tool.ki-dev.session",
    path=Path("pyproject.toml"),
)
_TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "codex_sessions_dir": _TEXT,
        "claude_sessions_dir": _TEXT,
        "exclude_cwd": {"type": "array", "items": _TEXT},
    },
}
_VALIDATOR = Draft202012Validator(
    {
        "type": "object",
        "properties": {
            "tool": {
                "type": "object",
                "properties": {
                    "ki-dev": {
                        "type": "object",
                        "properties": {"session": _SCHEMA},
                    }
                },
            }
        },
    }
)


def read_session_config() -> dict:
    """Optionale Projektdatei lesen und ungültige Angaben melden."""
    path = CONFIG_SOURCE.path
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(
            f"pyproject.toml nicht lesbar ({type(exc).__name__})"
        ) from None
    errors = list(_VALIDATOR.iter_errors(document))
    if errors:
        fields = [
            ".".join(str(p) for p in error.absolute_path) or "<section>"
            for error in errors
        ]
        raise ValueError(
            "tool.ki-dev.session ungültig: " + ", ".join(fields)
        )
    return document.get("tool", {}).get("ki-dev", {}).get("session", {})


def session_environ(
    environ: Mapping[str, str], config: Mapping | None = None
) -> dict[str, str]:
    """Explizite Umgebungsvariablen haben Vorrang vor Projektpfaden."""
    if config is None:
        config = read_session_config()
    result = dict(environ)
    for agent in ("codex", "claude"):
        key = f"{agent}_sessions_dir"
        env = f"KI_DEV_{agent.upper()}_SESSIONS_DIR"
        if key in config and env not in result:
            if agent == "codex" and "CODEX_HOME" in result:
                continue
            result[env] = str(Path(config[key]).expanduser().absolute())
    return result
