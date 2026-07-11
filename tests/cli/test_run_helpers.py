import pytest

from penpine.cli.commands.run import _build_request, _resolve_attacks
from penpine.cli.exceptions import CliError


def test_build_request_from_curl_sets_meta():
    req = _build_request(curl="curl 'https://t.example/api?id=1'")
    assert req.method == "GET"
    assert req.meta.host == "t.example"
    assert req.meta.port == 443


def test_build_request_from_url_sets_meta():
    req = _build_request(url="https://h/s?q=hi")
    assert req.meta.host == "h"
    assert req.meta.scheme == "https"


def test_build_request_from_file_needs_target(tmp_path):
    f = tmp_path / "r.http"
    f.write_text("GET /p HTTP/1.1\r\nHost: h\r\n\r\n")
    req = _build_request(request_file=str(f), target="https://h:8443")
    assert req.meta.host == "h"
    assert req.meta.port == 8443
    with pytest.raises(CliError):
        _build_request(request_file=str(f))  # no --target


def test_build_request_requires_exactly_one_input():
    with pytest.raises(CliError):
        _build_request()  # zero
    with pytest.raises(CliError):
        _build_request(curl="curl x", url="http://h/")  # two


def test_build_request_bad_curl_is_cli_error():
    with pytest.raises(CliError):
        _build_request(curl="curl -X POST")  # no URL -> BuildError -> CliError


def test_resolve_attacks_all_returns_builtins():
    names = _resolve_attacks("all")
    assert set(names) == {"sqli", "xss", "path-traversal", "open-redirect"}


def test_resolve_attacks_subset_and_unknown():
    assert _resolve_attacks("sqli,xss") == ["sqli", "xss"]
    with pytest.raises(CliError):
        _resolve_attacks("nope")
    with pytest.raises(CliError):
        _resolve_attacks(" , ")  # empty
