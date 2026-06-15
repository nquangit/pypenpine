# Penpine CLI Project Scaffolder (`penpine new`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `penpine new <name>` console subcommand that scaffolds a complete, runnable penpine-based project (folder, requirements.txt with an auto-detected editable penpine path, default virtualenv + install, runnable `main.py`, Python config, sample request, a `samples/` library with one offline-runnable example per extension point, and docs).

**Architecture:** A new `penpine/cli/` package with focused modules — `paths` (slug + penpine-source detection), `scaffold` (template renderer), `venv` (venv + pip), `commands/new` (orchestration + rollback), and `main` (argparse entry point). The scaffold is stored as real template files under `penpine/cli/templates/project/`; `*.tmpl` files get `{{ var }}` substitution, everything else is copied verbatim, and a `dot-` filename prefix maps to a leading `.`. A render+subprocess test proves every generated sample actually runs offline.

**Tech Stack:** Python 3.11+ stdlib only (`argparse`, `subprocess`, `venv`, `pathlib`, `re`, `shutil`, `datetime`); `pytest` for tests. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-06-15-penpine-cli-scaffolder-design.md`

**Conventions for this repo:**
- Commit WITHOUT GPG signing: `git -c commit.gpgsign=false commit -m "..."` (the `-c` flag goes BEFORE `commit`).
- Run tests with `python -m pytest`. The package is installed editable (an `penpine.egg-info` exists), so `import penpine` works in subprocesses launched with `sys.executable`.

---

### Task 1: CLI package skeleton + exceptions

**Files:**
- Create: `penpine/cli/__init__.py`
- Create: `penpine/cli/exceptions.py`
- Create: `penpine/cli/commands/__init__.py`
- Create: `tests/cli/__init__.py`
- Test: `tests/cli/test_exceptions.py`

- [ ] **Step 1: Write the failing test**

`tests/cli/test_exceptions.py`:
```python
from penpine.exceptions import PenpineError
from penpine.cli.exceptions import CliError, ScaffoldError, VenvError


def test_cli_errors_subclass_penpine_error():
    assert issubclass(CliError, PenpineError)
    assert issubclass(ScaffoldError, CliError)
    assert issubclass(VenvError, CliError)


def test_errors_carry_message():
    assert str(ScaffoldError("boom")) == "boom"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cli/test_exceptions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'penpine.cli'`

- [ ] **Step 3: Create the package files**

`penpine/cli/__init__.py`:
```python
"""penpine command-line interface."""
```

`penpine/cli/commands/__init__.py`:
```python
"""penpine CLI subcommands."""
```

`penpine/cli/exceptions.py`:
```python
"""CLI exception hierarchy."""
from __future__ import annotations

from penpine.exceptions import PenpineError


class CliError(PenpineError):
    """Base class for CLI failures."""


class ScaffoldError(CliError):
    """Project scaffolding failed (bad name, non-empty target, template bug)."""


class VenvError(CliError):
    """Virtualenv creation or dependency install failed."""
```

`tests/cli/__init__.py`:
```python
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cli/test_exceptions.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add penpine/cli/__init__.py penpine/cli/exceptions.py penpine/cli/commands/__init__.py tests/cli/__init__.py tests/cli/test_exceptions.py
git -c commit.gpgsign=false commit -m "feat(cli): add cli package skeleton and exception hierarchy"
```

---

### Task 2: `paths.py` — slug + penpine-source detection

**Files:**
- Create: `penpine/cli/paths.py`
- Test: `tests/cli/test_paths.py`

- [ ] **Step 1: Write the failing test**

`tests/cli/test_paths.py`:
```python
from pathlib import Path

from penpine.cli.paths import slugify, find_penpine_root, penpine_spec


def test_slugify_normalizes_names():
    assert slugify("My Engagement") == "my_engagement"
    assert slugify("a-b.c") == "a_b_c"
    assert slugify("123app") == "p_123app"
    assert slugify("  ok  ") == "ok"
    assert slugify("--!!--") == "p_"  # empty core -> prefixed


def test_penpine_spec():
    assert penpine_spec(None) == "penpine"
    assert penpine_spec(Path("/x/pypenpine")) == "-e /x/pypenpine"


def test_find_penpine_root_locates_this_repo():
    root = find_penpine_root()
    assert root is not None
    assert (root / "pyproject.toml").exists()
    assert (root / "penpine" / "__init__.py").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cli/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'penpine.cli.paths'`

- [ ] **Step 3: Write the implementation**

`penpine/cli/paths.py`:
```python
"""Project-name slugging and local penpine source detection."""
from __future__ import annotations

import re
from pathlib import Path

import penpine

_NON_IDENT = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """An importable, lowercase slug. Empty/digit-leading cores get a 'p_' prefix."""
    slug = _NON_IDENT.sub("_", name.strip().lower()).strip("_")
    if not slug or slug[0].isdigit():
        slug = "p_" + slug
    return slug


def find_penpine_root() -> Path | None:
    """The directory holding penpine's pyproject.toml, or None when penpine is
    installed without a source tree."""
    start = Path(penpine.__file__).resolve().parent
    for candidate in (start, *start.parents):
        pyproject = candidate / "pyproject.toml"
        if pyproject.exists() and 'name = "penpine"' in pyproject.read_text(encoding="utf-8"):
            return candidate
    return None


