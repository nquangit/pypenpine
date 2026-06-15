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
