import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from penpine.cli.exceptions import VenvError
from penpine.cli.venv import create_venv, pip_install


class FakeRunner:
    def __init__(self, returncode=0):
        self.calls = []
        self.returncode = returncode

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return SimpleNamespace(returncode=self.returncode, stdout="", stderr="boom")


def _make_fake_venv(project_dir) -> Path:
    """Create a fake .venv/bin/python (POSIX) so existence checks pass."""
    bin_dir = Path(project_dir) / ".venv" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    py = bin_dir / "python"
    py.write_text("")
    return py


def test_create_venv_invokes_python_m_venv(tmp_path):
    runner = FakeRunner()
    create_venv(tmp_path, python="/usr/bin/python3", runner=runner)
    argv = runner.calls[0][0]
    assert argv[:3] == ["/usr/bin/python3", "-m", "venv"]
    assert argv[3].endswith(".venv")


def test_create_venv_failure_raises(tmp_path):
    with pytest.raises(VenvError):
        create_venv(tmp_path, python=sys.executable, runner=FakeRunner(returncode=1))


def test_pip_install_uses_venv_python_and_requirements(tmp_path):
    _make_fake_venv(tmp_path)
    runner = FakeRunner()
    pip_install(tmp_path, runner=runner)
    argv, kwargs = runner.calls[0]
    assert argv[1:] == ["-m", "pip", "install", "-r", "requirements.txt"]
    assert kwargs["cwd"] == str(tmp_path)


def test_pip_install_failure_raises(tmp_path):
    _make_fake_venv(tmp_path)
    with pytest.raises(VenvError):
        pip_install(tmp_path, runner=FakeRunner(returncode=1))


def test_pip_install_missing_interpreter_raises_clear_error(tmp_path):
    # No .venv created: the guard must raise VenvError before ever invoking the
    # runner, instead of letting subprocess raise a raw FileNotFoundError.
    runner = FakeRunner()
    with pytest.raises(VenvError):
        pip_install(tmp_path, runner=runner)
    assert runner.calls == []  # never attempted to run a missing interpreter


def test_pip_install_uses_absolute_python_for_relative_project_dir(tmp_path, monkeypatch):
    # Reproduces the real bug: with a RELATIVE project dir + cwd=project_dir,
    # a relative interpreter path resolves against the wrong directory. The
    # interpreter path handed to the runner must be absolute.
    monkeypatch.chdir(tmp_path)
    proj = Path("demoproj")
    _make_fake_venv(proj)  # relative project dir
    runner = FakeRunner()
    pip_install(proj, runner=runner)
    argv = runner.calls[0][0]
    assert Path(argv[0]).is_absolute(), f"interpreter path must be absolute, got {argv[0]!r}"
    assert Path(argv[0]) == (tmp_path / "demoproj" / ".venv" / "bin" / "python")
