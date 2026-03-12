"""Ghosted CLI — Remove your personal data from the internet."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Confirm, Prompt

from ghosted.models import RemovalStatus, ScanStatus, UserProfile

app = typer.Typer(
    name="ghosted",
    help="Remove your personal data from the internet.",
    no_args_is_help=True,
)
console = Console()

BASE_DIR = Path.home() / ".ghosted"
BROKERS_DIR = Path(__file__).resolve().parent.parent / "brokers"


def _get_vault(profile_name: str = "default"):
    from ghosted.vault.store import VaultStore
    return VaultStore(BASE_DIR, profile_name=profile_name)


def _get_history(profile_name: str = "default"):
    from ghosted.core.history import HistoryDB
    db_path = BASE_DIR / "profiles" / profile_name / "scan_history.db"
    return HistoryDB(db_path)


def _require_vault(profile_name: str = "default") -> None:
    """Exit with a helpful message if the vault doesn't exist yet."""
    vault = _get_vault(profile_name)
    if not vault.exists():
        console.print(
            Panel(
                f"No vault found for profile [bold]{profile_name}[/bold].\n"
                f"Run [bold cyan]ghosted init --profile {profile_name}[/bold cyan] first.",
                title="Setup Required",
                border_style="red",
            )
        )
        raise typer.Exit(1)


def _load_profile(passphrase: str, profile_name: str = "default") -> UserProfile:
    """Load and decrypt the user profile from the vault."""
    vault = _get_vault(profile_name)
    try:
        return vault.load(passphrase)
    except Exception:
        console.print("[bold red]Error:[/bold red] Wrong passphrase or corrupted vault.")
        raise typer.Exit(1)


def _get_passphrase(profile_name: str = "default") -> str:
    """Prompt for the vault passphrase."""
    label = f"[bold]Vault passphrase[/bold] [dim]({profile_name})[/dim]"
    return Prompt.ask(label, password=True, console=console)


