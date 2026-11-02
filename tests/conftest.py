"""Gemeinsame Testumgebung."""

from __future__ import annotations

import pytest

# Anforderungstests: --spec, Marker requirement/control
# (make spec-test).
pytest_plugins = ["tests.spec.plugin"]


@pytest.fixture(autouse=True)
def claude_quota_dir(tmp_path_factory, monkeypatch):
    """5h-Messwerte des Claude-Adapters nie unter ``~/.cache``."""
    root = tmp_path_factory.mktemp("claude-quota")
    monkeypatch.setattr(
        "ki_dev.adapter.executors.claude_cli.DEFAULT_QUOTA_DIR", root
    )
    return root


@pytest.fixture(autouse=True)
def git_identity(tmp_path_factory, monkeypatch):
    """Eigene globale Git-Konfiguration: der Start verlangt eine
    Identität, und auf dem Host gälte sonst die des Nutzers."""
    config = tmp_path_factory.mktemp("git") / "config"
    config.write_text(
        "[user]\n\tname = test\n\temail = test@example.invalid\n"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    return config


@pytest.fixture(autouse=True)
def state_home(tmp_path_factory, monkeypatch):
    """Laufdaten ohne ``--runs-dir`` nie im echten Zustandsordner."""
    root = tmp_path_factory.mktemp("state")
    monkeypatch.setenv("XDG_STATE_HOME", str(root))
    return root


@pytest.fixture(autouse=True)
def scaffold_flows_only(monkeypatch):
    """Abläufe und Vorlagen aus dem Gerüst, nie aus einem externen
    Paket der Umgebung (``KI_DEV_FLOW_PATH``); Tests, die es
    brauchen, setzen es selbst."""
    monkeypatch.delenv("KI_DEV_FLOW_PATH", raising=False)
