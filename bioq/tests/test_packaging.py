from pathlib import Path

import tomllib


def test_bioq_console_script_registered():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["scripts"]["bioq"] == "bioq.main:main"


def test_cli_in_wheel_packages():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert "bioq" in data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
