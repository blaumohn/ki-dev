"""Tool-Temp-Volume des readme-check-Containers (ki-dev-ablauf-rzjs).

Statisch, ohne Docker: Das echte Verhalten deckt make readme-check ab.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "compose.readme-check.yaml"
DOCKERFILE = ROOT / "docker/readme-check/Dockerfile"


def test_tool_tmp_is_image_prepared_volume_not_shared_folder():
    service = yaml.safe_load(COMPOSE.read_text())["services"]["check"]
    tool_tmp = service["environment"]["TMPDIR"]
    mounts = [v for v in service["volumes"] if isinstance(v, dict)]
    volumes = {v["target"]: v for v in mounts}

    # Anonymes Volume: ohne source landet es auf der VM-Platte.
    assert volumes[tool_tmp]["type"] == "volume"
    assert "source" not in volumes[tool_tmp]
    # Große Go-Zwischendateien bleiben auf dem Bind-Mount.
    assert service["environment"]["GOTMPDIR"] != tool_tmp
    assert volumes[service["environment"]["GOTMPDIR"]]["type"] == "bind"
    # Das Volume übernimmt die Rechte aus dem Image; der Container ist
    # read_only und läuft als Host-UID.
    assert service["read_only"] is True
    path = re.escape(tool_tmp)
    prepared = re.search(
        rf"mkdir -p {path} && chmod 1777 {path}", DOCKERFILE.read_text()
    )
    assert prepared, f"{tool_tmp}: mkdir/chmod 1777 fehlt im Dockerfile"
