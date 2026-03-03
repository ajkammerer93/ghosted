"""Playwright-based automation engine for broker search and opt-out."""

import asyncio
import random
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright_stealth import Stealth

from ghosted.models import (
    BrokerConfig,
    BrokerStep,
    RemovalRequest,
    RemovalStatus,
    ScanResult,
    ScanStatus,
    UserProfile,
)

STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
]

COMMON_VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
]

USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
]


class AutomationEngine:
    """Drives browser automation for searching and opting out of data brokers."""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._stealth = Stealth()
        self._playwright_ctx = None
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def start(self) -> None:
        """Launch the Playwright browser with stealth patches."""
        self._playwright_ctx = self._stealth.use_async(async_playwright())
        self._playwright = await self._playwright_ctx.__aenter__()
        viewport = random.choice(COMMON_VIEWPORTS)
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=STEALTH_ARGS,
        )
        self._context = await self._browser.new_context(
            ignore_https_errors=True,
            viewport=viewport,
            screen=viewport,
            user_agent=random.choice(USER_AGENTS),
            locale="en-US",
            timezone_id="America/New_York",
            color_scheme="light",
        )

    async def stop(self) -> None:
        """Close the browser and clean up Playwright."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright_ctx:
            await self._playwright_ctx.__aexit__(None, None, None)
        self._context = None
        self._browser = None
        self._playwright = None
        self._playwright_ctx = None

    async def search_broker(self, config: BrokerConfig, profile: UserProfile) -> ScanResult:
        """Search a broker for the user's data.

        Navigates to the broker's search URL, fills in template variables,
        and classifies the outcome as FOUND, NOT_FOUND, BLOCKED, ERROR, or UNKNOWN.
        """
        if not config.search:
            return ScanResult(
                broker_name=config.name,
                status=ScanStatus.ERROR,
                found=False,
                error="No search configuration defined",
            )

        page: Page = await self._context.new_page()
        try:
            search_url = self._substitute_vars(config.search.url, profile)

            try:
                response = await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as goto_err:
                # Navigation timeout — page never finished loading (e.g. CAPTCHA blocking)
                # Return BLOCKED with the search URL as profile_url since it may be valid
                return ScanResult(
                    broker_name=config.name,
                    status=ScanStatus.BLOCKED,
                    found=False,
                    error=f"Navigation timeout: {search_url}",
                    profile_url=search_url,
                )

            http_status = response.status if response else None
            page_title = await page.title()

            # 404 and 5xx are never Cloudflare challenges — fail immediately
            if http_status and http_status == 404:
                return ScanResult(
                    broker_name=config.name,
                    status=ScanStatus.ERROR,
                    found=False,
                    error=f"HTTP {http_status} Not Found",
                    page_title=page_title,
                    http_status=http_status,
                )
            if http_status and http_status >= 500:
                return ScanResult(
                    broker_name=config.name,
                    status=ScanStatus.ERROR,
                    found=False,
                    error=f"HTTP {http_status} Server Error",
                    page_title=page_title,
                    http_status=http_status,
                )

            # Check for Cloudflare challenge — 403s are often CF challenges that
            # auto-solve in headed mode, so detect CF before returning BLOCKED
            if await self._detect_cloudflare(page):
                resolved = await self._wait_for_cloudflare_resolution(page)
                if not resolved:
                    return ScanResult(
                        broker_name=config.name,
                        status=ScanStatus.BLOCKED,
                        found=False,
                        error="Cloudflare protection detected",
                        page_title=page_title,
                        http_status=http_status,
                    )
                # Challenge resolved — update page state and continue
                page_title = await page.title()
                http_status = 200

            # Non-CF 403 (IP ban, auth required, etc.)
            if http_status and http_status == 403:
                return ScanResult(
                    broker_name=config.name,
                    status=ScanStatus.BLOCKED,
                    found=False,
                    error=f"HTTP {http_status} Forbidden",
                    page_title=page_title,
                    http_status=http_status,
                )

            # Detect CAPTCHA walls on search page
            if await self._detect_captcha_wall(page):
                return ScanResult(
                    broker_name=config.name,
                    status=ScanStatus.BLOCKED,
                    found=False,
                    error="CAPTCHA wall detected",
                    page_title=page_title,
                    http_status=http_status,
                )

            # Dismiss any verification/cookie popups before checking results
            await self._dismiss_dialogs(page)

            # Wait for JS-rendered results: try to wait for the result selector
            # or no-results indicator to appear, with a reasonable timeout
            selectors_to_wait = [config.search.result_selector]
            if config.search.no_results_indicator and config.search.no_results_indicator.startswith((".", "#", "[")):
                selectors_to_wait.append(config.search.no_results_indicator)

            try:
                await page.wait_for_selector(
                    ", ".join(selectors_to_wait),
                    timeout=10000,
                )
            except Exception:
                # Selectors didn't appear — page may be blocked or truly empty.
                # Fall through to the normal check logic below.
                await page.wait_for_timeout(2000)

            # Check for no-results indicator first
            if config.search.no_results_indicator:
                indicator = config.search.no_results_indicator
                # If it looks like a CSS selector, use query_selector;
                # otherwise treat it as page text content to search for
                if indicator.startswith((".", "#", "[", "//")) or "{" in indicator:
                    no_results = await page.query_selector(indicator)
                else:
                    no_results = await page.get_by_text(indicator).first.is_visible() if await page.get_by_text(indicator).count() > 0 else False
                if no_results:
                    return ScanResult(
                        broker_name=config.name,
                        status=ScanStatus.NOT_FOUND,
                        found=False,
                        page_title=page_title,
                        http_status=http_status,
                    )

            # Check for result matches
            results = await page.query_selector_all(config.search.result_selector)
            if results:
                profile_url = await self._extract_profile_url(results[0], page)

                return ScanResult(
                    broker_name=config.name,
                    status=ScanStatus.FOUND,
                    found=True,
                    profile_url=profile_url,
                    page_title=page_title,
                    http_status=http_status,
                )

            # Dump page snapshot for debugging selector mismatches
            await self._dump_debug_snapshot(config.name, page)

            return ScanResult(
                broker_name=config.name,
                status=ScanStatus.UNKNOWN,
                found=False,
                error="Neither results nor no-results indicator matched",
                page_title=page_title,
                http_status=http_status,
            )
        except Exception as e:
            return ScanResult(
                broker_name=config.name,
                status=ScanStatus.ERROR,
                found=False,
                error=str(e),
            )
        finally:
            await page.close()

    async def _detect_cloudflare(self, page: Page) -> bool:
        """Detect Cloudflare challenge/interstitial pages."""
        title = (await page.title()).lower()
        if any(phrase in title for phrase in ("just a moment", "attention required", "security challenge", "managed challenge")):
            return True

        cf_indicators = [
            "#challenge-form",
            ".cf-browser-verification",
            "#cf-challenge-running",
            "iframe[src*='challenges.cloudflare.com']",
        ]
        for selector in cf_indicators:
            if await page.query_selector(selector):
                return True

        return False

    async def _detect_captcha_wall(self, page: Page) -> bool:
        """Detect CAPTCHA challenges blocking the search page."""
        captcha_selectors = [
            "iframe[src*='recaptcha']",
            "iframe[src*='hcaptcha']",
            "iframe[src*='challenges.cloudflare.com']",
            ".g-recaptcha",
            ".h-captcha",
            "#cf-turnstile",
        ]
        for selector in captcha_selectors:
            if await page.query_selector(selector):
                return True
        return False

    async def _wait_for_cloudflare_resolution(self, page: Page, timeout: int = 10000) -> bool:
        """Wait briefly for a Cloudflare challenge to auto-resolve.

        Cloudflare Turnstile detects CDP-controlled browsers at the protocol
        level, so human interaction can't solve it through Playwright. We just
        wait briefly in case the challenge auto-resolves (rare), then give up.
        """
        elapsed = 0
        interval = 1000
        while elapsed < timeout:
            try:
                await page.wait_for_timeout(interval)
            except Exception:
                return False
            elapsed += interval
            try:
                if not await self._detect_cloudflare(page):
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    return True
            except Exception:
                # Page was closed during the wait
                return False
        return False

    async def execute_removal(
        self,
        config: BrokerConfig,
        profile: UserProfile,
        profile_url: str,
    ) -> RemovalRequest:
        """Execute the opt-out steps defined in a broker config.

        Handles each action type: navigate, fill, click, wait,
        solve_captcha, await_email, click_email_link.
        """
        page: Page = await self._context.new_page()
        try:
            for step in config.opt_out_steps:
                profile_url = await self._execute_step(step, page, profile, profile_url)
                # Random human-like delay between steps
                await asyncio.sleep(random.uniform(1.0, 3.0))

            status = RemovalStatus.SUBMITTED
            if config.requires_email_verification:
                status = RemovalStatus.AWAITING_VERIFICATION

            return RemovalRequest(
                broker_name=config.name,
                profile_url=profile_url,
                status=status,
                method=config.method,
                submitted_at=datetime.now(),
            )
        except _AwaitingVerification:
            return RemovalRequest(
                broker_name=config.name,
                profile_url=profile_url,
                status=RemovalStatus.AWAITING_VERIFICATION,
                method=config.method,
                submitted_at=datetime.now(),
            )
        except _ManualRequired as e:
            return RemovalRequest(
                broker_name=config.name,
                profile_url=profile_url,
                status=RemovalStatus.MANUAL_REQUIRED,
                method=config.method,
                submitted_at=datetime.now(),
                notes=str(e),
            )
        except Exception as e:
            return RemovalRequest(
                broker_name=config.name,
                profile_url=profile_url,
                status=RemovalStatus.FAILED,
                method=config.method,
                error=str(e),
            )
        finally:
            await page.close()

    async def _extract_profile_url(self, element, page: Page) -> str:
        """Extract the best profile URL from a result element.

        Tries: the element itself if it's a link, then child links
        (skipping generic/utility links), then falls back to page URL.
        """
        from urllib.parse import urljoin

        # If the element itself is a link, use it
        tag = await element.evaluate("el => el.tagName.toLowerCase()")
        if tag == "a":
            href = await element.get_attribute("href")
            if href and not href.startswith("/4:"):
                return urljoin(page.url, href)

        # Find all child links and pick the best one
        links = await element.query_selector_all("a[href]")
        skip_patterns = ["/contact", "/feedback", "/help", "/faq", "/redirect", "javascript:"]
        for link in links:
            href = await link.get_attribute("href")
            if not href or href.startswith("/4:"):
                continue
            if any(pat in href.lower() for pat in skip_patterns):
                continue
            return urljoin(page.url, href)

        return page.url

    async def _dump_debug_snapshot(self, broker_name: str, page: Page) -> None:
        """Save page HTML to ~/.ghosted/debug/ for selector debugging."""
        try:
            debug_dir = Path.home() / ".ghosted" / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            safe_name = broker_name.lower().replace(" ", "_").replace(".", "_")
            html = await page.content()
            snapshot_path = debug_dir / f"{safe_name}.html"
            snapshot_path.write_text(html, encoding="utf-8")
        except Exception:
            pass  # Debug snapshots are best-effort

    async def _dismiss_dialogs(self, page: Page) -> None:
        """Try to dismiss common overlay dialogs (TOS, cookie consent, etc.)."""
        # First: force-close any open <dialog> elements via JavaScript
        closed = await page.evaluate("""() => {
            let closed = 0;
            for (const d of document.querySelectorAll('dialog[open]')) {
                d.close();
                closed++;
            }
            // Also remove modal wrappers that block pointer events
            for (const el of document.querySelectorAll('[class*="modal-wrapper"], [class*="overlay"]')) {
                if (el.style) el.style.display = 'none';
            }
            return closed;
        }""")
        if closed:
            await asyncio.sleep(0.3)
            return

        # Fallback: try clicking common accept/dismiss buttons
        dismiss_selectors = [
            "[class*='consent'] button",
            "[class*='cookie'] button[class*='accept']",
            "[class*='cookie'] button[class*='agree']",
            "button[id*='accept']",
            "button[id*='agree']",
        ]
        for selector in dismiss_selectors:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.5)
                    return
            except Exception:
                continue

    async def _execute_step(
        self,
        step: BrokerStep,
        page: Page,
        profile: UserProfile,
        profile_url: str,
    ) -> str:
        """Execute a single opt-out step. Returns the (possibly updated) profile_url."""
        match step.action:
            case "navigate":
                url = self._substitute_vars(step.url, profile, profile_url)
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            case "fill":
                value = self._substitute_vars(step.value or "", profile, profile_url)
                await page.fill(step.selector, value)

            case "click":
                # Try to dismiss any overlay dialogs before clicking
                await self._dismiss_dialogs(page)
                try:
                    await page.click(step.selector, timeout=10000)
                except Exception:
                    # Retry with force if an overlay is still intercepting
                    await self._dismiss_dialogs(page)
                    await page.click(step.selector, force=True, timeout=10000)

            case "wait" | "wait_seconds":
                seconds = step.wait_seconds or 2.0
                await asyncio.sleep(seconds)

            case "capture_url":
                profile_url = page.url

            case "dismiss_dialogs":
                await self._dismiss_dialogs(page)

            case "solve_captcha":
                print(
                    f"\n[!] CAPTCHA detected on {page.url}\n"
                    "    Please solve it in the browser window, then press Enter to continue..."
                )
                await asyncio.get_event_loop().run_in_executor(None, input)

            case "manual_step":
                msg = self._substitute_vars(step.value or "Manual intervention required", profile, profile_url)
                raise _ManualRequired(msg)

            case "await_email" | "click_email_link":
                raise _AwaitingVerification()

            case _:
                print(f"Warning: unknown action '{step.action}', skipping")

        return profile_url

    def _substitute_vars(
        self,
        template: str,
        profile: UserProfile,
        profile_url: str = "",
    ) -> str:
        """Replace template variables with actual user profile values."""
        replacements = {
            "{{user.first_name}}": profile.first_name,
            "{{user.last_name}}": profile.last_name,
            "{{user.email}}": profile.email,
            "{{user.city}}": profile.city,
            "{{user.state}}": profile.state,
            "{{user.phone}}": profile.phone or "",
            "{{user.date_of_birth}}": profile.date_of_birth or "",
            "{{user.opt_out_email}}": profile.opt_out_email or profile.email,
            "{{profile_url}}": profile_url,
        }
        result = template
        for placeholder, value in replacements.items():
            result = result.replace(placeholder, value)
        return result


class _AwaitingVerification(Exception):
    """Internal signal that the opt-out flow requires email verification."""


class _ManualRequired(Exception):
    """Internal signal that the opt-out flow requires manual user action."""
