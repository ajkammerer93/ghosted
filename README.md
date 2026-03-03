# Ghosted

Open-source personal data removal tool. Scan, remove, and monitor your personal data across data brokers and people-search sites.

## Features

- **Scan** — Search 19 data broker sites for your personal information with honest status classification (Found, Clear, Blocked, Unknown, Error)
- **Remove** — Automate opt-out requests via web forms and legal demand emails
- **Multi-profile** — Manage removals for yourself, spouse, family members
- **Stealth mode** — Anti-detection browser fingerprinting to bypass basic bot checks
- **Monitor** — Re-scan and track removal status over time
- **Local-first** — All data stays on your machine, encrypted at rest
- **Extensible** — YAML-based broker plugin system for community contributions

## Install

```bash
pip install -e .
playwright install chromium
```

### Linux / WSL

Chromium requires system libraries that may not be present on a minimal Linux or WSL install. Install them with:

```bash
sudo playwright install-deps chromium
```

Or manually:

```bash
sudo apt-get install -y libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
  libgbm1 libpango-1.0-0 libcairo2 libasound2
```

## Usage

```bash
# Set up your encrypted profile
ghosted init

# Set up a profile for someone else
ghosted init --profile spouse

# Scan data brokers for your info
ghosted scan

# Scan all profiles at once
ghosted scan --all-profiles

# Remove your data from found brokers
ghosted remove

# Remove from a specific broker
ghosted remove --broker Whitepages

# Check verification email status
ghosted verify

# View removal status dashboard
ghosted status

# List all profiles
ghosted profiles

# List available broker configs
ghosted brokers
```

### Headed mode

By default, scans run headless (no browser window). To see what the browser is doing:

```bash
ghosted scan --headed
ghosted remove --headed
```

On WSL, headed mode requires WSLg (Windows 11) or an X server (VcXsrv on Windows 10). Test with `sudo apt-get install -y x11-apps && xclock`.

## How It Works

Ghosted uses browser automation (Playwright) to search data broker sites for your personal information and execute opt-out requests on your behalf. For brokers that accept email-based removal requests, it generates legally-grounded demand letters citing CCPA, GDPR, or other applicable privacy laws.

Your personal information is stored in an encrypted local vault (`~/.ghosted/profiles/<name>/`) and never leaves your machine. Each profile gets its own encrypted vault and scan history database.

### Anti-detection

The browser engine uses playwright-stealth to patch common automation fingerprints, randomized viewports and user agents, and anti-detection launch arguments. This bypasses basic bot checks but not advanced protections like Cloudflare Turnstile — 11 of 20 brokers are Cloudflare-protected. The scan engine detects Cloudflare challenge pages (including "Just a moment", "Attention Required", "Security Challenge" titles), CAPTCHA walls, and HTTP error codes to classify results honestly rather than reporting false "clear" results. In headed mode, some CF challenges auto-resolve. Debug snapshots of unmatched pages are saved to `~/.ghosted/debug/` for selector troubleshooting.

### CAPTCHA handling

Some brokers require CAPTCHAs during opt-out. In headed mode, the engine pauses and prompts you to solve the CAPTCHA in the browser window. Brokers requiring phone verification (like Whitepages) are marked as "manual required" with instructions.

## Supported Brokers

20 data brokers configured (19 enabled), including Spokeo, Whitepages, BeenVerified, TruePeopleSearch, FastPeopleSearch, PeopleConnect (Intelius/TruthFinder/InstantCheckmate/USSearch), Radaris, Nuwber, ThatsThem, Addresses.com, VeriPages, and more.

Not all brokers will return results — 11 are behind Cloudflare and will show "Blocked" in headless mode. In headed mode, some CF challenges auto-resolve (e.g. Spokeo). Brokers with `cloudflare: true` in their YAML are known to be Cloudflare-protected. Run `ghosted brokers` to see the full list.

## Adding Brokers

Broker definitions are YAML files in the `brokers/` directory. Each config defines search URLs, result selectors, and opt-out step sequences. See any existing config for the format.

Key fields:
- `enabled: false` — disable a broker without removing its config
- `cloudflare: true` — mark a broker as Cloudflare-protected (scans will report "Blocked" instead of false "Clear")
- `search` — how to find the user on the site (URL template + CSS selectors)
- `opt_out_steps` — sequence of actions: navigate, fill, click, wait_seconds, capture_url, dismiss_dialogs, solve_captcha, manual_step, await_email, click_email_link

## Project Structure

```
ghosted/
  cli.py              # Typer CLI commands
  models.py           # Pydantic models (UserProfile, BrokerConfig, ScanResult, etc.)
  brokers/
    engine.py          # Playwright automation engine with stealth
    registry.py        # YAML config loader
  core/
    scanner.py         # Scan orchestration
    remover.py         # Removal orchestration
    history.py         # SQLite scan/removal history
    emailer.py         # IMAP/SMTP email integration
  vault/
    store.py           # Encrypted profile storage
    crypto.py          # PBKDF2 key derivation + Fernet encryption
  legal/
    generator.py       # Legal email template renderer
    templates/         # CCPA, GDPR, generic removal templates
  utils/
    reporting.py       # Rich tables/panels for CLI output
    captcha.py         # CAPTCHA detection helpers
brokers/               # YAML broker configs (20 files)
tests/
  test_e2e.py          # 58 e2e tests
```

## License

MIT