@app.command()
def init(
    profile: str = typer.Option("default", "--profile", "-p", help="Profile name (e.g., 'spouse', 'parent')."),
) -> None:
    """Set up your encrypted profile vault."""
    vault = _get_vault(profile)

    if vault.exists():
        overwrite = Confirm.ask(
            f"Profile '{profile}' already exists. Overwrite it?", default=False, console=console
        )
        if not overwrite:
            raise typer.Exit()

    console.print(
        Panel(
            f"Welcome to [bold cyan]Ghosted[/bold cyan]!\n\n"
            f"Setting up profile: [bold]{profile}[/bold]\n"
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

    # Optional IMAP configuration
    imap_host = None
    imap_port = 993
    imap_user = None
    imap_password = None
    if Confirm.ask("[bold]Configure email verification (IMAP)?[/bold]", default=False, console=console):
        imap_host = Prompt.ask("[bold]IMAP host[/bold] [dim](e.g. imap.gmail.com)[/dim]", console=console)
        imap_port_str = Prompt.ask("[bold]IMAP port[/bold]", default="993", console=console)
        try:
            imap_port = int(imap_port_str)
        except ValueError:
            console.print("[bold red]IMAP port must be a number.[/bold red]")
            raise typer.Exit(1)
        imap_user = Prompt.ask("[bold]IMAP username[/bold] [dim](email address)[/dim]", console=console)
        imap_password = Prompt.ask("[bold]IMAP password[/bold] [dim](app password)[/dim]", password=True, console=console)

    user_profile = UserProfile(
        first_name=first_name,
        last_name=last_name,
        email=email_addr,
        city=city,
        state=state,
        phone=phone or None,
        date_of_birth=dob or None,
        previous_addresses=previous_addresses,
        opt_out_email=opt_out_email or None,
        imap_host=imap_host or None,
        imap_port=imap_port,
        imap_user=imap_user or None,
        imap_password=imap_password or None,
    )

    vault.create(user_profile, passphrase)

    console.print()
    profile_flag = f" --profile {profile}" if profile != "default" else ""
    console.print(
        Panel(
            f"Profile [bold]{profile}[/bold] for [bold]{first_name} {last_name}[/bold] encrypted and saved.\n"
            f"Vault location: [dim]{vault.vault_dir}[/dim]\n\n"
            f"Run [bold cyan]ghosted scan{profile_flag}[/bold cyan] to search data brokers for your info.",
            title="Setup Complete",
            border_style="green",
        )
    )


@app.command()
def scan(
    profile: str = typer.Option("default", "--profile", "-p", help="Profile to scan for."),
    all_profiles: bool = typer.Option(False, "--all-profiles", help="Scan for all profiles."),
    headed: bool = typer.Option(False, "--headed", help="Show browser window (requires display server)."),
) -> None:
    """Scan data brokers for your personal information."""
    from ghosted.brokers.engine import AutomationEngine
    from ghosted.brokers.registry import BrokerRegistry
    from ghosted.core.scanner import scan_brokers
    from ghosted.utils.reporting import print_scan_report
    from ghosted.vault.store import VaultStore

    registry = BrokerRegistry(BROKERS_DIR)
    broker_list = registry.load_all()

    if not broker_list:
        console.print("[yellow]No broker configs found.[/yellow]")
        raise typer.Exit()

    # Determine which profiles to scan
    if all_profiles:
        profile_names = VaultStore.list_profiles(BASE_DIR)
        if not profile_names:
            console.print("[yellow]No profiles found.[/yellow] Run [bold cyan]ghosted init[/bold cyan] first.")
            raise typer.Exit()
    else:
        _require_vault(profile)
        profile_names = [profile]

    for profile_name in profile_names:
        _require_vault(profile_name)
        passphrase = _get_passphrase(profile_name)
        user_profile = _load_profile(passphrase, profile_name)

        if len(profile_names) > 1:
            console.print(f"\n[bold]━━━ Profile: {profile_name} ({user_profile.first_name} {user_profile.last_name}) ━━━[/bold]")

        console.print(f"\nScanning [bold]{len(broker_list)}[/bold] broker(s)...\n")

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        )

        async def _run_scan(up=user_profile):
            task_id = progress.add_task("Starting...", total=len(broker_list))

            def on_start(name: str, current: int, total: int):
                progress.update(task_id, description=f"[cyan]{name}[/cyan]")

            def on_done(result, current: int, total: int):
                status_map = {
                    ScanStatus.FOUND: "[bold red]found[/bold red]",
                    ScanStatus.NOT_FOUND: "[green]clear[/green]",
                    ScanStatus.BLOCKED: "[yellow]blocked[/yellow]",
                    ScanStatus.ERROR: "[red]error[/red]",
                    ScanStatus.UNKNOWN: "[yellow]unknown[/yellow]",
                }
                s = status_map.get(result.status, f"[dim]{result.status.value}[/dim]")
                progress.console.print(
                    f"  [{current}/{total}] {result.broker_name}: {s}"
                )
                progress.update(task_id, completed=current)

            engine = AutomationEngine(headless=not headed)
            await engine.start()
            try:
                report = await scan_brokers(
                    up, broker_list, engine,
                    on_broker_start=on_start,
                    on_broker_done=on_done,
                )
            finally:
                await engine.stop()
            return report

        with progress:
            report = asyncio.run(_run_scan())

        console.print()
        print_scan_report(report, console)

        # Save to per-profile history
        history = _get_history(profile_name)
        history.init_db()
        history.save_scan(report)
        history.close()

        profile_flag = f" --profile {profile_name}" if profile_name != "default" else ""
        console.print(f"\n[dim]Scan saved to history. Run [bold]ghosted remove{profile_flag}[/bold] to opt out.[/dim]")


@app.command()
def remove(
    profile: str = typer.Option("default", "--profile", "-p", help="Profile to remove data for."),
    broker: Optional[str] = typer.Option(None, "--broker", help="Remove from a specific broker by name."),
    headed: bool = typer.Option(False, "--headed", help="Show browser window (requires display server)."),
) -> None:
    """Submit opt-out requests to data brokers."""
    _require_vault(profile)
    passphrase = _get_passphrase(profile)
    user_profile = _load_profile(passphrase, profile)

    from ghosted.brokers.engine import AutomationEngine
    from ghosted.brokers.registry import BrokerRegistry
    from ghosted.core.remover import remove_from_brokers
    from ghosted.utils.reporting import print_removal_report

    history = _get_history(profile)
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

    registry = BrokerRegistry(BROKERS_DIR)
    broker_list = registry.load_all()

    console.print(f"\nRemoving from [bold]{len(found_results)}[/bold] broker(s)...\n")

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )

    async def _run_removals():
        task_id = progress.add_task("Starting...", total=len(found_results))

        def on_start(name: str, current: int, total: int):
            progress.update(task_id, description=f"[cyan]{name}[/cyan]")

        def on_done(request, current: int, total: int):
            status_map = {
                RemovalStatus.SUBMITTED: "[green]submitted[/green]",
                RemovalStatus.AWAITING_VERIFICATION: "[yellow]awaiting verification[/yellow]",
                RemovalStatus.MANUAL_REQUIRED: "[yellow]manual required[/yellow]",
                RemovalStatus.PENDING: "[yellow]pending[/yellow]",
                RemovalStatus.FAILED: "[red]failed[/red]",
            }
            s = status_map.get(request.status, f"[dim]{request.status.value}[/dim]")
            progress.console.print(f"  [{current}/{total}] {request.broker_name}: {s}")
            progress.update(task_id, completed=current)

        engine = AutomationEngine(headless=not headed)
        await engine.start()
        try:
            report = await remove_from_brokers(
                user_profile, found_results, broker_list, engine,
                on_broker_start=on_start,
                on_broker_done=on_done,
            )
        finally:
            await engine.stop()
        return report

    with progress:
        report = asyncio.run(_run_removals())

    print_removal_report(report, console)

    for req in report.requests:
        history.save_removal(req)

    history.close()


