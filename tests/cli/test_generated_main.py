"""The generated main.py must build a request the Engine can actually send:
i.e. load_request() populates connection meta (scheme/host/port). Regression
for the 'request.meta missing host/port' failure."""

import subprocess
import sys
from datetime import date

from penpine.cli.scaffold import render_project

VARS = {
    "project_name": "demo",
    "project_slug": "demo",
    "penpine_path": "/tmp/pp",
    "penpine_spec": "penpine",
    "date": date.today().isoformat(),
    "python_version": "3.11",
}

# Run inside the generated project: load the request and assert meta is set,
# for both the default http config and an https override.
_CHECK = """
import config, main
config.TARGET_SCHEME = "{scheme}"
config.TARGET_HOST = "{host}"
r = main.load_request()
assert r.meta.scheme == "{scheme}", r.meta
assert r.meta.host == "{exp_host}", r.meta
assert r.meta.port == {exp_port}, r.meta
print("META_OK", r.meta.scheme, r.meta.host, r.meta.port)
"""


def _run_check(project, *, scheme, host, exp_host, exp_port):
    code = _CHECK.format(scheme=scheme, host=host, exp_host=exp_host, exp_port=exp_port)
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=project, capture_output=True, text=True
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "META_OK" in result.stdout


def test_load_request_sets_meta(tmp_path):
    project = tmp_path / "proj"
    render_project(project, VARS)
    # explicit port honored, https scheme preserved
    _run_check(
        project, scheme="https", host="example.test:8443", exp_host="example.test", exp_port=8443
    )
    # default https port when none given
    _run_check(project, scheme="https", host="example.test", exp_host="example.test", exp_port=443)
    # default http port when none given
    _run_check(project, scheme="http", host="example.test", exp_host="example.test", exp_port=80)
