"""Rich terminal rendering for reports and findings (presentation-only)."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

__all__ = ["console", "render_report", "render_run_summary"]

console = Console()

_MAX_FIELD = 200
_CONFIDENCE_STYLES = {"HIGH": "bold red", "MEDIUM": "yellow", "LOW": "dim cyan"}


def _status_style(status: object) -> str:
    try:
        code = int(status)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "red"
    if 200 <= code < 300:
        return "green"
    if 300 <= code < 400:
        return "cyan"
    if 400 <= code < 500:
        return "yellow"
    return "red"


def _confidence_style(confidence: object) -> str:
    name = getattr(confidence, "name", str(confidence))
    return _CONFIDENCE_STYLES.get(name, "white")


def _humanize_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    kb = n / 1024
    if kb < 1024:
        return f"{kb:.1f} kB"
    return f"{kb / 1024:.1f} MB"


def _truncate(s: object, limit: int = _MAX_FIELD) -> str:
    s = str(s)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _finding_panel(finding: object, attempt: object) -> Panel:
    conf_name = getattr(finding.confidence, "name", str(finding.confidence))
    style = _confidence_style(finding.confidence)
    attack = getattr(finding.attack_type, "value", finding.attack_type)
    title = f"[{style}]FINDING · {conf_name} · {escape(str(attack))}[/]"

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="right")
    grid.add_column()
    grid.add_row("point", escape(str(finding.point.expr)))
    payload_val = getattr(finding.payload, "value", finding.payload)
    grid.add_row("payload", escape(_truncate(payload_val)))

    response = getattr(attempt, "response", None) or getattr(finding, "response", None)
    if response is not None:
        status = getattr(response, "status_code", "?")
        elapsed = getattr(attempt, "elapsed_ms", None)
        timing = f"  ({elapsed:.0f} ms)" if elapsed is not None else ""
        grid.add_row("status", f"[{_status_style(status)}]{escape(str(status))}[/]{timing}")

    grid.add_row("evidence", escape(_truncate(finding.evidence)))
    return Panel(grid, title=title, title_align="left", border_style=style, expand=False)


def render_report(report: object, *, console: Console = console) -> None:
    summary = report.summary()
    attack = getattr(report.attack_type, "value", report.attack_type)
    found = summary["found"]
    found_txt = f"[bold red]{found}[/]" if found else "0"
    console.print(
        f"\n[bold]{escape(str(attack))}[/]  "
        f"sent={summary['sent']}  failed={summary['failed']}  found={found_txt}"
    )
    for attempt in report.attempts:
        finding = getattr(attempt, "finding", None)
        if finding is not None:
            console.print(_finding_panel(finding, attempt))
    errors = report.errors
    if errors:
        console.print(f"[dim]errors: {len(errors)}[/]")
        for att in errors[:3]:
            console.print(f"[dim]  - {escape(str(att.error))}[/]")


def render_run_summary(results: object, *, console: Console = console) -> None:
    table = Table(title="run summary", title_justify="left", expand=False)
    table.add_column("target / attack")
    table.add_column("sent", justify="right")
    table.add_column("failed", justify="right")
    table.add_column("found", justify="right")

    tot_sent = tot_failed = tot_found = 0
    for label, report in results:
        s = report.summary()
        tot_sent += s["sent"]
        tot_failed += s["failed"]
        tot_found += s["found"]
        found_cell = Text(str(s["found"]), style="bold red") if s["found"] else Text("0")
        table.add_row(
            escape(str(label)),
            str(s["sent"]),
            str(s["failed"]),
            found_cell,
            style="bold" if s["found"] else None,
        )

    table.add_section()
    total_found = Text(str(tot_found), style="bold red") if tot_found else Text("0")
    table.add_row(
        Text("TOTAL", style="bold"),
        Text(str(tot_sent), style="bold"),
        Text(str(tot_failed), style="bold"),
        total_found,
    )
    console.print(table)
