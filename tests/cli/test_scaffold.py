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
    assert (dst / "main.py").read_text() == "name = demo\n"  # .tmpl rendered + suffix stripped
    assert (
        dst / "keep.http"
    ).read_text() == "literal {{ x }} stays\n"  # verbatim, braces preserved
    assert (dst / ".gitignore").read_text() == ".venv/\n"  # dot- prefix mapped
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
