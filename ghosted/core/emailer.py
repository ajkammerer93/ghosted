"""Email integration for verification link checking and legal demand sending."""

import email
import imaplib
import re
import smtplib
import ssl
from datetime import datetime
from email.mime.text import MIMEText
from typing import Optional

from pydantic import BaseModel


class EmailConfig(BaseModel):
    """IMAP/SMTP configuration for email operations."""

    imap_host: str
    imap_port: int = 993
    smtp_host: str
    smtp_port: int = 587
    email: str
    password: str


async def connect_imap(config: EmailConfig) -> imaplib.IMAP4_SSL:
    """Connect and authenticate to the IMAP server."""
    import asyncio

    def _connect():
        ctx = ssl.create_default_context()
        conn = imaplib.IMAP4_SSL(config.imap_host, config.imap_port, ssl_context=ctx)
        conn.login(config.email, config.password)
        return conn

    return await asyncio.get_event_loop().run_in_executor(None, _connect)


async def check_verification_emails(
    config: EmailConfig,
    broker_patterns: dict[str, dict],
) -> list[dict]:
    """Search for unseen verification emails matching broker subject patterns.

    Args:
        config: Email credentials and server info.
        broker_patterns: Mapping of broker_name -> {"subject": ..., "link_pattern": ...}.

    Returns:
        List of dicts with broker_name, subject, verification_url, received_at.
    """
    import asyncio

    def _check():
        ctx = ssl.create_default_context()
        conn = imaplib.IMAP4_SSL(config.imap_host, config.imap_port, ssl_context=ctx)
        conn.login(config.email, config.password)
        conn.select("INBOX")

        results = []
        for broker_name, patterns in broker_patterns.items():
            subject_pattern = patterns.get("subject", "")
            link_pat = patterns.get("link_pattern", "")
            if not subject_pattern:
                continue

            sanitized = subject_pattern.replace('"', "").replace("\\", "")
            _, msg_nums = conn.search(None, "UNSEEN", f'SUBJECT "{sanitized}"')
            if not msg_nums or not msg_nums[0]:
                continue

            for num in msg_nums[0].split():
                _, msg_data = conn.fetch(num, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                subject = msg.get("Subject", "")
                date_str = msg.get("Date", "")
                body_html = _get_html_body(msg)
                links = extract_verification_links(body_html, link_pat) if body_html else []

                results.append({
                    "broker_name": broker_name,
                    "subject": subject,
                    "verification_url": links[0] if links else None,
                    "received_at": date_str,
                })

        conn.logout()
        return results

    return await asyncio.get_event_loop().run_in_executor(None, _check)


def extract_verification_links(html_body: str, link_pattern: str) -> list[str]:
    """Extract links from HTML that match the given pattern.

    If link_pattern is empty, returns all http/https links found.
    """
    # Find all href links
    href_re = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
    all_links = href_re.findall(html_body)

    # Filter to http(s) links
    all_links = [link for link in all_links if link.startswith(("http://", "https://"))]

    if not link_pattern:
        return all_links

    filtered = [link for link in all_links if re.search(link_pattern, link)]
    return filtered


async def click_verification_link(url: str, headless: bool = True) -> bool:
    """Navigate to a verification URL via Patchright and return success."""
    try:
        from patchright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=headless)
            page = await browser.new_page()
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                return response is not None and response.status < 400
            finally:
                await browser.close()
    except Exception:
        return False


async def send_legal_email(
    config: EmailConfig,
    to_email: str,
    subject: str,
    body: str,
) -> None:
    """Send a legal demand email (CCPA/GDPR) via SMTP with TLS."""
    import asyncio

    def _send():
        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"] = config.email
        msg["To"] = to_email

        ctx = ssl.create_default_context()
        with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
            server.starttls(context=ctx)
            server.login(config.email, config.password)
            server.send_message(msg)

    await asyncio.get_event_loop().run_in_executor(None, _send)


def _get_html_body(msg: email.message.Message) -> Optional[str]:
    """Extract the HTML body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        if msg.get_content_type() == "text/html":
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
    return None
