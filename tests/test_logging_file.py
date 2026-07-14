import logging

import pytest

from penpine.logging import configure_logging, get_logger

_ROOT = "penpine"


@pytest.fixture(autouse=True)
def _clean_penpine_logger():
    log = logging.getLogger(_ROOT)
    saved = log.handlers[:]
    log.handlers.clear()
    yield
    log.handlers.clear()
    log.handlers.extend(saved)


def test_configure_logging_accepts_level_name():
    log = configure_logging(level="WARNING")
    assert log.level == logging.WARNING


def test_configure_logging_writes_to_file(tmp_path):
    path = tmp_path / "run.log"
    configure_logging(level="DEBUG", log_file=str(path))
    get_logger("penpine.demo").debug("hello-file")
    for h in logging.getLogger(_ROOT).handlers:
        h.flush()
    assert "hello-file" in path.read_text()


def test_configure_logging_is_idempotent(tmp_path):
    path = tmp_path / "run.log"
    configure_logging(log_file=str(path))
    n = len(logging.getLogger(_ROOT).handlers)
    configure_logging(log_file=str(path))
    assert len(logging.getLogger(_ROOT).handlers) == n