async def _run_verify(
    user_profile: UserProfile,
    broker_patterns: dict[str, dict],
    headed: bool,
) -> list[dict]:
    """Check verification emails and click all confirmation links in a single browser session.

    Returns list of dicts with broker_name, success, url, subject.
    """
    from ghosted.core.emailer import EmailConfig, check_verification_emails

    email_config = EmailConfig(
        imap_host=user_profile.imap_host,
        imap_port=user_profile.imap_port,
        email=user_profile.imap_user,
        password=user_profile.imap_password,
    )

    found_emails = await check_verification_emails(email_config, broker_patterns)
    if not found_emails:
        return []

    # Collect emails that have clickable URLs
    to_click = [(em, em["verification_url"]) for em in found_emails if em.get("verification_url")]

    results = []
    # Add entries for emails without links
    for em in found_emails:
        if not em.get("verification_url"):
            results.append({
                "broker_name": em["broker_name"],
                "subject": em["subject"],
                "url": None,
                "success": False,
            })

    if to_click:
        from patchright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=not headed)
            page = await browser.new_page()
            try:
                for em, url in to_click:
                    # Extract allowed domain from broker's link_pattern
                    link_pat = broker_patterns.get(em["broker_name"], {}).get("link_pattern", "")
                    allowed_domain = ""
                    if link_pat:
                        parsed = urlparse(link_pat) if "://" in link_pat else None
                        if parsed and parsed.hostname:
                            allowed_domain = parsed.hostname
                        else:
                            # Try to extract domain from regex pattern
                            domain_match = __import__("re").search(r'(?:https?://)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', link_pat)
                            if domain_match:
                                allowed_domain = domain_match.group(1)

                    # Validate URL
                    parsed_url = urlparse(url)
                    if parsed_url.scheme != "https":
                        results.append({"broker_name": em["broker_name"], "subject": em["subject"], "url": url, "success": False})
                        continue
                    hostname = parsed_url.hostname or ""
                    if hostname == "localhost":
                        results.append({"broker_name": em["broker_name"], "subject": em["subject"], "url": url, "success": False})
                        continue
                    if allowed_domain and allowed_domain not in hostname:
                        results.append({"broker_name": em["broker_name"], "subject": em["subject"], "url": url, "success": False})
                        continue

                    try:
                        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(2000)
                        success = response is not None and response.status < 400
                    except Exception:
                        success = False

                    results.append({
                        "broker_name": em["broker_name"],
                        "subject": em["subject"],
                        "url": url,
                        "success": success,
                    })
            finally:
                await browser.close()

    return results


