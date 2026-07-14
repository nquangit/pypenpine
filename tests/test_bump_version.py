import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "bump_version", Path(__file__).resolve().parents[1] / "scripts" / "bump_version.py"
)
bump_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump_version)


def test_next_version_levels():
    assert bump_version.next_version("0.0.1", "patch") == "0.0.2"
    assert bump_version.next_version("0.0.1", "minor") == "0.1.0"
    assert bump_version.next_version("0.0.1", "major") == "1.0.0"
    assert bump_version.next_version("1.2.3", "minor") == "1.3.0"
    assert bump_version.next_version("1.2.3", "major") == "2.0.0"


def test_next_version_explicit_must_increase():
    assert bump_version.next_version("0.1.0", "0.2.0") == "0.2.0"
    with pytest.raises(ValueError):
        bump_version.next_version("0.2.0", "0.1.0")
    with pytest.raises(ValueError):
        bump_version.next_version("0.2.0", "0.2.0")  # equal is not an increase


def test_parse_version_rejects_non_xyz():
    with pytest.raises(ValueError):
        bump_version.parse_version("1.2")
    with pytest.raises(ValueError):
        bump_version.parse_version("1.2.3b1")


def test_read_and_rewrite_version_touches_only_version_line():
    text = '[project]\nname = "penpine"\nversion = "0.0.1"\ndescription = "x"\n'
    assert bump_version.read_version(text) == "0.0.1"
    out = bump_version.rewrite_version(text, "0.1.0")
    assert 'version = "0.1.0"' in out
    assert bump_version.read_version(out) == "0.1.0"
    # nothing else changed
    assert out.replace('"0.1.0"', '"0.0.1"') == text


def test_read_version_missing_raises():
    with pytest.raises(ValueError):
        bump_version.read_version('[project]\nname = "penpine"\n')
