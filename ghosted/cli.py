"""Ghosted CLI — Remove your personal data from the internet."""

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt

from ghosted.models import RemovalStatus, UserProfile

app = typer.Typer(
    name="ghosted",
    help="Remove your personal data from the internet.",
    no_args_is_help=True,
)
console = Console()

VAULT_DIR = Path.home() / ".ghosted"
BROKERS_DIR = Path(__file__).resolve().parent.parent / "brokers"


def _require_vault() -> None:
    """Exit with a helpful message if the vault doesn't exist yet."""
    from ghosted.vault.store import VaultStore

    vault = VaultStore(VAULT_DIR)
    if not vault.exists():
        console.print(
            Panel(
                "No vault found. Run [bold cyan]ghosted init[/bold cyan] first to set up your profile.",
                title="Setup Required",
                border_style="red",
            )
        )
        raise typer.Exit(1)


def _load_profile(passphrase: str) -> UserProfile:
    """Load and decrypt the user profile from the vault."""
    from ghosted.vault.store import VaultStore

    vault = VaultStore(VAULT_DIR)
    try:
        return vault.load(passphrase)
    except Exception:
        console.print("[bold red]Error:[/bold red] Wrong passphrase or corrupted vault.")
        raise typer.Exit(1)


def _get_passphrase() -> str:
    """Prompt for the vault passphrase."""
    return Prompt.ask("[bold]Vault passphrase[/bold]", password=True, console=console)


@app.command()
def init() -> None:
    """Set up your encrypted profile vault."""
    from ghosted.vault.store import VaultStore

    vault = VaultStore(VAULT_DIR)

    if vault.exists():
        overwrite = Confirm.ask(
            "A vault already exists. Overwrite it?", default=False, console=console
        )
        if not overwrite:
            raise typer.Exit()

    console.print(
        Panel(
            "Welcome to [bold cyan]Ghosted[/bold cyan]!\n\n"
            "We'll encrypt your personal information locally so it can be used\n"
            "to scan data brokers and submit opt-out requests on your behalf.",
            title="Setup",
            border_style="cyan",
        )
    )

    # Passphrase
    passphrase = Prompt.ask("[bold]Choose a passphrase[/bold]", password=True, console=console)
    confirm = Prompt.ask("[bold]Confirm passphrase[/bold]", password=True, console=console)
    if passphrase != confirm:
        console.print("[bold red]Passphrases don't match.[/bold red]")
        raise typer.Exit(1)
    if len(passphrase) < 8:
        console.print("[bold red]Passphrase must be at least 8 characters.[/bold red]")
        raise typer.Exit(1)

    # Required fields
    first_name = Prompt.ask("[bold]First name[/bold]", console=console)
    last_name = Prompt.ask("[bold]Last name[/bold]", console=console)
    email_addr = Prompt.ask("[bold]Email address[/bold]", console=console)
    city = Prompt.ask("[bold]City[/bold]", console=console)
    state = Prompt.ask("[bold]State[/bold]", console=console)

    # Optional fields
    phone = Prompt.ask("[bold]Phone number[/bold] [dim](optional)[/dim]", default="", console=console)
    dob = Prompt.ask("[bold]Date of birth[/bold] [dim](optional, YYYY-MM-DD)[/dim]", default="", console=console)
    prev_addr = Prompt.ask(
        "[bold]Previous addresses[/bold] [dim](optional, comma-separated)[/dim]",
        default="",
        console=console,
    )
    opt_out_email = Prompt.ask(
        "[bold]Opt-out email[/bold] [dim](optional, separate email for broker comms)[/dim]",
        default="",
        console=console,
    )

    previous_addresses = [a.strip() for a in prev_addr.split(",") if a.strip()] if prev_addr else []

    profile = UserProfile(
        first_name=first_name,
        last_name=last_name,
        email=email_addr,
        city=city,
        state=state,
        phone=phone or None,
        date_of_birth=dob or None,
        previous_addresses=previous_addresses,
        opt_out_email=opt_out_email or None,
    )

    vault.create(profile, passphrase)

    console.print()
    console.print(
        Panel(
            f"Profile for [bold]{first_name} {last_name}[/bold] encrypted and saved.\n"
            f"Vault location: [dim]{VAULT_DIR}[/dim]\n\n"
            "Run [bold cyan]ghosted scan[/bold cyan] to search data brokers for your info.",
            title="Setup Complete",
            border_style="green",
        )
    )


@app.command()
def scan(
    headed: bool = typer.Option(False, "--headed", help="Show browser window (requires display server)."),
) -> None:
    """Scan data brokers for your personal information."""
    _require_vault()
    passphrase = _get_passphrase()
    profile = _load_profile(passphrase)

    from ghosted.brokers.engine import AutomationEngine
    from ghosted.brokers.registry import BrokerRegistry
    from ghosted.core.history import HistoryDB
    from ghosted.core.scanner import scan_brokers
    from ghosted.utils.reporting import print_scan_report

    registry = BrokerRegistry(BROKERS_DIR)
    broker_list = registry.load_all()

    if not broker_list:
        console.print("[yellow]No broker configs found.[/yellow] Add YAML configs to the brokers/configs/ directory.")
        raise typer.Exit()

    console.print(f"\nScanning [bold]{len(broker_list)}[/bold] broker(s)...\n")

    async def _run_scan():
        engine = AutomationEngine(headless=not headed)
        await engine.start()
        try:
            report = await scan_brokers(profile, broker_list, engine)
        finally:
            await engine.stop()
        return report

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Scanning brokers...", total=None)
        report = asyncio.run(_run_scan())

    print_scan_report(report, console)

    # Save to history
    history = HistoryDB()
    history.init_db()
    history.save_scan(report)
    history.close()

    console.print("\n[dim]Scan saved to history. Run [bold]ghosted remove[/bold] to opt out.[/dim]")


