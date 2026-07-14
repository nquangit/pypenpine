import penpine


def test_top_level_exports():
    assert hasattr(penpine, "Request")
    assert hasattr(penpine, "Response")
    assert hasattr(penpine, "RequestBuilder")
    assert hasattr(penpine, "configure_logging")
    assert hasattr(penpine, "render_report")
    assert hasattr(penpine, "render_run_summary")
    assert hasattr(penpine, "console")
    r = penpine.Request.from_url("http://h/a")
    assert r.method == "GET"