@app.command()
def verify(
    profile: str = typer.Option("default", "--profile", "-p", help="Profile to check verifications for."),
    headed: bool = typer.Option(False, "--headed", help="Show browser window when clicking verification links."),
) -> None:
    """Check for verification emails and click confirmation links."""
    _require_vault(profile)
    passphrase = _get_passphrase(profile)
    user_profile = _load_profile(passphrase, profile)

    history = _get_history(profile)
    history.init_db()

    removals = history.get_all_removals()
    awaiting = [r for r in removals if r.status == RemovalStatus.AWAITING_VERIFICATION]

    if not awaiting:
        console.print("[green]No pending verifications.[/green]")
        history.close()
        return

    from rich.table import Table

    # If IMAP not configured, show stub and exit
    if not user_profile.imap_host or not user_profile.imap_user or not user_profile.imap_password:
        console.print(
            Panel(
                f"[bold yellow]{len(awaiting)}[/bold yellow] removal(s) awaiting email verification.\n\n"
                "To automatically check your email, configure IMAP:\n"
                f"  [bold cyan]ghosted configure-email --profile {profile}[/bold cyan]\n\n"
                "Otherwise, check your inbox and click the verification links manually.",
                title="Pending Verifications",
                border_style="yellow",
            )
        )

        table = Table(show_lines=True)
        table.add_column("Broker", style="bold")
        table.add_column("Status")
        table.add_column("Submitted")

        for r in awaiting:
            submitted = r.submitted_at.strftime("%Y-%m-%d %H:%M") if r.submitted_at else "Unknown"
            table.add_row(r.broker_name, "Awaiting Verification", submitted)

        console.print(table)
        history.close()
        return

    # Build broker_patterns from YAML configs
    from ghosted.brokers.registry import BrokerRegistry, build_broker_patterns

    registry = BrokerRegistry(BROKERS_DIR)
    broker_list = registry.load_all()

    awaiting_names = {r.broker_name for r in awaiting}
    broker_patterns = build_broker_patterns(broker_list, awaiting_names)

    if not broker_patterns:
        console.print("[yellow]No broker email patterns found for pending verifications.[/yellow]")
        history.close()
        return

    console.print(f"Checking inbox for verification emails from [bold]{len(broker_patterns)}[/bold] broker(s)...\n")

    try:
        results = asyncio.run(_run_verify(user_profile, broker_patterns, headed))
    except Exception as e:
        console.print(Panel(f"Failed to check email: {e}", title="IMAP Error", border_style="red"))
        history.close()
        raise typer.Exit(1)

    if not results:
        console.print("[yellow]No verification emails found yet.[/yellow] Check again later.")
        history.close()
        return

    # Display found emails
    table = Table(title="Verification Emails Found", show_lines=True)
    table.add_column("Broker", style="bold")
    table.add_column("Subject")
    table.add_column("Link")

    for r in results:
        link_display = "[green]found[/green]" if r["url"] else "[red]not found[/red]"
        table.add_row(r["broker_name"], r["subject"], link_display)

    console.print(table)
    console.print()

    # Process results
    verified = 0
    failed = 0

    for r in results:
        if not r["url"]:
            console.print(f"  {r['broker_name']}: [red]no link found in email[/red]")
            failed += 1
        elif r["success"]:
            console.print(f"  {r['broker_name']}: [green]verified[/green]")
            removal = history.get_removal_status(r["broker_name"])
            if removal:
                removal.status = RemovalStatus.VERIFIED
                removal.verified_at = datetime.now()
                history.save_removal(removal)
            verified += 1
        else:
            console.print(f"  {r['broker_name']}: [red]failed[/red]")
            failed += 1

    console.print()
    console.print(
        Panel(
            f"[green]{verified}[/green] verified, [red]{failed}[/red] failed, "
            f"[yellow]{len(awaiting) - len(results)}[/yellow] still pending",
            title="Verification Summary",
            border_style="green" if verified > 0 else "yellow",
        )
    )
    history.close()


@app.command()
def status(
    profile: str = typer.Option("default", "--profile", "-p", help="Profile to show status for."),
) -> None:
    """Show your data removal dashboard."""
    from ghosted.utils.reporting import print_status_dashboard

    history = _get_history(profile)
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
        "profile": profile,
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


