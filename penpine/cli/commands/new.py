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
