import pytest

from penpine.attack import registry
from penpine.attack.modules import BUILTIN_MODULES, register_builtins


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def test_register_builtins_registers_all_and_is_idempotent():
    register_builtins()
    for name in ("sqli", "xss", "path-traversal", "open-redirect"):
        assert registry.get(name)
    register_builtins()
    assert set(registry.list_modules()) >= {"sqli", "xss", "path-traversal", "open-redirect"}
    assert len(BUILTIN_MODULES) >= 4


def test_import_has_no_side_effects():
    import subprocess
    import sys

    code = (
        "import penpine.attack, penpine.attack.modules\n"
        "from penpine.attack import registry\n"
        "print(registry.list_modules())\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"  # fresh import registers nothing


def test_attack_package_reexports():
    from penpine.attack import BUILTIN_MODULES as bm
    from penpine.attack import register_builtins as rb

    assert rb is register_builtins
    assert bm is BUILTIN_MODULES
