"""Create a project virtualenv and install its requirements."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from penpine.cli.exceptions import VenvError


def _venv_python(project_dir) -> Path:
    # Resolve to an absolute path: pip_install runs this interpreter with
    # `cwd=project_dir`, and subprocess resolves a *relative* executable against
    # that cwd — so a relative path (from a relative project dir) would be looked
    # up under project_dir/project_dir/... and vanish. Absolute avoids that.
    venv_dir = Path(project_dir).resolve() / ".venv"
    windows = venv_dir / "Scripts" / "python.exe"
    return windows if windows.exists() else venv_dir / "bin" / "python"


def create_venv(project_dir, *, python: str | None = None, runner=subprocess.run) -> Path:
    python = python or sys.executable
    result = runner(
        [python, "-m", "venv", str(Path(project_dir) / ".venv")], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise VenvError(f"venv creation failed:\n{result.stderr}")
    return _venv_python(project_dir)


def pip_install(project_dir, *, runner=subprocess.run) -> None:
    python = _venv_python(project_dir)
    if not python.exists():
        raise VenvError(
            f"virtualenv interpreter not found at {python} "
            f"(venv creation may have failed); cannot install requirements"
        )
    result = runner(
        [str(python), "-m", "pip", "install", "-r", "requirements.txt"],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise VenvError(f"pip install failed:\n{result.stderr}")
