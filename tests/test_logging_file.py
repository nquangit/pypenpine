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


def test_file_handler_strips_markup(tmp_path):
    path = tmp_path / "run.log"
    configure_logging(level="INFO", log_file=str(path))
    get_logger("penpine.demo").info("[green]200[/] hello-markup", extra={"markup": True})
    for h in logging.getLogger(_ROOT).handlers:
        h.flush()
    text = path.read_text()
    assert "hello-markup" in text
    assert "[green]" not in text  # markup stripped in file output


def test_file_preserves_nonmarkup_brackets(tmp_path):
    path = tmp_path / "run.log"
    configure_logging(level="INFO", log_file=str(path))
    get_logger("penpine.demo").info("payload [bold]pwn[/] kept")
    for h in logging.getLogger(_ROOT).handlers:
        h.flush()
    text = path.read_text()
    assert "[bold]pwn[/]" in text  # non-markup record: brackets preserved verbatim


def test_file_handler_keeps_request_records(tmp_path):
    path = tmp_path / "run.log"
    configure_logging(level="INFO", log_file=str(path))
    get_logger("penpine.transport").info("200 GET /x (12 ms)", extra={"_penpine_request": True})
    for h in logging.getLogger(_ROOT).handlers:
        h.flush()
    assert "200 GET /x" in path.read_text()  # file keeps the audit line
