"""Legal email generator for data broker removal requests."""

import re
from pathlib import Path

from ghosted.models import BrokerConfig, UserProfile

TEMPLATES_DIR = Path(__file__).parent / "templates"

JURISDICTION_MAP = {
    "ccpa": "ccpa_deletion.txt",
    "gdpr": "gdpr_erasure.txt",
    "generic": "generic_removal.txt",
}


def list_jurisdictions() -> list[str]:
    """Return available jurisdiction template names."""
    return list(JURISDICTION_MAP.keys())


def get_template_path(jurisdiction: str) -> Path:
    """Return the filesystem path for a jurisdiction's email template.

    Args:
        jurisdiction: One of "ccpa", "gdpr", or "generic".

    Raises:
        ValueError: If the jurisdiction is not recognized.
        FileNotFoundError: If the template file does not exist on disk.
    """
    filename = JURISDICTION_MAP.get(jurisdiction)
    if filename is None:
        valid = ", ".join(sorted(JURISDICTION_MAP.keys()))
        raise ValueError(
            f"Unknown jurisdiction '{jurisdiction}'. Valid options: {valid}"
        )
    path = TEMPLATES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    return path


def generate_legal_email(
    profile: UserProfile,
    broker: BrokerConfig,
    jurisdiction: str = "ccpa",
) -> tuple[str, str]:
    """Generate a legal removal email from a template.

    Loads the template for the given jurisdiction and substitutes all
    ``{{user.*}}`` and ``{{broker.*}}`` placeholders with values from
    the provided profile and broker config.

    Args:
        profile: The user's personal information.
        broker: The target data broker configuration.
        jurisdiction: Which legal template to use ("ccpa", "gdpr", or "generic").

    Returns:
        A (subject, body) tuple ready to send.

    Raises:
        ValueError: If the jurisdiction is not recognized.
        FileNotFoundError: If the template file is missing.
    """
    template_path = get_template_path(jurisdiction)
    raw = template_path.read_text(encoding="utf-8")

    # Build the replacement mapping
    replacements: dict[str, str] = {
        "{{user.first_name}}": profile.first_name,
        "{{user.last_name}}": profile.last_name,
        "{{user.email}}": profile.email,
        "{{user.city}}": profile.city,
        "{{user.state}}": profile.state,
        "{{user.phone}}": profile.phone or "",
        "{{user.opt_out_email}}": profile.opt_out_email or profile.email,
        "{{broker.name}}": broker.name,
        "{{broker.url}}": broker.url,
        "{{broker.opt_out_url}}": broker.opt_out_url,
    }

    text = raw
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)

    # Strip any remaining unresolved placeholders
    text = re.sub(r"\{\{[^}]+\}\}", "", text)

    # Split subject from body — first line starting with "Subject: " is the subject
    lines = text.split("\n", 1)
    subject = ""
    body = text
    if lines[0].startswith("Subject: "):
        subject = lines[0].removeprefix("Subject: ").strip()
        body = lines[1].lstrip("\n") if len(lines) > 1 else ""

    return subject, body