@app.command()
def remove(
    all_brokers: bool = typer.Option(False, "--all", help="Remove from all brokers where data was found."),
    broker: Optional[str] = typer.Option(None, "--broker", help="Remove from a specific broker by name."),
    headed: bool = typer.Option(False, "--headed", help="Show browser window (requires display server)."),
) -> None:
    """Submit opt-out requests to data brokers."""
    _require_vault()
    passphrase = _get_passphrase()
    profile = _load_profile(passphrase)

    from ghosted.brokers.engine import AutomationEngine
    from ghosted.brokers.registry import BrokerRegistry
    from ghosted.core.history import HistoryDB
    from ghosted.core.remover import remove_from_brokers
    from ghosted.utils.reporting import print_removal_report

    history = HistoryDB()
    history.init_db()

    latest_scan = history.get_latest_scan()
    if not latest_scan:
        console.print("[yellow]No scan results found.[/yellow] Run [bold cyan]ghosted scan[/bold cyan] first.")
        history.close()
        raise typer.Exit()

    # Filter results to those with data found
    found_results = [r for r in latest_scan.results if r.found]
    if not found_results:
        console.print("[green]No brokers had your data in the latest scan.[/green]")
        history.close()
        raise typer.Exit()

    if broker:
        found_results = [r for r in found_results if r.broker_name == broker]
        if not found_results:
            console.print(f"[yellow]Broker '{broker}' not found in scan results or had no data.[/yellow]")
            history.close()
            raise typer.Exit()
    elif not all_brokers:
        console.print(
            f"Found data on [bold red]{len(found_results)}[/bold red] broker(s). "
            "Use [bold]--all[/bold] to remove from all, or [bold]--broker NAME[/bold] for a specific one."
        )
        history.close()
        raise typer.Exit()

    registry = BrokerRegistry(BROKERS_DIR)
    broker_list = registry.load_all()

    console.print(f"\nRemoving from [bold]{len(found_results)}[/bold] broker(s)...\n")

    async def _run_removals():
        engine = AutomationEngine(headless=not headed)
        await engine.start()
        try:
            report = await remove_from_brokers(profile, found_results, broker_list, engine)
        finally:
            await engine.stop()
        return report

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Submitting opt-out requests...", total=None)
        report = asyncio.run(_run_removals())

    print_removal_report(report, console)

    for req in report.requests:
        history.save_removal(req)

    history.close()


@app.command()
def verify() -> None:
    """Check for verification emails from brokers."""
    from ghosted.core.history import HistoryDB

    history = HistoryDB()
    history.init_db()

    removals = history.get_all_removals()
    awaiting = [r for r in removals if r.status == RemovalStatus.AWAITING_VERIFICATION]

    if not awaiting:
        console.print("[green]No pending verifications.[/green]")
        history.close()
        return

    console.print(
        Panel(
            f"[bold yellow]{len(awaiting)}[/bold yellow] removal(s) awaiting email verification.\n\n"
            "To automatically check your email, configure IMAP in your vault.\n"
            "Otherwise, check your inbox and click the verification links manually.",
            title="Pending Verifications",
            border_style="yellow",
        )
    )

    from rich.table import Table

    table = Table(show_lines=True)
    table.add_column("Broker", style="bold")
    table.add_column("Status")
    table.add_column("Submitted")

    for r in awaiting:
        submitted = r.submitted_at.strftime("%Y-%m-%d %H:%M") if r.submitted_at else "Unknown"
        table.add_row(r.broker_name, "Awaiting Verification", submitted)

    console.print(table)
    history.close()


@app.command()
def status() -> None:
    """Show your data removal dashboard."""
    from ghosted.core.history import HistoryDB
    from ghosted.utils.reporting import print_status_dashboard

    history = HistoryDB()
    history.init_db()

    latest_scan = history.get_latest_scan()
    removals = history.get_all_removals()

    confirmed = sum(1 for r in removals if r.status in (RemovalStatus.CONFIRMED, RemovalStatus.VERIFIED))
    pending = sum(
        1 for r in removals
        if r.status in (RemovalStatus.PENDING, RemovalStatus.SUBMITTED, RemovalStatus.AWAITING_VERIFICATION)
    )
    failed = sum(1 for r in removals if r.status == RemovalStatus.FAILED)

    stats = {
        "total_scanned": latest_scan.total_brokers if latest_scan else 0,
        "found": latest_scan.brokers_with_data if latest_scan else 0,
        "removed": confirmed,
        "pending": pending,
        "failed": failed,
        "last_scan": latest_scan.started_at.strftime("%Y-%m-%d %H:%M") if latest_scan else "Never",
        "next_scan": "Not scheduled",
    }

    print_status_dashboard(stats, console)
    history.close()


@app.command()
def brokers() -> None:
    """List all available broker configurations."""
    from ghosted.brokers.registry import BrokerRegistry
    from ghosted.utils.reporting import print_broker_list

    registry = BrokerRegistry(BROKERS_DIR)
    broker_list = registry.load_all()

    if not broker_list:
        console.print("[yellow]No broker configs found.[/yellow] Add YAML configs to the brokers/configs/ directory.")
        raise typer.Exit()

    print_broker_list(broker_list, console)
