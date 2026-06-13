import logging
from penpine.logging import get_logger, configure_logging


def test_get_logger_returns_namespaced_logger():
    log = get_logger("penpine.core.foo")
    assert isinstance(log, logging.Logger)
    assert log.name == "penpine.core.foo"


def test_no_import_side_effects_on_root():
    root = logging.getLogger()
    before = len(root.handlers)
    get_logger("penpine.x")
    assert len(root.handlers) == before


def test_configure_logging_sets_level_and_handler():
    log = configure_logging(level=logging.DEBUG)
    assert log.level == logging.DEBUG
    assert any(h for h in log.handlers)
    n = len(log.handlers)
    configure_logging(level=logging.INFO)
    assert len(log.handlers) == n
