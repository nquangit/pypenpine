import logging

from penpine.logging import configure_logging, get_logger


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
    from rich.logging import RichHandler

    log = configure_logging(level=logging.DEBUG)
    assert log.level == logging.DEBUG
    assert any(isinstance(h, RichHandler) for h in log.handlers)
    n = len(log.handlers)
    configure_logging(level=logging.INFO)
    assert len(log.handlers) == n


def test_bracketed_log_does_not_raise():
    configure_logging(level=logging.INFO)
    # unbalanced markup in a normal (non-interceptor) log site must not crash
    get_logger("penpine.x").info("server said: %s", "boom [/] [not-a-tag")


def test_console_handler_filters_request_records():
    from rich.logging import RichHandler

    log = configure_logging(level=logging.INFO)
    console_h = next(h for h in log.handlers if isinstance(h, RichHandler))
    normal = logging.LogRecord("penpine.x", logging.INFO, "f", 1, "hi", None, None)
    request = logging.LogRecord("penpine.x", logging.INFO, "f", 1, "hi", None, None)
    request._penpine_request = True
    assert console_h.filter(normal)  # normal records pass
    assert console_h.filter(request) is False  # request-audit records dropped
