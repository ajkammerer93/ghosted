"""Rich output formatting for scan reports, removal status, and dashboards."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ghosted.models import BrokerConfig, RemovalReport, RemovalStatus, ScanReport, ScanStatus


def print_scan_report(report: ScanReport, console: Console) -> None:
    """Display scan results in a Rich table with color coding."""
    table = Table(title="Scan Results", show_lines=True)
    table.add_column("Broker", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Details")

    status_display = {
        ScanStatus.FOUND: ("Found", "bold red"),
        ScanStatus.NOT_FOUND: ("Clear", "green"),
        ScanStatus.BLOCKED: ("Blocked", "yellow"),
        ScanStatus.ERROR: ("Error", "red"),
        ScanStatus.UNKNOWN: ("Unknown", "yellow"),
    }

    for result in report.results:
        label, style = status_display.get(result.status, ("Unknown", "yellow"))
        status_text = Text(label, style=style)

        details = ""
        if result.profile_url:
            details = result.profile_url
        if result.error:
            details = result.error if not details else f"{details}  ({result.error})"

        info = ", ".join(result.info_found) if result.info_found else ""
        if info:
            details = f"{details}  {info}" if details else info

        table.add_row(result.broker_name, status_text, details.strip())

    console.print()
    console.print(table)

    summary_parts = [
        f"[bold]{report.total_brokers}[/bold] scanned",
    ]
    if report.brokers_with_data:
        summary_parts.append(f"[bold red]{report.brokers_with_data}[/bold red] found")
    else:
        summary_parts.append(f"[green]0[/green] found")

    # Count clear results
    clear_count = sum(1 for r in report.results if r.status == ScanStatus.NOT_FOUND)
    if clear_count:
        summary_parts.append(f"[green]{clear_count}[/green] clear")

    if report.brokers_blocked:
        summary_parts.append(f"[yellow]{report.brokers_blocked}[/yellow] blocked")
    if report.brokers_unknown:
        summary_parts.append(f"[yellow]{report.brokers_unknown}[/yellow] unknown")
    if report.errors:
        summary_parts.append(f"[red]{report.errors}[/red] errors")

    console.print(Panel(" | ".join(summary_parts), title="Summary", border_style="blue"))


def print_removal_report(report: RemovalReport, console: Console) -> None:
    """Display removal results in a Rich table with status coloring."""
    table = Table(title="Removal Results", show_lines=True)
    table.add_column("Broker", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Method")
    table.add_column("Notes")

    status_styles = {
        RemovalStatus.CONFIRMED: "green",
        RemovalStatus.VERIFIED: "green",
        RemovalStatus.SUBMITTED: "green",
        RemovalStatus.PENDING: "yellow",
        RemovalStatus.AWAITING_VERIFICATION: "yellow",
        RemovalStatus.FAILED: "red",
        RemovalStatus.MANUAL_REQUIRED: "blue",
    }

    manual_actions = []

    for req in report.requests:
        style = status_styles.get(req.status, "white")
        status_text = Text(req.status.value.replace("_", " ").title(), style=style)
        notes = req.notes or ""
        if req.error:
            notes = req.error if not notes else f"{notes} ({req.error})"

        if req.status == RemovalStatus.MANUAL_REQUIRED and notes:
            table.add_row(req.broker_name, status_text, req.method.value, "See instructions below")
            manual_actions.append((req.broker_name, notes, req.profile_url))
        else:
            table.add_row(req.broker_name, status_text, req.method.value, notes)

    console.print()
    console.print(table)

    for broker_name, notes, profile_url in manual_actions:
        console.print()
        console.print(Panel(
            f"{notes}\n\n[bold]Profile URL:[/bold]\n{profile_url}" if profile_url else notes,
            title=f"[bold blue]{broker_name}[/bold blue] — Manual Action Required",
            border_style="blue",
            expand=True,
        ))

    summary_parts = [
        f"[bold]{report.total_requests}[/bold] total",
        f"[green]{report.automated}[/green] automated",
    ]
    if report.needs_user_input:
        summary_parts.append(f"[yellow]{report.needs_user_input}[/yellow] need input")
    if report.manual_only:
        summary_parts.append(f"[blue]{report.manual_only}[/blue] manual")

    console.print(Panel(" | ".join(summary_parts), title="Removal Summary", border_style="blue"))


def print_status_dashboard(stats: dict, console: Console) -> None:
    """Display a summary dashboard panel with key metrics."""
    lines = []

    total_scanned = stats.get("total_scanned", 0)
    found = stats.get("found", 0)
    removed = stats.get("removed", 0)
    pending = stats.get("pending", 0)
    failed = stats.get("failed", 0)
    last_scan = stats.get("last_scan", "Never")
    next_scan = stats.get("next_scan", "Not scheduled")

    lines.append(f"[bold]Brokers Scanned:[/bold]  {total_scanned}")
    lines.append(f"[bold red]Data Found On:[/bold red]     {found}")
    lines.append(f"[bold green]Removed:[/bold green]           {removed}")
    lines.append(f"[bold yellow]Pending:[/bold yellow]           {pending}")
    if failed:
        lines.append(f"[bold red]Failed:[/bold red]            {failed}")
    lines.append("")
    lines.append(f"[bold]Last Scan:[/bold]  {last_scan}")
    lines.append(f"[bold]Next Scan:[/bold]  {next_scan}")

    console.print()
    console.print(Panel("\n".join(lines), title="Ghosted Status", border_style="cyan", padding=(1, 2)))


def print_broker_list(brokers: list[BrokerConfig], console: Console) -> None:
    """Display available brokers in a Rich table."""
    table = Table(title="Available Brokers", show_lines=True)
    table.add_column("Name", style="bold")
    table.add_column("Method")
    table.add_column("CAPTCHA", justify="center")
    table.add_column("Rescan (days)", justify="center")
    table.add_column("Email Verify", justify="center")

    for broker in sorted(brokers, key=lambda b: b.name):
        captcha = broker.captcha or Text("-", style="dim")
        method = broker.method.value.replace("_", " ").title()
        rescan = str(broker.recommended_rescan_days)
        email_verify = Text("Yes", style="yellow") if broker.requires_email_verification else Text("-", style="dim")
        table.add_row(broker.name, method, captcha, rescan, email_verify)

    console.print()
    console.print(table)
    console.print(f"\n[dim]{len(brokers)} broker(s) loaded[/dim]")
