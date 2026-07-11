import subprocess
import sys

from penpine.cli.main import main


def test_main_run_dry_run_returns_zero(capsys):
    rc = main(["run", "--url", "http://h/s?q=1", "--attack", "sqli", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "would attack (sqli):" in out


def test_main_run_no_input_is_cli_error():
    rc = main(["run", "--attack", "sqli"])  # no --curl/--request/--url
    assert rc == 2


def test_python_m_penpine_run_dry_run_smoke():
    result = subprocess.run(
        [sys.executable, "-m", "penpine", "run", "--url", "http://h/s?q=1", "--dry-run"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "would attack" in result.stdout
