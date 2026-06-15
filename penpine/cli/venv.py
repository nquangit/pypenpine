"""Create a project virtualenv and install its requirements."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from penpine.cli.exceptions import VenvError


def _venv_python(project_dir) -> Path:
    venv_dir = Path(project_dir) / ".venv"
    windows = venv_dir / "Scripts" / "python.exe"
    return windows if windows.exists() else venv_dir / "bin" / "python"


def create_venv(project_dir, *, python: str | None = None, runner=subprocess.run) -> Path:
    python = python or sys.executable
    result = runner([python, "-m", "venv", str(Path(project_dir) / ".venv")],
                    capture_output=True, text=True)
    if result.returncode != 0:
        raise VenvError(f"venv creation failed:\n{result.stderr}")
    return _venv_python(project_dir)


def pip_install(project_dir, *, runner=subprocess.run) -> None:
    result = runner([str(_venv_python(project_dir)), "-m", "pip", "install",
                     "-r", "requirements.txt"],
                    cwd=str(project_dir), capture_output=True, text=True)
    if result.returncode != 0:
        raise VenvError(f"pip install failed:\n{result.stderr}")
