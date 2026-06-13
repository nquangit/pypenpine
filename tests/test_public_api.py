import penpine


def test_top_level_exports():
    assert hasattr(penpine, "Request")
    assert hasattr(penpine, "Response")
    assert hasattr(penpine, "RequestBuilder")
    assert hasattr(penpine, "configure_logging")
    r = penpine.Request.from_url("http://h/a")
    assert r.method == "GET"
