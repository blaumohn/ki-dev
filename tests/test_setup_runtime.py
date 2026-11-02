"""Reale Offline-Installation und Update bei gleicher Paketversion."""

import shutil
import sys
from pathlib import Path

import pytest
from plumbum import local

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts/setup-runtime.sh", repo / "scripts")
    shutil.copy(ROOT / "scripts/agent-container", repo / "scripts")
    shutil.copytree(ROOT / "scripts/lib", repo / "scripts/lib")
    for name in (
        "compose.yaml",
        "compose.beads.yaml",
        "compose.fresh.yaml",
        "compose.workdir.yaml",
    ):
        shutil.copy(ROOT / name, repo)
    shutil.copytree(
        ROOT / "docker/agent-settings", repo / "docker/agent-settings"
    )
    shutil.copy(ROOT / "Makefile", repo)
    # Wheel-Backend ohne Downloads oder Build-Abhängigkeiten.
    (repo / "pyproject.toml").write_text(
        '[build-system]\nrequires = []\nbuild-backend = "backend"\n'
        'backend-path = ["."]\n'
    )
    (repo / "backend.py").write_text(
        "from pathlib import Path\n"
        "from zipfile import ZipFile\n"
        "def build_wheel(wheel_directory, config_settings=None, "
        "metadata_directory=None):\n"
        " name = 'ki_dev-0.0.1-py3-none-any.whl'\n"
        " prefix = 'ki_dev-0.0.1.dist-info/'\n"
        " with ZipFile(Path(wheel_directory) / name, 'w') as wheel:\n"
        "  for path in Path('ki_dev').glob('*.py'):\n"
        "   wheel.write(path, str(path))\n"
        "  wheel.writestr(prefix + 'METADATA', "
        "'Metadata-Version: 2.1\\nName: ki-dev\\nVersion: 0.0.1\\n')\n"
        "  wheel.writestr(prefix + 'WHEEL', "
        "'Wheel-Version: 1.0\\nGenerator: test\\n' "
        "'Root-Is-Purelib: true\\nTag: py3-none-any\\n')\n"
        "  wheel.writestr(prefix + 'entry_points.txt', "
        "'[console_scripts]\\nki-dev = ki_dev.cli:main\\n')\n"
        "  wheel.writestr(prefix + 'RECORD', '')\n"
        " return name\n"
    )
    (repo / "ki_dev").mkdir()
    (repo / "ki_dev/__init__.py").write_text('VALUE = "first"\n')
    (repo / "ki_dev/cli.py").write_text(
        "from . import VALUE\ndef main():\n print(VALUE)\n"
    )
    return repo


def setup(repo, user_dir, data_home=""):
    with (
        local.cwd(repo),
        local.env(
            HOME=str(user_dir),
            XDG_DATA_HOME=data_home,
            KI_DEV_SETUP_PYTHON=sys.executable,
            PIP_NO_INDEX="1",
            PIP_CONFIG_FILE="/dev/null",
            PYTHONPATH="",
        ),
    ):
        return local["make"].run(
            args=["setup-runtime"], retcode=None, timeout=120
        )


@pytest.mark.parametrize("custom_xdg", [False, True])
def test_install_and_update_are_independent_of_repo(
    project, tmp_path, custom_xdg
):
    user_dir = tmp_path / "user with spaces"
    data_home = str(tmp_path / "data") if custom_xdg else ""
    code, _, error = setup(project, user_dir, data_home)
    assert code == 0, error
    root = Path(data_home) if data_home else user_dir / ".local/share"
    runtime = root / "ki-dev/venv"
    link = user_dir / ".local/bin/ki-dev"
    assert link.is_symlink()
    assert link.readlink() == runtime / "bin/ki-dev"
    command = local[str(link)]
    with local.env(PYTHONPATH=str(project), PYTHONHOME="/wrong"):
        assert command().strip() == "first"
    (project / "ki_dev/__init__.py").write_text('VALUE = "second"\n')
    assert command().strip() == "first"
    code, _, error = setup(project, user_dir, data_home)
    assert code == 0, error
    assert command().strip() == "second"
    installed = local[str(runtime / "bin/python")](
        "-I", "-c", "import ki_dev; print(ki_dev.__file__)"
    ).strip()
    assert Path(installed).is_relative_to(runtime)
    assert not (project / ".venv").exists()


@pytest.mark.parametrize("conflict", ["file", "symlink"])
def test_foreign_entry_point_is_preserved(project, tmp_path, conflict):
    user_dir = tmp_path / "user"
    link = user_dir / ".local/bin/ki-dev"
    link.parent.mkdir(parents=True)
    if conflict == "file":
        link.write_text("foreign")
    else:
        link.symlink_to(tmp_path / "foreign")
    code, _, error = setup(project, user_dir)
    assert code != 0
    assert "gehört nicht" in error
    if conflict == "file":
        assert link.read_text() == "foreign"
    else:
        assert link.readlink() == tmp_path / "foreign"
    assert not (user_dir / ".local/share/ki-dev").exists()


def test_runtime_cannot_be_installed_inside_repo(project, tmp_path):
    code, _, error = setup(project, tmp_path / "user", str(project))
    assert code != 0
    assert "außerhalb" in error
    assert not (project / "ki-dev/venv").exists()


def test_existing_non_venv_is_preserved(project, tmp_path):
    data = tmp_path / "data"
    runtime = data / "ki-dev/venv"
    runtime.mkdir(parents=True)
    marker = runtime / "foreign.txt"
    marker.write_text("preserve")
    code, _, error = setup(project, tmp_path / "user", str(data))
    assert code != 0
    assert "kein venv" in error
    assert marker.read_text() == "preserve"
