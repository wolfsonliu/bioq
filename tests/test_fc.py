"""Opt-in end-to-end: bioq against a real gateway. Run with:
    RUN_FC_TESTS=1 BIOQ_GATEWAY_URL=... [BIOQ_FC_PDB=<pdb>] \
        uv run python -m pytest tests/test_fc.py -v -m fc

Auth: the tests drive the real CLI through main(), which uses the logged-in profile
(run `bioq login --oidc` / `--client-credentials` first) or `auth_mode = "none"` for
a localhost / VPC-bypass gateway.

The `run` test also needs a PDB input for proteinmpnn `design`; set BIOQ_FC_PDB to a
PDB file (e.g. 5L33.pdb) to enable it.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from bioq import main as mainmod

_needs = pytest.mark.skipif(
    not (os.environ.get("BIOQ_GATEWAY_URL") and os.environ.get("RUN_FC_TESTS")),
    reason="set RUN_FC_TESTS=1 + BIOQ_GATEWAY_URL",
)
_PDB = os.environ.get("BIOQ_FC_PDB")


@pytest.mark.fc
@_needs
def test_services_lists_proteinmpnn():
    assert mainmod.main(["services"]) == 0


@pytest.mark.fc
@_needs
@pytest.mark.skipif(
    not (_PDB and Path(_PDB).is_file()),
    reason="set BIOQ_FC_PDB to a PDB file to run the run test",
)
def test_run_proteinmpnn_design(tmp_path):
    code = mainmod.main([
        "run", "proteinmpnn-server", "design",
        "--file", f"pdb={_PDB}",
        "--set", "name=bioqtest", "--set", "num_seq_per_target=2",
        "--set", "model_variant=vanilla", "--set", "model_name=v_48_020",
        "--set", "sampling_temp=0.1", "--set", "seed=37",
        "--wait", "-o", str(tmp_path / "out"),
    ])
    assert code == 0
    fastas = list((tmp_path / "out").rglob("*.fa")) + list((tmp_path / "out").rglob("*.fasta"))
    assert fastas, "no FASTA extracted"