@app.command("destroy-profile")
def destroy_profile(
    profile: str = typer.Option("default", "--profile", "-p", help="Profile to destroy."),
    all_profiles: bool = typer.Option(False, "--all-profiles", help="Destroy all profiles."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Permanently delete a profile and its scan history."""
    from ghosted.vault.store import VaultStore

    if all_profiles:
        profile_names = VaultStore.list_profiles(BASE_DIR)
        if not profile_names:
            console.print("[yellow]No profiles found.[/yellow]")
            raise typer.Exit()
    else:
        _require_vault(profile)
        profile_names = [profile]

    if not yes:
        names_str = ", ".join(f"[bold]{n}[/bold]" for n in profile_names)
        console.print(
            Panel(
                f"This will permanently delete the following profile(s): {names_str}\n\n"
                "This includes encrypted vault data and all scan/removal history.\n"
                "[bold red]This action cannot be undone.[/bold red]",
                title="Confirm Deletion",
                border_style="red",
            )
        )
        if not Confirm.ask("Are you sure?", default=False, console=console):
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit()

    for name in profile_names:
        vault = _get_vault(name)
        if vault.exists():
            vault.destroy(remove_history=True)
            console.print(f"  [red]Destroyed[/red] profile [bold]{name}[/bold]")
        else:
            console.print(f"  [yellow]Skipped[/yellow] profile [bold]{name}[/bold] (not found)")

    count = len(profile_names)
    console.print(f"\n[green]Done.[/green] {count} profile(s) deleted.")


@app.command("configure-email")
def configure_email(
    profile: str = typer.Option("default", "--profile", "-p", help="Profile to configure."),
) -> None:
    """Add or update IMAP email configuration on an existing profile."""
    _require_vault(profile)
    passphrase = _get_passphrase(profile)
    user_profile = _load_profile(passphrase, profile)

    console.print(
        Panel(
            "Configure IMAP to let [bold cyan]ghosted verify[/bold cyan] automatically\n"
            "check your inbox for broker verification emails.",
            title="Email Configuration",
            border_style="cyan",
        )
    )

    imap_host = Prompt.ask(
        "[bold]IMAP host[/bold] [dim](e.g. imap.gmail.com)[/dim]",
        default=user_profile.imap_host or "",
        console=console,
    )
    imap_port_str = Prompt.ask(
        "[bold]IMAP port[/bold]",
        default=str(user_profile.imap_port),
        console=console,
    )
    imap_user = Prompt.ask(
        "[bold]IMAP username[/bold] [dim](email address)[/dim]",
        default=user_profile.imap_user or "",
        console=console,
    )
    imap_password = Prompt.ask(
        "[bold]IMAP password[/bold] [dim](app password)[/dim]",
        password=True,
        console=console,
    )

    try:
        imap_port = int(imap_port_str)
    except ValueError:
        console.print("[bold red]IMAP port must be a number.[/bold red]")
        raise typer.Exit(1)

    user_profile.imap_host = imap_host or None
    user_profile.imap_port = imap_port
    user_profile.imap_user = imap_user or None
    user_profile.imap_password = imap_password or None

    vault = _get_vault(profile)
    vault.create(user_profile, passphrase)

    console.print(
        Panel(
            "IMAP configuration saved to vault.\n"
            "Run [bold cyan]ghosted verify[/bold cyan] to check for verification emails.",
            title="Done",
            border_style="green",
        )
    )


@app.command()
def profiles() -> None:
    """List all configured profiles."""
    from ghosted.vault.store import VaultStore
    from rich.table import Table

    profile_names = VaultStore.list_profiles(BASE_DIR)

    if not profile_names:
        console.print("[yellow]No profiles found.[/yellow] Run [bold cyan]ghosted init[/bold cyan] to create one.")
        raise typer.Exit()

    table = Table(title="Profiles", show_lines=True)
    table.add_column("Name", style="bold")
    table.add_column("Vault")
    table.add_column("History")

    for name in profile_names:
        vault = _get_vault(name)
        history_path = BASE_DIR / "profiles" / name / "scan_history.db"
        vault_status = "[green]encrypted[/green]" if vault.exists() else "[red]missing[/red]"
        history_status = "[green]has data[/green]" if history_path.exists() else "[dim]empty[/dim]"
        table.add_row(name, vault_status, history_status)

    console.print(table)
    console.print(f"\n[dim]Use [bold]--profile NAME[/bold] with any command to target a specific profile.[/dim]")
