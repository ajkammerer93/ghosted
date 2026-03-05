"""Email integration for verification link checking and legal demand sending."""

import email
import html
import imaplib
import ipaddress
import logging
import re
import smtplib
import ssl
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel


logger = logging.getLogger(__name__)


class EmailConfig(BaseModel):
    """IMAP/SMTP configuration for email operations."""

    imap_host: str
    imap_port: int = 993
    smtp_host: str = ""
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

            # Use broker name for broad IMAP substring search, then filter client-side
            search_term = broker_name.replace('"', "").replace("\\", "")
            _, msg_nums = conn.search(None, "UNSEEN", f'SUBJECT "{search_term}"')
            if not msg_nums or not msg_nums[0]:
                continue

            for num in msg_nums[0].split():
                _, msg_data = conn.fetch(num, "(BODY.PEEK[])")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                subject = msg.get("Subject", "")
                # Filter client-side with regex against the full subject pattern
                if not re.search(subject_pattern, subject, re.IGNORECASE):
                    continue

                date_str = msg.get("Date", "")
                body_html, body_text = _get_email_body(msg)
                if body_html:
                    links = extract_verification_links(body_html, link_pat)
                elif body_text:
                    links = extract_verification_links_from_text(body_text, link_pat)
                else:
                    links = []

                results.append({
                    "broker_name": broker_name,
                    "subject": subject,
                    "verification_url": links[0] if links else None,
                    "received_at": date_str,
                })

        # Dedup: keep only the most recent (last) email per broker
        seen: dict[str, dict] = {}
        for result in results:
            seen[result["broker_name"]] = result
        deduped = list(seen.values())

        conn.logout()
        return deduped

    return await asyncio.get_event_loop().run_in_executor(None, _check)


def extract_verification_links(html_body: str, link_pattern: str) -> list[str]:
    """Extract links from HTML that match the given pattern.

    If link_pattern is empty, returns all http/https links found.
    """
    href_re = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
    all_links = href_re.findall(html_body)

    # Unescape HTML entities in URLs
    all_links = [html.unescape(link) for link in all_links]

    # Filter to http(s) links
    all_links = [link for link in all_links if link.startswith(("http://", "https://"))]

    if not link_pattern:
        return all_links

    filtered = [link for link in all_links if re.search(link_pattern, link)]
    return filtered


def extract_verification_links_from_text(plain_text: str, link_pattern: str) -> list[str]:
    """Extract links from plain text that match the given pattern."""
    url_re = re.compile(r'https?://[^\s<>"\']+')
    all_links = url_re.findall(plain_text)

    if not link_pattern:
        return all_links

    filtered = [link for link in all_links if re.search(link_pattern, link)]
    return filtered


def _is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private/reserved IP address."""
    try:
        addr = ipaddress.ip_address(hostname)
        return addr.is_private or addr.is_reserved or addr.is_loopback or addr.is_link_local
    except ValueError:
        # Not a raw IP — it's a hostname, which is fine
        return False


async def click_verification_link(
    url: str, headless: bool = True, allowed_domain: str = ""
) -> bool:
    """Navigate to a verification URL via Patchright and return success."""
    # Validate URL before navigating
    parsed = urlparse(url)
    if parsed.scheme != "https":
        logger.warning("Rejected non-HTTPS verification URL: %s", url)
        return False

    hostname = parsed.hostname or ""
    if hostname == "localhost" or _is_private_ip(hostname):
        logger.warning("Rejected private/reserved IP in verification URL: %s", url)
        return False

    if allowed_domain and allowed_domain not in hostname:
        logger.warning(
            "Rejected URL domain %s — expected %s", hostname, allowed_domain
        )
        return False

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
    except Exception as exc:
        _log_verify_error(exc)
        return False


def _log_verify_error(exc: Exception) -> None:
    """Log verification errors to ~/.ghosted/debug/verify_errors.log."""
    debug_dir = Path.home() / ".ghosted" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    log_path = debug_dir / "verify_errors.log"
    timestamp = datetime.now().isoformat()
    with open(log_path, "a") as f:
        f.write(f"[{timestamp}] {type(exc).__name__}: {exc}\n")


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


def _get_email_body(msg: email.message.Message) -> tuple[Optional[str], Optional[str]]:
    """Extract the HTML and plain-text bodies from an email message.

    Returns:
        Tuple of (html_body, text_body). Either may be None.
    """
    html_body = None
    text_body = None

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if ctype == "text/html" and html_body is None:
                html_body = decoded
            elif ctype == "text/plain" and text_body is None:
                text_body = decoded
    else:
        ctype = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if ctype == "text/html":
                html_body = decoded
            elif ctype == "text/plain":
                text_body = decoded

    return html_body, text_body
