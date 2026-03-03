"""CAPTCHA detection and user-assisted solving."""

from typing import Optional

from rich.console import Console
from rich.panel import Panel


async def detect_captcha(page) -> Optional[str]:
    """Check the current page for known CAPTCHA types.

    Returns the CAPTCHA type string if detected, None otherwise.
    """
    # reCAPTCHA
    recaptcha = await page.query_selector("iframe[src*='recaptcha'], .g-recaptcha")
    if recaptcha:
        return "reCAPTCHA"

    # hCaptcha
    hcaptcha = await page.query_selector("iframe[src*='hcaptcha'], .h-captcha")
    if hcaptcha:
        return "hCaptcha"

    # Cloudflare Turnstile / challenge
    cloudflare = await page.query_selector(
        "iframe[src*='challenges.cloudflare'], .cf-turnstile, #cf-challenge-running"
    )
    if cloudflare:
        return "Cloudflare"

    return None


async def prompt_user_solve(page, broker_name: str, console: Console) -> None:
    """Ask the user to manually solve a CAPTCHA in the browser window.

    Prints a Rich-formatted prompt, waits for the user to press Enter,
    then verifies the CAPTCHA element is no longer blocking.
    """
    captcha_type = await detect_captcha(page) or "CAPTCHA"

    console.print()
    console.print(
        Panel(
            f"[bold yellow]{captcha_type}[/bold yellow] detected on [cyan]{broker_name}[/cyan].\n\n"
            "Please solve the CAPTCHA in the browser window,\n"
            "then press [bold]Enter[/bold] here to continue.",
            title="Manual Action Required",
            border_style="yellow",
        )
    )

    # Block until user presses Enter (run input() in executor to not block event loop)
    import asyncio
    await asyncio.get_event_loop().run_in_executor(None, input)

    # Quick check: did the CAPTCHA go away?
    remaining = await detect_captcha(page)
    if remaining:
        console.print(
            f"[yellow]Warning:[/yellow] {remaining} may still be present. "
            "Continuing anyway — the form submission may fail."
        )
