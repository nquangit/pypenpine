import subprocess
import sys
from datetime import date

import pytest

from penpine.cli.scaffold import render_project

VARS = {
    "project_name": "demo",
    "project_slug": "demo",
    "penpine_path": "/tmp/pp",
    "penpine_spec": "penpine",
    "date": date.today().isoformat(),
    "python_version": "3.11",
}

SAMPLES = [
    "custom_payload",
    "custom_validator",
    "custom_module",
    "custom_rule",
    "custom_auth",
    "custom_interceptor",
    "data_sharing",
    "byo_test_cases",
    "flow_basic",
    "flow_attacks",
    "flow_login",
]
FINDING_SAMPLES = {"custom_module", "byo_test_cases"}


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    dst = tmp_path_factory.mktemp("proj")
    render_project(dst, VARS, force=True)
    return dst


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_runs_offline(project, name):
    result = subprocess.run(
        [sys.executable, "-m", f"samples.{name}"], cwd=project, capture_output=True, text=True
    )
    assert result.returncode == 0, f"{name} failed:\n{result.stdout}\n{result.stderr}"
    if name in FINDING_SAMPLES:
        assert "'found': 0" not in result.stdout, f"{name} produced no finding:\n{result.stdout}"
