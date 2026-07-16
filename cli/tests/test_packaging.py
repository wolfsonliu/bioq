import tomllib
from pathlib import Path


def test_bioq_console_script_registered():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["scripts"]["bioq"] == "cli.main:main"


def test_cli_in_wheel_packages():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert "cli" in data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