def penpine_spec(root: Path | None) -> str:
    """The requirements.txt dependency line for penpine."""
    return f"-e {root}" if root is not None else "penpine"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cli/test_paths.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add penpine/cli/paths.py tests/cli/test_paths.py
git -c commit.gpgsign=false commit -m "feat(cli): add name slugging and penpine source detection"
```

---

### Task 3: `scaffold.py` — the template renderer

**Files:**
- Create: `penpine/cli/scaffold.py`
- Test: `tests/cli/test_scaffold.py`

- [ ] **Step 1: Write the failing test**

`tests/cli/test_scaffold.py`:
```python
import pytest

from penpine.cli.exceptions import ScaffoldError
from penpine.cli.scaffold import render_project


def _make_source(tmp_path):
    src = tmp_path / "tpl"
    (src / "sub").mkdir(parents=True)
    (src / "main.py.tmpl").write_text("name = {{ project_name }}\n")
    (src / "keep.http").write_text("literal {{ x }} stays\n")  # verbatim
    (src / "dot-gitignore").write_text(".venv/\n")
    (src / "sub" / "note.txt.tmpl").write_text("on {{ date }}\n")
    return src


def test_renders_substitutes_copies_and_maps_dotfiles(tmp_path):
    src = _make_source(tmp_path)
    dst = tmp_path / "out"
    written = render_project(dst, {"project_name": "demo", "date": "2026-06-15"}, source=src)
    assert (dst / "main.py").read_text() == "name = demo\n"          # .tmpl rendered + suffix stripped
    assert (dst / "keep.http").read_text() == "literal {{ x }} stays\n"  # verbatim, braces preserved
    assert (dst / ".gitignore").read_text() == ".venv/\n"            # dot- prefix mapped
    assert (dst / "sub" / "note.txt").read_text() == "on 2026-06-15\n"  # nested
    assert (dst / "main.py") in written


def test_unknown_placeholder_raises(tmp_path):
    src = tmp_path / "tpl"
    src.mkdir()
    (src / "f.tmpl").write_text("{{ nope }}")
    with pytest.raises(ScaffoldError):
        render_project(tmp_path / "out", {}, source=src)


def test_non_empty_target_without_force_raises(tmp_path):
    src = _make_source(tmp_path)
    dst = tmp_path / "out"
    dst.mkdir()
    (dst / "existing").write_text("x")
    with pytest.raises(ScaffoldError):
        render_project(dst, {"project_name": "d", "date": "x"}, source=src)
    # force overwrites without raising
    render_project(dst, {"project_name": "d", "date": "x"}, source=src, force=True)
    assert (dst / "main.py").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cli/test_scaffold.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'penpine.cli.scaffold'`

- [ ] **Step 3: Write the implementation**

`penpine/cli/scaffold.py`:
```python
"""Render the project template tree into a destination directory."""
from __future__ import annotations

import re
from pathlib import Path

from penpine.cli.exceptions import ScaffoldError

_PLACEHOLDER = re.compile(r"\{\{\s*([^}\s]+)\s*\}\}")
_HERE = Path(__file__).resolve().parent
_DEFAULT_SOURCE = _HERE / "templates" / "project"


def _render_text(text: str, variables: dict) -> str:
    def _sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in variables:
            raise ScaffoldError(f"unknown template variable {{{{ {key} }}}}")
        return str(variables[key])
    return _PLACEHOLDER.sub(_sub, text)


def _map_segment(segment: str) -> str:
    if segment.startswith("dot-"):
        return "." + segment[len("dot-"):]
    return segment


def render_project(dst, variables: dict, *, source=None, force: bool = False) -> list:
    """Render every file under `source` into `dst`. `*.tmpl` files are variable-
    substituted and lose the suffix; all other files are copied verbatim; a
    `dot-` filename prefix maps to a leading `.`. Returns the files written."""
    dst = Path(dst)
    src = Path(source) if source is not None else _DEFAULT_SOURCE
    if dst.exists() and any(dst.iterdir()) and not force:
        raise ScaffoldError(f"target {dst} is not empty (use force=True / --force)")

    written = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        parts = [_map_segment(part) for part in path.relative_to(src).parts]
        rendered = parts[-1].endswith(".tmpl")
        if rendered:
            parts[-1] = parts[-1][: -len(".tmpl")]
        out_path = dst.joinpath(*parts)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        if rendered:
            data = _render_text(data.decode("utf-8"), variables).encode("utf-8")
        out_path.write_bytes(data)
        written.append(out_path)
    return written
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cli/test_scaffold.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add penpine/cli/scaffold.py tests/cli/test_scaffold.py
git -c commit.gpgsign=false commit -m "feat(cli): add template renderer (.tmpl substitution, dot- mapping, verbatim copy)"
```

---

### Task 4: `venv.py` — venv creation + pip install

**Files:**
- Create: `penpine/cli/venv.py`
- Test: `tests/cli/test_venv.py`

- [ ] **Step 1: Write the failing test**

`tests/cli/test_venv.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cli/test_venv.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'penpine.cli.venv'`

- [ ] **Step 3: Write the implementation**

`penpine/cli/venv.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cli/test_venv.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add penpine/cli/venv.py tests/cli/test_venv.py
git -c commit.gpgsign=false commit -m "feat(cli): add venv creation and pip install with injectable runner"
```

---

### Task 5: Base project templates (main, config, requirements, gitignore, request, README)

**Files:**
- Create: `penpine/cli/templates/project/main.py.tmpl`
- Create: `penpine/cli/templates/project/config.py.tmpl`
- Create: `penpine/cli/templates/project/requirements.txt.tmpl`
- Create: `penpine/cli/templates/project/dot-gitignore`
- Create: `penpine/cli/templates/project/requests/sample.http`
- Create: `penpine/cli/templates/project/docs/README.md.tmpl`
- Test: `tests/cli/test_base_templates.py`

- [ ] **Step 1: Write the failing test**

`tests/cli/test_base_templates.py`:
```python
from datetime import date

