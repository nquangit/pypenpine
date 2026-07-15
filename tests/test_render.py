from rich.console import Console

from penpine.attack.models import Confidence, Finding, InjectionPoint, Payload
from penpine.attack.results import Attempt, Report
from penpine.attack.types import AttackType
from penpine.render import (
    RequestTableRenderer,
    _confidence_style,
    _humanize_bytes,
    _status_style,
    _truncate,
    console,
    render_report,
    render_run_summary,
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


def _point(expr="param:id"):
    return InjectionPoint(expr=expr, kind="param", name="id")


def _finding(evidence="SQL syntax error near", payload="' OR 1=1-- -"):
    return Finding(
        attack_type=AttackType.SQLI,
        point=_point(),
        payload=Payload(value=payload),
        confidence=Confidence.HIGH,
        evidence=evidence,
    )


class _Resp:
    def __init__(self, status_code=500):
        self.status_code = status_code


def _rec():  # a recording console
    return Console(record=True, width=100)


def test_render_report_with_finding_shows_fields():
    c = _rec()
    att = Attempt(test_case=object(), response=_Resp(500), finding=_finding(), elapsed_ms=28.0)
    report = Report(request=object(), attack_type=AttackType.SQLI, baseline=None, attempts=[att])
    render_report(report, console=c)
    out = c.export_text()
    assert "param:id" in out
    assert "1=1" in out
    assert "SQL syntax error" in out
    assert "HIGH" in out
    assert "sqli" in out


def test_render_report_no_findings_shows_summary():
    c = _rec()
    att = Attempt(test_case=object(), response=_Resp(200))
    report = Report(request=object(), attack_type=AttackType.XSS, baseline=None, attempts=[att])
    render_report(report, console=c)
    out = c.export_text()
    assert "sent=" in out
    assert "found=0" in out


def test_render_report_shows_errors():
    c = _rec()
    att = Attempt(test_case=object(), error=RuntimeError("connection refused"))
    report = Report(request=object(), attack_type=AttackType.SQLI, baseline=None, attempts=[att])
    render_report(report, console=c)
    out = c.export_text()
    assert "errors:" in out
    assert "connection refused" in out


def test_render_report_escapes_markup_in_payload():
    c = _rec()
    att = Attempt(
        test_case=object(),
        response=_Resp(500),
        finding=_finding(payload="[bold]pwn[/]"),
        elapsed_ms=1.0,
    )
    report = Report(request=object(), attack_type=AttackType.SQLI, baseline=None, attempts=[att])
    render_report(report, console=c)
    out = c.export_text()
    assert "[bold]pwn[/]" in out  # literal, not interpreted as markup


def test_render_run_summary_totals_and_labels():
    c = _rec()
    r1 = Report(
        request=object(),
        attack_type=AttackType.SQLI,
        baseline=None,
        attempts=[
            Attempt(test_case=object(), response=_Resp(500), finding=_finding(), elapsed_ms=1.0),
            Attempt(test_case=object(), error=RuntimeError("x")),
        ],
    )
    r2 = Report(
        request=object(),
        attack_type=AttackType.XSS,
        baseline=None,
        attempts=[Attempt(test_case=object(), response=_Resp(200))],
    )
    render_run_summary([("login.php / sqli", r1), ("login.php / xss", r2)], console=c)
    out = c.export_text()
    assert "login.php / sqli" in out
    assert "login.php / xss" in out
    assert "TOTAL" in out
    # totals: sent 2+1=3, failed 1, found 1
    assert "3" in out and "TOTAL" in out


def test_run_summary_empty_does_not_crash():
    c = _rec()
    render_run_summary([], console=c)
    assert "TOTAL" in c.export_text()


def test_render_symbols_reexported_from_root():
    import penpine

    assert hasattr(penpine, "render_report")
    assert hasattr(penpine, "render_run_summary")
    assert hasattr(penpine, "console")


def _table_console():
    return Console(record=True, width=60)


def test_request_table_aligns_columns_and_shows_header_once():
    c = _table_console()
    r = RequestTableRenderer(console=c)
    r.row(status=200, method="GET", size="1.2 kB", timing="12 ms", url="/aaa")
    r.row(status=404, method="POST", size="3 B", timing="1 ms", url="/bbb")
    lines = [ln for ln in c.export_text().splitlines() if ln.strip()]
    # header printed exactly once
    assert sum(1 for ln in lines if "STATUS" in ln and "URL" in ln) == 1
    data = [ln for ln in lines if "/aaa" in ln or "/bbb" in ln]
    assert len(data) == 2
    # URL column starts at the same offset on both data rows (alignment)
    assert data[0].index("/aaa") == data[1].index("/bbb")


def test_request_table_folds_long_url():
    c = _table_console()
    r = RequestTableRenderer(console=c)
    r.row(status=200, method="GET", size="1 B", timing="1 ms", url="/x?" + "A" * 200)
    text = c.export_text()
    # a 200-char URL cannot fit one 60-col line -> folds across multiple lines
    assert text.count("A") >= 200
    assert len([ln for ln in text.splitlines() if "A" in ln]) >= 2


def test_request_table_failed_row_and_escaping():
    c = Console(record=True, width=100)  # wide enough that the detail doesn't wrap mid-word
    r = RequestTableRenderer(console=c)
    r.row(
        status="ERR",
        method="POST",
        size="—",
        timing="—",
        url="/login  · ConnectionRefusedError: [refused]",
        failed=True,
    )
    text = c.export_text()
    assert "ERR" in text
    assert "ConnectionRefusedError" in text
    assert "[refused]" in text  # markup escaped -> literal brackets survive


def test_request_table_renderer_reexported():
    import penpine

    assert hasattr(penpine, "RequestTableRenderer")


def test_request_table_escapes_size_and_timing():
    c = Console(record=True, width=60)
    r = RequestTableRenderer(console=c)
    # markup kept short enough to fit the fixed-width SIZE (8) / TOOK (7) columns
    # on one line, so wrapping doesn't split the literal brackets across rows.
    r.row(status=200, method="GET", size="[i]1B[/]", timing="[b]9[/]", url="/x")
    text = c.export_text()
    assert "[i]1B[/]" in text and "[b]9[/]" in text


def test_request_table_shows_timestamp_and_header_labels():
    c = Console(record=True, width=80)
    r = RequestTableRenderer(console=c)
    r.row(status=200, method="GET", size="1 B", timing="1 ms", url="/x", timestamp="20:56:11")
    text = c.export_text()
    assert "20:56:11" in text
    assert "TIME" in text and "TOOK" in text  # header renamed/added


def test_request_table_shows_injection_location_and_value():
    from penpine.transport.trace import InjectionInfo

    c = Console(record=True, width=80)
    r = RequestTableRenderer(console=c)
    r.row(
        status=200,
        method="POST",
        size="1 B",
        timing="1 ms",
        url="/api/login",
        timestamp="20:56:11",
        injection=InjectionInfo(locator="json:$.user", value="' OR 1=1"),
    )
    text = c.export_text()
    assert "json:$.user" in text
    assert "' OR 1=1" in text
    assert "=" in text


def test_request_table_injection_value_escaped():
    from penpine.transport.trace import InjectionInfo

    c = Console(record=True, width=80)
    r = RequestTableRenderer(console=c)
    r.row(
        status=200,
        method="GET",
        size="1 B",
        timing="1 ms",
        url="/x",
        timestamp="t",
        injection=InjectionInfo(locator="param:q", value="[bold]pwn[/]"),
    )
    assert "[bold]pwn[/]" in c.export_text()  # literal, markup not interpreted


def test_request_table_no_injection_shows_url_only():
    c = Console(record=True, width=80)
    r = RequestTableRenderer(console=c)
    r.row(status=200, method="GET", size="1 B", timing="1 ms", url="/only-url", timestamp="t")
    text = c.export_text()
    assert "/only-url" in text and "=" not in text.split("/only-url")[1]
