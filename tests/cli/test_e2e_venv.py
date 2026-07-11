import os
import subprocess

import pytest

from penpine.cli.commands import new as new_cmd

pytestmark = pytest.mark.slow

requires_optin = pytest.mark.skipif(
    "PENPINE_SLOW" not in os.environ,
    reason="set PENPINE_SLOW=1 to run the real-venv end-to-end test",
)


@requires_optin
def test_real_venv_install_and_import(tmp_path):
    project = new_cmd.run("eng", target_dir=str(tmp_path), create_venv=True)
    venv_python = project / ".venv" / "bin" / "python"
    assert venv_python.exists()
    # penpine importable inside the freshly built venv
    result = subprocess.run(
        [str(venv_python), "-c", "import penpine, config; print('ok')"],
        cwd=project,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