from penpine.cli.scaffold import render_project

VARS = {
    "project_name": "demo-eng",
    "project_slug": "demo_eng",
    "penpine_path": "/tmp/pypenpine",
    "penpine_spec": "-e /tmp/pypenpine",
    "date": date.today().isoformat(),
    "python_version": "3.11",
}


def test_base_files_render_and_compile(tmp_path):
    dst = tmp_path / "proj"
    render_project(dst, VARS)  # real templates
    for rel in ("main.py", "config.py", "requirements.txt",
                ".gitignore", "requests/sample.http", "docs/README.md"):
        assert (dst / rel).exists(), rel
    # editable spec landed in requirements
    assert "-e /tmp/pypenpine" in (dst / "requirements.txt").read_text()
    # main.py and config.py are valid Python
    compile((dst / "main.py").read_text(), "main.py", "exec")
    compile((dst / "config.py").read_text(), "config.py", "exec")
    # the sample request keeps its runtime placeholder verbatim
    assert "{{TARGET_HOST}}" in (dst / "requests" / "sample.http").read_text()
    # README carries the project name
    assert "demo-eng" in (dst / "docs" / "README.md").read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cli/test_base_templates.py -v`
Expected: FAIL (template files don't exist yet → `render_project` finds no `main.py`, assertion error / empty source)

- [ ] **Step 3: Create the template files**

`penpine/cli/templates/project/main.py.tmpl`:
```python
"""{{ project_name }} — penpine engagement entry point.

Runnable end to end: loads requests/sample.http, registers the built-in attack
modules plus this project's custom module, runs the configured attack(s), and
prints findings. Configure the target in config.py before running.

    python main.py            # run config.ATTACKS
    python main.py sqli xss   # override the attack list on the CLI
"""
import sys

from penpine import Engine, Runner
from penpine.attack.modules import register_builtins
from penpine.core.message import Request
from penpine.transport.proxy import ProxyConfig
from penpine.transport.tls import TLSConfig

import config
from samples.custom_module import register as register_custom


def load_request():
    raw = open("requests/sample.http", "rb").read()
    return Request.from_raw(raw.replace(b"{{TARGET_HOST}}", config.TARGET_HOST.encode()))


def build_runner():
    engine_kw = {"tls": TLSConfig(verify=config.TLS_VERIFY)}
    if config.PROXY:
        engine_kw["proxy"] = ProxyConfig.from_url(config.PROXY)
    return Runner(sender=Engine(**engine_kw), max_concurrency=config.CONCURRENCY)


def main(argv=None):
    attacks = (argv if argv is not None else sys.argv[1:]) or config.ATTACKS
    register_builtins()
    register_custom()
    request = load_request()
    runner = build_runner()
    try:
        for attack in attacks:
            report = runner.run_sync(request, attack=attack)
            print(f"\n== {attack} ==  {report.summary()}")
            for finding in report.findings:
                print(f"  [{finding.confidence.name}] {finding.point.expr} -> {finding.evidence}")
    finally:
        runner.close()


if __name__ == "__main__":
    main()
```

`penpine/cli/templates/project/config.py.tmpl`:
```python
"""{{ project_name }} — configuration (pure Python; no external config files)."""

# Host[:port] the sample request targets. CHANGE THIS to a system you are
# AUTHORIZED to test. Defaults to localhost so a blind run hits nothing real.
TARGET_HOST = "127.0.0.1:8000"

# Attacks to run by default — names of registered modules.
ATTACKS = ["sqli", "xss"]

# Max concurrent in-flight requests.
CONCURRENCY = 10

# Optional upstream proxy, e.g. "http://127.0.0.1:8080" for Burp/ZAP. None disables.
PROXY = None

