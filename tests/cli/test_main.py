import subprocess
import sys

from penpine.cli.main import main


def test_main_creates_project_returns_zero(tmp_path):
    rc = main(["new", "eng", "--dir", str(tmp_path), "--no-venv"])
    assert rc == 0
    assert (tmp_path / "eng" / "main.py").exists()


def test_main_returns_two_on_cli_error(tmp_path):
    project = tmp_path / "eng"
    project.mkdir()
    (project / "x").write_text("y")
    rc = main(["new", "eng", "--dir", str(tmp_path), "--no-venv"])  # non-empty, no --force
    assert rc == 2


def test_python_m_penpine_smoke(tmp_path):
    result = subprocess.run([sys.executable, "-m", "penpine", "new", "eng",
                             "--dir", str(tmp_path), "--no-venv"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "eng" / "samples" / "custom_payload.py").exists()
