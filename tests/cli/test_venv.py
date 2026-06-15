import sys
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
    runner = FakeRunner()
    pip_install(tmp_path, runner=runner)
    argv, kwargs = runner.calls[0]
    assert argv[1:] == ["-m", "pip", "install", "-r", "requirements.txt"]
    assert kwargs["cwd"] == str(tmp_path)


def test_pip_install_failure_raises(tmp_path):
    with pytest.raises(VenvError):
        pip_install(tmp_path, runner=FakeRunner(returncode=1))
