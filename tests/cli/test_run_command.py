from penpine.cli.commands.run import run
from penpine.core.parse.http_parser import parse_response


class FakeSender:
    """Records sent requests; returns a SQL-error body when a quote was injected."""

    def __init__(self):
        self.calls = []

    async def send(self, request):
        self.calls.append(request)
        raw = request.serialize()
        if b"%27" in raw or b"'" in raw:
            body = b"You have an error in your SQL syntax near '''"
        else:
            body = b"<html>ok</html>"
        return parse_response(b"HTTP/1.1 200 X\r\nContent-Length: %d\r\n\r\n" % len(body) + body)


class CleanSender:
    def __init__(self):
        self.calls = []

    async def send(self, request):
        self.calls.append(request)
        body = b"<html>ok</html>"
        return parse_response(b"HTTP/1.1 200 X\r\nContent-Length: %d\r\n\r\n" % len(body) + body)


def test_dry_run_lists_points_and_sends_nothing(capsys):
    fake = FakeSender()
    rc = run(curl="curl 'http://h/s?q=hi'", attacks="sqli", dry_run=True, sender=fake)
    out = capsys.readouterr().out
    assert rc == 0
    assert "would attack (sqli):" in out
    assert "param:q" in out
    assert "payloads" in out
    assert fake.calls == []  # nothing sent


def test_execute_reports_finding_and_exit_codes(capsys):
    rc = run(curl="curl 'http://h/s?q=hi'", attacks="sqli", sender=FakeSender())
    out = capsys.readouterr().out
    assert rc == 0
    assert "== sqli ==" in out
    assert "[HIGH]" in out
    assert "param:q" in out


def test_fail_on_findings_sets_exit_1():
    rc = run(
        curl="curl 'http://h/s?q=hi'", attacks="sqli", fail_on_findings=True, sender=FakeSender()
    )
    assert rc == 1


def test_clean_run_exit_0_even_with_fail_flag(capsys):
    rc = run(
        curl="curl 'http://h/s?q=hi'", attacks="sqli", fail_on_findings=True, sender=CleanSender()
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "found 0" in out