# Verify TLS certificates. False is common when testing self-signed targets.
TLS_VERIFY = False
```

`penpine/cli/templates/project/requirements.txt.tmpl`:
```
# Editable install of the local penpine source, auto-detected at scaffold time.
{{ penpine_spec }}
jsonpath-ng>=1.6
```

`penpine/cli/templates/project/dot-gitignore`:
```
.venv/
__pycache__/
*.pyc
findings/
```

`penpine/cli/templates/project/requests/sample.http` (note the trailing blank line):
```
GET /search?q=penpine&id=1 HTTP/1.1
Host: {{TARGET_HOST}}
User-Agent: penpine-sample
Accept: */*
Connection: close

```

`penpine/cli/templates/project/docs/README.md.tmpl`:
```markdown
# {{ project_name }}

A penpine-based pentesting project, scaffolded on {{ date }}.

## Setup

A virtualenv was created at `.venv` with penpine installed editable from
`{{ penpine_path }}`. Activate it:

    source .venv/bin/activate        # Windows: .venv\Scripts\activate

If you scaffolded with `--no-venv`, create it yourself:

    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

## Run

1. Edit `config.py` and set `TARGET_HOST` to **a system you are authorized to test**.
2. Run the engagement:

       python main.py            # runs config.ATTACKS against requests/sample.http
       python main.py sqli xss   # override the attack list

`main.py` registers the built-in modules plus this project's custom module,
runs each attack, and prints findings.

## Extending

`samples/` holds one self-contained, offline-runnable example per extension
point — run any directly with `python -m samples.<name>`:

| File | Shows |
|------|-------|
| `samples/custom_payload.py` | a `PayloadGenerator` |
| `samples/custom_validator.py` | a `Validator` |
| `samples/custom_module.py` | wiring generator + validator into a registered `AttackModule` |
| `samples/custom_rule.py` | a `ClassificationRule` for the analyzer |
| `samples/custom_auth.py` | a custom `AuthScheme` + `AuthProfile` |
| `samples/custom_interceptor.py` | a transport `Interceptor` |
| `samples/data_sharing.py` | sharing captured data between two `Identity` objects (IDOR) |
| `samples/byo_test_cases.py` | bringing your own `TestCase`s to the `Runner` |

## Legal

For authorized security testing only. Only test systems you own or have
explicit written permission to assess.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cli/test_base_templates.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add penpine/cli/templates/project tests/cli/test_base_templates.py
git -c commit.gpgsign=false commit -m "feat(cli): add base project templates (main, config, requirements, README, request)"
```

---

### Task 6: `samples/` library templates + offline-run test

**Files:**
- Create: `penpine/cli/templates/project/samples/__init__.py`
- Create: `penpine/cli/templates/project/samples/custom_payload.py`
- Create: `penpine/cli/templates/project/samples/custom_validator.py`
- Create: `penpine/cli/templates/project/samples/custom_module.py`
- Create: `penpine/cli/templates/project/samples/custom_rule.py`
- Create: `penpine/cli/templates/project/samples/custom_auth.py`
- Create: `penpine/cli/templates/project/samples/custom_interceptor.py`
- Create: `penpine/cli/templates/project/samples/data_sharing.py`
- Create: `penpine/cli/templates/project/samples/byo_test_cases.py`
- Test: `tests/cli/test_samples_run.py`

All sample files are VERBATIM (no `.tmpl`) so any literal `{{ }}` is preserved.

- [ ] **Step 1: Write the failing test**

`tests/cli/test_samples_run.py`:
```python
import subprocess
import sys
from datetime import date

import pytest

from penpine.cli.scaffold import render_project

VARS = {
    "project_name": "demo", "project_slug": "demo", "penpine_path": "/tmp/pp",
    "penpine_spec": "penpine", "date": date.today().isoformat(), "python_version": "3.11",
}

SAMPLES = ["custom_payload", "custom_validator", "custom_module", "custom_rule",
           "custom_auth", "custom_interceptor", "data_sharing", "byo_test_cases"]
FINDING_SAMPLES = {"custom_module", "byo_test_cases"}


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    dst = tmp_path_factory.mktemp("proj")
    render_project(dst, VARS, force=True)
    return dst


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_runs_offline(project, name):
    result = subprocess.run([sys.executable, "-m", f"samples.{name}"],
                            cwd=project, capture_output=True, text=True)
    assert result.returncode == 0, f"{name} failed:\n{result.stdout}\n{result.stderr}"
    if name in FINDING_SAMPLES:
        assert "'found': 0" not in result.stdout, f"{name} produced no finding:\n{result.stdout}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cli/test_samples_run.py -v`
Expected: FAIL (sample modules don't exist → subprocess returncode != 0)

- [ ] **Step 3: Create the sample files**

`penpine/cli/templates/project/samples/__init__.py`:
```python
"""Self-contained examples of every penpine extension point."""
```

`penpine/cli/templates/project/samples/custom_payload.py`:
```python
"""Custom PayloadGenerator: yield TestCases (payload + metadata) for a point.

Plug it into an AttackModule (see custom_module.py) to use it in a run.
    python -m samples.custom_payload
"""
from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import InjectionPoint, Payload, TestCase


class HeaderSmugglingGenerator(PayloadGenerator):
    """Emit a few CRLF / header-smuggling probes for any injection point."""

    PAYLOADS = ["x\r\nX-Injected: 1", "x%0d%0aX-Injected:%201"]

    def __init__(self, payloads=None):
        self.payloads = list(payloads) if payloads is not None else list(self.PAYLOADS)

    def generate(self, point, request):
        for value in self.payloads:
            yield TestCase(point=point, payload=Payload(value, technique="crlf"),
                           attack_type="crlf")


def demo():
    point = InjectionPoint(expr="param:q", kind="param", name="q", value="hi")
    cases = list(HeaderSmugglingGenerator().generate(point, None))
    print(f"generated {len(cases)} test cases:")
    for tc in cases:
        print("  ", tc.payload.technique, repr(tc.payload.value))
    return cases


if __name__ == "__main__":
    demo()
```

`penpine/cli/templates/project/samples/custom_validator.py`:
```python
"""Custom Validator: inspect the response (and optional baseline) and return a
Finding when the attack succeeded, else None.
    python -m samples.custom_validator
"""
import re

from penpine.attack.models import Confidence, Finding, InjectionPoint, Payload, TestCase
from penpine.attack.validator import Validator
from penpine.core.parse.http_parser import parse_response

_TRACE = re.compile(rb"Traceback \(most recent call last\)")


class StackTraceValidator(Validator):
    """Flag responses leaking a Python stack trace the baseline did not have."""

    def evaluate(self, test_case, response, baseline=None):
        leaked = _TRACE.search(response.body.raw)
        in_baseline = baseline is not None and _TRACE.search(baseline.body.raw)
        if leaked and not in_baseline:
            return Finding(attack_type="error-leak", point=test_case.point,
                           payload=test_case.payload, confidence=Confidence.MEDIUM,
                           evidence="python stack trace in response",
                           request=test_case.request, response=response)
        return None


def _resp(status, body):
    return parse_response(b"HTTP/1.1 %d X\r\nContent-Length: %d\r\n\r\n%s"
                          % (status, len(body), body))


def demo():
    point = InjectionPoint(expr="param:q", kind="param", name="q", value="hi")
    tc = TestCase(point=point, payload=Payload("'"), attack_type="error-leak")
    finding = StackTraceValidator().evaluate(
        tc, _resp(500, b"Traceback (most recent call last): ValueError"))
    print("finding:", finding and finding.evidence)
    return finding


if __name__ == "__main__":
    demo()
```

`penpine/cli/templates/project/samples/custom_module.py`:
```python
"""Wire a generator + validator into a registered AttackModule.

Once registered, `Runner.run(req, attack="crlf-leak")` (or module=MODULE) selects
points, generates payloads, sends, and validates end to end.
    python -m samples.custom_module
"""
from penpine.attack import Runner, registry
from penpine.attack.analyze import analyze
from penpine.attack.module import AttackModule
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response

from samples.custom_payload import HeaderSmugglingGenerator
from samples.custom_validator import StackTraceValidator

MODULE = AttackModule("crlf-leak", HeaderSmugglingGenerator(), StackTraceValidator(),
                      applies_to=("param", "header"),
                      description="sample CRLF probe + error-leak detector")


def register():
    registry.register(MODULE, replace=True)


class _Sender:
    """Offline fake: leaks a stack trace when a probe was injected."""

    async def send(self, request):
        leaked = b"X-Injected" in request.serialize()
        body = b"Traceback (most recent call last): boom" if leaked else b"ok"
        return parse_response(b"HTTP/1.1 200 X\r\nContent-Length: %d\r\n\r\n%s"
                              % (len(body), body))


def demo():
    register()
    req = Request.from_url("http://target.example/search?q=hi")
    report = Runner(sender=_Sender()).run_sync(req, module=MODULE, points=analyze(req).all())
    print("summary:", report.summary())
    return report


if __name__ == "__main__":
    demo()
```

`penpine/cli/templates/project/samples/custom_rule.py`:
```python
"""Custom analyzer ClassificationRule: tag injection points with attack types.

Pass your rule list to analyze(request, rules=[...]) to influence selection.
    python -m samples.custom_rule
"""
from penpine.attack.analyze import DEFAULT_RULES, analyze
from penpine.attack.analyze.rules import ClassificationRule
from penpine.core.message import Request


class GraphQLRule(ClassificationRule):
    name = "graphql"

    def match(self, point):
        if point.name.lower() in {"query", "operationname", "variables"}:
            return {"graphql-injection"}
        return set()


def demo():
    rules = list(DEFAULT_RULES) + [GraphQLRule()]
    req = Request.from_url("http://target.example/graphql?query=abc&id=1")
    analysis = analyze(req, rules=rules)
    print("tags:", {p.expr: p.attack_types for p in analysis})
    matched = analysis.for_attack("graphql-injection")
    print("graphql points:", [p.expr for p in matched])
    return matched


if __name__ == "__main__":
    demo()
```

`penpine/cli/templates/project/samples/custom_auth.py`:
```python
"""Custom AuthScheme + AuthProfile.

A scheme decides how auth material rides on each request. Bundle a provider +
scheme into an AuthProfile; profile.manager() gives a SessionManager that logs
in, attaches auth, and re-logs in on 401.
    python -m samples.custom_auth
"""
from penpine.auth import AuthProfile, JsonLoginProvider
from penpine.auth.scheme import AuthScheme
from penpine.auth.session import Session
from penpine.core.message import Request


class ApiKeyHeaderScheme(AuthScheme):
    """Attach the session token as a custom X-API-Key header."""

    def __init__(self, header="X-API-Key"):
        self.header = header

    def apply(self, request, session):
        return request.set_header(self.header, session.token or "")


def build_profile():
    provider = JsonLoginProvider(url="http://target.example/login",
                                 payload={"user": "demo", "pw": "demo"},
                                 token_path="$.access_token")
    return AuthProfile(name="demo", provider=provider, scheme=ApiKeyHeaderScheme())


def demo():
    profile = build_profile()
    # Offline: show the scheme applying a token (no network/login round-trip).
    applied = profile.scheme.apply(Request.from_url("http://target.example/api/me"),
                                   Session(token="secret-123"))
    present = b"X-API-Key: secret-123" in applied.serialize()
    print("auth header applied:", present)
    return applied


if __name__ == "__main__":
    demo()
```

`penpine/cli/templates/project/samples/custom_interceptor.py`:
```python
"""Transport Interceptor: hook every send/receive on an Engine.

before_send can mutate/log outgoing requests; after_receive can inspect
responses. Attach with Engine(interceptors=[TaggingInterceptor()]).
    python -m samples.custom_interceptor
"""
import asyncio

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.interceptor import Interceptor


class TaggingInterceptor(Interceptor):
    """Stamp a header on every outgoing request and count responses."""

    def __init__(self, tag="penpine-sample"):
        self.tag = tag
        self.responses = 0

    async def before_send(self, request):
        return request.set_header("X-Penpine", self.tag)

    async def after_receive(self, request, response):
        self.responses += 1
        return response


def demo():
    interceptor = TaggingInterceptor()
    stamped = asyncio.run(interceptor.before_send(Request.from_url("http://target.example/")))
    resp = parse_response(b"HTTP/1.1 200 X\r\nContent-Length: 0\r\n\r\n")
    asyncio.run(interceptor.after_receive(stamped, resp))
    print("stamped:", b"X-Penpine: penpine-sample" in stamped.serialize())
    print("responses seen:", interceptor.responses)
    return stamped


if __name__ == "__main__":
    demo()
```

`penpine/cli/templates/project/samples/data_sharing.py`:
```python
"""Runtime data sharing between two Identities (IDOR pattern).

alice "creates" a resource; the id is captured into a shared Context; bob's
request is rendered with that id — modelling cross-user access testing.
    python -m samples.data_sharing
"""
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.data.context import Context
from penpine.data.extract import Extract
from penpine.data.identity import Identity


def demo():
    shared = Context()
    alice = Identity("alice", context=shared)
    bob = Identity("bob", context=shared)

    body = b'{"id": 4242, "owner": "alice"}'
    created = parse_response(
        b"HTTP/1.1 201 Created\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
        % (len(body), body))
    alice.capture(created, [Extract(key="new_id", json="$.id")])

    probe = bob.render(Request.from_raw(
        b"GET /doc/{{new_id}} HTTP/1.1\r\nHost: target.example\r\n\r\n"))
    line = probe.serialize().split(b"\r\n")[0].decode()
    print("bob probes:", line)
    return line


if __name__ == "__main__":
    demo()
```

`penpine/cli/templates/project/samples/byo_test_cases.py`:
```python
"""Bring-your-own TestCases: skip generation, hand the Runner explicit cases.
    python -m samples.byo_test_cases
"""
from penpine.attack import Runner
from penpine.attack.models import Confidence, Finding, InjectionPoint, Payload, TestCase
from penpine.attack.validator import Validator
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response


class ContainsValidator(Validator):
    def __init__(self, needle):
        self.needle = needle.encode()

    def evaluate(self, test_case, response, baseline=None):
        if self.needle in response.body.raw:
            return Finding(attack_type="byo", point=test_case.point,
                           payload=test_case.payload, confidence=Confidence.HIGH,
                           evidence=f"matched {self.needle!r}",
                           request=test_case.request, response=response)
        return None


class _Sender:
    async def send(self, request):
        body = b"unexpected token FOOBAR" if b"FOOBAR" in request.serialize() else b"ok"
        return parse_response(b"HTTP/1.1 200 X\r\nContent-Length: %d\r\n\r\n%s"
                              % (len(body), body))


def demo():
    req = Request.from_url("http://target.example/api?name=alice")
    point = InjectionPoint(expr="param:name", kind="param", name="name", value="alice")
    cases = [TestCase(point=point, payload=Payload("FOOBAR"), attack_type="byo")]
    report = Runner(sender=_Sender()).run_sync(req, test_cases=cases,
                                               validator=ContainsValidator("FOOBAR"))
    print("summary:", report.summary())
    return report


if __name__ == "__main__":
    demo()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cli/test_samples_run.py -v`
Expected: PASS (8 parametrized cases). If `custom_module` or `byo_test_cases` shows `'found': 0`, the fake sender / point selection is wrong — debug before proceeding.

- [ ] **Step 5: Commit**

```bash
git add penpine/cli/templates/project/samples tests/cli/test_samples_run.py
git -c commit.gpgsign=false commit -m "feat(cli): add samples library (one offline-runnable example per extension point)"
```

---

### Task 7: `commands/new.py` — orchestration + rollback

**Files:**
- Create: `penpine/cli/commands/new.py`
- Test: `tests/cli/test_command_new.py`

- [ ] **Step 1: Write the failing test**

`tests/cli/test_command_new.py`:
```python
import pytest

from penpine.cli.commands import new as new_cmd
from penpine.cli.exceptions import ScaffoldError


def test_no_venv_renders_full_tree(tmp_path):
    project = new_cmd.run("eng", target_dir=str(tmp_path), create_venv=False)
    assert project == tmp_path / "eng"
    for rel in ("main.py", "config.py", "requirements.txt", ".gitignore",
                "requests/sample.http", "docs/README.md",
                "samples/custom_module.py"):
        assert (project / rel).exists(), rel
    # editable spec auto-detected from THIS repo
    assert "-e " in (project / "requirements.txt").read_text()


def test_non_empty_target_without_force_is_left_untouched(tmp_path):
    project = tmp_path / "eng"
    project.mkdir()
    (project / "keep.txt").write_text("mine")
    with pytest.raises(ScaffoldError):
        new_cmd.run("eng", target_dir=str(tmp_path), create_venv=False)
    assert (project / "keep.txt").read_text() == "mine"
    assert not (project / "main.py").exists()


def test_rollback_removes_dir_we_created_on_failure(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("render exploded")
    monkeypatch.setattr(new_cmd.scaffold, "render_project", boom)
    with pytest.raises(RuntimeError):
        new_cmd.run("eng", target_dir=str(tmp_path), create_venv=False)
    assert not (tmp_path / "eng").exists()  # cleaned up


def test_venv_failure_is_downgraded_not_raised(tmp_path, monkeypatch):
    from penpine.cli.exceptions import VenvError
    def boom(*a, **k):
        raise VenvError("pip died")
    monkeypatch.setattr(new_cmd.venv, "create_venv", boom)
    # does NOT raise; files remain
    project = new_cmd.run("eng", target_dir=str(tmp_path), create_venv=True)
    assert (project / "main.py").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cli/test_command_new.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'penpine.cli.commands.new'`

- [ ] **Step 3: Write the implementation**

`penpine/cli/commands/new.py`:
```python
"""The `penpine new` command: scaffold a project, optionally build its venv."""
from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

from penpine.cli import paths, scaffold, venv
from penpine.cli.exceptions import ScaffoldError, VenvError
from penpine.logging import get_logger

log = get_logger(__name__)


def run(name: str, *, target_dir: str = ".", create_venv: bool = True,
        force: bool = False, python: str | None = None) -> Path:
    project = Path(target_dir) / name
    we_created_dir = not project.exists()
    if project.exists() and any(project.iterdir()) and not force:
        raise ScaffoldError(f"target {project} is not empty (use --force)")

    root = paths.find_penpine_root()
    if root is None:
        log.warning("could not detect a local penpine source; requirements.txt will "
                    "use a plain 'penpine' spec (needs penpine on an index)")

    variables = {
        "project_name": name,
        "project_slug": paths.slugify(name),
        "penpine_path": str(root) if root else "",
        "penpine_spec": paths.penpine_spec(root),
        "date": date.today().isoformat(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
    }

    try:
        scaffold.render_project(project, variables, force=force)
    except Exception:
        if we_created_dir and project.exists():
            shutil.rmtree(project, ignore_errors=True)
        raise

    if create_venv:
        try:
            venv.create_venv(project, python=python)
            venv.pip_install(project)
        except VenvError as exc:
            log.warning("%s", exc)
            log.warning("finish setup manually: cd %s && python -m venv .venv && "
                        "source .venv/bin/activate && pip install -r requirements.txt", project)
    return project
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cli/test_command_new.py -v`
Expected: PASS (4 tests). Note: `test_venv_failure...` builds the real tree but the monkeypatched `create_venv` raises immediately, so no real venv is created.

- [ ] **Step 5: Commit**

```bash
git add penpine/cli/commands/new.py tests/cli/test_command_new.py
git -c commit.gpgsign=false commit -m "feat(cli): add new-command orchestration with rollback and tolerant venv"
```

---

### Task 8: `main.py` entry point, `__main__`, and packaging

**Files:**
- Create: `penpine/cli/main.py`
- Create: `penpine/cli/__main__.py`
- Create: `MANIFEST.in`
- Modify: `pyproject.toml` (add `[project.scripts]`, `[tool.setuptools.package-data]`, pytest `slow` marker)
- Test: `tests/cli/test_main.py`

- [ ] **Step 1: Write the failing test**

`tests/cli/test_main.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cli/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'penpine.cli.main'`

- [ ] **Step 3: Write the implementation + packaging**

`penpine/cli/main.py`:
```python
"""penpine CLI entry point."""
from __future__ import annotations

import argparse
import sys

from penpine.cli.commands import new as new_cmd
from penpine.cli.exceptions import CliError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="penpine",
                                     description="penpine pentesting framework CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="scaffold a new penpine project")
    new.add_argument("name", help="project name (becomes the directory)")
    new.add_argument("--dir", default=".", help="parent directory (default: current)")
    new.add_argument("--no-venv", dest="venv", action="store_false",
                     help="skip virtualenv creation and dependency install")
    new.add_argument("--force", action="store_true",
                     help="scaffold into a non-empty directory")
    new.add_argument("--python", default=None,
                     help="interpreter used to build the virtualenv")
    new.set_defaults(venv=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "new":
            project = new_cmd.run(args.name, target_dir=args.dir,
                                  create_venv=args.venv, force=args.force,
                                  python=args.python)
            print(f"created {project}")
            print("next steps:")
            print(f"  cd {project}")
            if args.venv:
                print("  source .venv/bin/activate")
            else:
                print("  python -m venv .venv && source .venv/bin/activate")
                print("  pip install -r requirements.txt")
            print("  # edit config.py: set TARGET_HOST to an authorized target")
            print("  python main.py")
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
```

`penpine/cli/__main__.py`:
```python
"""Enable `python -m penpine`."""
from penpine.cli.main import main

raise SystemExit(main())
```

`MANIFEST.in`:
```
recursive-include penpine/cli/templates *
```

In `pyproject.toml`, after the `[project.optional-dependencies]` block add:
```toml
[project.scripts]
penpine = "penpine.cli.main:main"

[tool.setuptools.package-data]
"penpine.cli" = ["templates/**/*", "templates/**/.*"]
```

And extend the existing `[tool.pytest.ini_options]` table with a markers entry (keep the existing `testpaths` and `asyncio_mode` lines):
```toml
markers = ["slow: end-to-end tests that build a real virtualenv (opt-in)"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cli/test_main.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Reinstall to register the console script and verify**

Run: `pip install -e . >/dev/null && penpine new /tmp/penpine_demo_$$ --no-venv --dir /tmp && echo OK`
Expected: prints `created ...` then `OK`. (Confirms the `penpine` console script resolves and templates are packaged.)

- [ ] **Step 6: Commit**

```bash
git add penpine/cli/main.py penpine/cli/__main__.py MANIFEST.in pyproject.toml tests/cli/test_main.py
git -c commit.gpgsign=false commit -m "feat(cli): add penpine entry point, python -m support, and packaging"
```

---

### Task 9: Opt-in end-to-end venv test

**Files:**
- Test: `tests/cli/test_e2e_venv.py`

- [ ] **Step 1: Write the test (gated, skipped by default)**

`tests/cli/test_e2e_venv.py`:
```python
import os
import subprocess
import sys

import pytest

from penpine.cli.commands import new as new_cmd

pytestmark = pytest.mark.slow

requires_optin = pytest.mark.skipif(
    "PENPINE_SLOW" not in os.environ,
    reason="set PENPINE_SLOW=1 to run the real-venv end-to-end test")


@requires_optin
def test_real_venv_install_and_import(tmp_path):
    project = new_cmd.run("eng", target_dir=str(tmp_path), create_venv=True)
    venv_python = project / ".venv" / "bin" / "python"
    assert venv_python.exists()
    # penpine importable inside the freshly built venv
    result = subprocess.run([str(venv_python), "-c", "import penpine, config; print('ok')"],
                            cwd=project, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
```

- [ ] **Step 2: Verify it is collected but skipped by default**

Run: `python -m pytest tests/cli/test_e2e_venv.py -v`
Expected: SKIPPED (1 skipped) — message mentions `PENPINE_SLOW`.

- [ ] **Step 3: (Optional, local only) run it for real**

Run: `PENPINE_SLOW=1 python -m pytest tests/cli/test_e2e_venv.py -v`
Expected: PASS (builds a real venv; needs network for pip). Skip in CI.

- [ ] **Step 4: Commit**

```bash
git add tests/cli/test_e2e_venv.py
git -c commit.gpgsign=false commit -m "test(cli): add opt-in end-to-end real-venv test"
```

---

### Final verification (after all tasks)

- [ ] Run the whole suite: `python -m pytest -q` — expect all prior 300 tests plus the new CLI tests passing (the one slow test skipped).
- [ ] Manually scaffold and run a project offline to confirm the headline UX:
```bash
penpine new /tmp/penpine_check --dir /tmp --no-venv
cd /tmp/penpine_check && python -m samples.custom_module   # prints a finding summary
```

---

## Self-Review

**Spec coverage:**
- §1/§3 module layout → Tasks 1–8 create `exceptions`, `paths`, `scaffold`, `venv`, `commands/new`, `main`, `__main__`, `templates/`. ✓
- §4 rendering (`.tmpl` substitution, verbatim copy, `{{ }}` regex, unknown-placeholder error) → Task 3. ✓ (Added a `dot-` filename rule, surfaced in §6 layout via `.gitignore`; covered in Task 3 test.)
- §5 path detection + slug + fallback spec → Task 2; fallback warning → Task 7. ✓
- §6 generated layout (main/config/requests/samples/docs/requirements/.gitignore) → Tasks 5–6; safe-by-default `TARGET_HOST` → Task 5; offline samples → Task 6. ✓
- §7 packaging (scripts, package-data, MANIFEST, importlib/source access) → Task 8 (renderer uses module-relative `Path(__file__)`, which is robust for the editable install this targets). ✓
- §8 command flow + flags + rollback → Tasks 7–8. ✓
- §9 errors (`CliError`/`ScaffoldError`/`VenvError`, exit 2) → Tasks 1, 8. ✓
- §10 testing (unit, integration import/run, CLI smoke, opt-in slow) → Tasks 2–9. ✓

**Placeholder scan:** No TBD/TODO; every code step contains complete content. ✓

**Type consistency:** `render_project(dst, variables, *, source=None, force=False)`, `create_venv(project_dir, *, python=None, runner=...)`, `pip_install(project_dir, *, runner=...)`, `new_cmd.run(name, *, target_dir, create_venv, force, python)`, `find_penpine_root()/penpine_spec()/slugify()` are used identically across tasks. Sample APIs (`PayloadGenerator.generate`, `Validator.evaluate(self, tc, response, baseline=None)`, `AttackModule(name, gen, val, applies_to=, description=)`, `registry.register(module, replace=True)`, `ClassificationRule.match`, `Interceptor.before_send/after_receive`, `Identity(context=...)/.capture/.render`, `Extract(key=, json=)`, `Runner.run_sync(..., module=/points=/test_cases=/validator=)`) match the verified library signatures. ✓
