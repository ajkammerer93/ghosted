"""Playwright-based automation engine for broker search and opt-out."""

import asyncio
import random
from datetime import datetime

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from ghosted.models import (
    BrokerConfig,
    BrokerStep,
    RemovalRequest,
    RemovalStatus,
    ScanResult,
    UserProfile,
)


class AutomationEngine:
    """Drives browser automation for searching and opting out of data brokers."""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def start(self) -> None:
        """Launch the Playwright browser."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context()

    async def stop(self) -> None:
        """Close the browser and clean up Playwright."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._context = None
        self._browser = None
        self._playwright = None

    async def search_broker(self, config: BrokerConfig, profile: UserProfile) -> ScanResult:
        """Search a broker for the user's data.

        Navigates to the broker's search URL, fills in template variables,
        and checks whether results are found.
        """
        if not config.search:
            return ScanResult(
                broker_name=config.name,
                found=False,
                error="No search configuration defined",
            )

        page: Page = await self._context.new_page()
        try:
            search_url = self._substitute_vars(config.search.url, profile)
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

            # Check for no-results indicator first
            if config.search.no_results_indicator:
                no_results = await page.query_selector(config.search.no_results_indicator)
                if no_results:
                    return ScanResult(broker_name=config.name, found=False)

            # Check for result matches
            results = await page.query_selector_all(config.search.result_selector)
            if results:
                # Try to grab the first result's link
                profile_url = None
                first = results[0]
                link = await first.query_selector("a")
                if link:
                    profile_url = await link.get_attribute("href")

                return ScanResult(
                    broker_name=config.name,
                    found=True,
                    profile_url=profile_url,
                )

            return ScanResult(broker_name=config.name, found=False)
        except Exception as e:
            return ScanResult(
                broker_name=config.name,
                found=False,
                error=str(e),
            )
        finally:
            await page.close()

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
                await self._execute_step(step, page, profile, profile_url)
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

    async def _execute_step(
        self,
        step: BrokerStep,
        page: Page,
        profile: UserProfile,
        profile_url: str,
    ) -> None:
        """Execute a single opt-out step."""
        match step.action:
            case "navigate":
                url = self._substitute_vars(step.url, profile, profile_url)
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            case "fill":
                value = self._substitute_vars(step.value or "", profile, profile_url)
                await page.fill(step.selector, value)

            case "click":
                await page.click(step.selector)

            case "wait":
                seconds = step.wait_seconds or 2.0
                await asyncio.sleep(seconds)

            case "solve_captcha":
                print(
                    f"\n[!] CAPTCHA detected on {page.url}\n"
                    "    Please solve it in the browser window, then press Enter to continue..."
                )
                await asyncio.get_event_loop().run_in_executor(None, input)

            case "await_email" | "click_email_link":
                raise _AwaitingVerification()

            case _:
                print(f"Warning: unknown action '{step.action}', skipping")

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
