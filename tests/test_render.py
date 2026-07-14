from penpine.render import (
    _confidence_style,
    _humanize_bytes,
    _status_style,
    _truncate,
    console,
)


def test_status_style_by_class():
    assert _status_style(200) == "green"
    assert _status_style(301) == "cyan"
    assert _status_style(404) == "yellow"
    assert _status_style(500) == "red"
    assert _status_style("?") == "red"


def test_confidence_style_by_name():
    class _C:
        def __init__(self, name):
            self.name = name

    assert _confidence_style(_C("HIGH")) == "bold red"
    assert _confidence_style(_C("MEDIUM")) == "yellow"
    assert _confidence_style(_C("LOW")) == "dim cyan"


def test_humanize_bytes():
    assert _humanize_bytes(512) == "512 B"
    assert _humanize_bytes(1536) == "1.5 kB"


def test_truncate_adds_ellipsis():
    assert _truncate("abc", 10) == "abc"
    assert _truncate("abcdef", 4).endswith("…")
    assert len(_truncate("abcdef", 4)) == 4


def test_console_is_a_rich_console():
    from rich.console import Console

    assert isinstance(console, Console)
