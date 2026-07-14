from datetime import date

from penpine.cli.scaffold import render_project

VARS = {
    "project_name": "demo-eng",
    "project_slug": "demo_eng",
    "date": date.today().isoformat(),
    "python_version": "3.11",
}


def test_base_files_render_and_compile(tmp_path):
    dst = tmp_path / "proj"
    render_project(dst, VARS)  # real templates
    for rel in (
        "main.py",
        "config.py",
        "requirements.txt",
        ".gitignore",
        "requests/sample.http",
        "docs/README.md",
    ):
        assert (dst / rel).exists(), rel
    # requirements install penpine from the Gitea registry
    reqs = (dst / "requirements.txt").read_text()
    assert "--extra-index-url" in reqs
    assert "penpine" in reqs
    assert "-e " not in reqs
    # main.py and config.py are valid Python
    compile((dst / "main.py").read_text(), "main.py", "exec")
    compile((dst / "config.py").read_text(), "config.py", "exec")
    # the sample request keeps its runtime placeholder verbatim
    assert "__TARGET_HOST__" in (dst / "requests" / "sample.http").read_text()
    # README carries the project name
    assert "demo-eng" in (dst / "docs" / "README.md").read_text()
