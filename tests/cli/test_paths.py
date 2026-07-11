from pathlib import Path

from penpine.cli.paths import find_penpine_root, penpine_spec, slugify


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
