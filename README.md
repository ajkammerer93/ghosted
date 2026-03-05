# Ghosted

Open-source personal data removal tool. Scan, remove, and monitor your personal data across data brokers and people-search sites.

## Features

- **Scan** — Search 19 data broker sites for your personal information with honest status reporting (Found, Clear, Blocked, Error)
- **Remove** — Automate opt-out requests via web forms, with CAPTCHA handoff and manual-step instructions
- **Multi-profile** — Manage removals for yourself, spouse, family members — each with its own encrypted vault
- **Anti-detection** — Patchright (Playwright fork) with patched Chromium to bypass basic bot detection
- **Monitor** — Re-scan and track removal status over time with per-profile SQLite history
- **Local-first** — All data stays on your machine, encrypted at rest with PBKDF2-SHA256 + Fernet
- **Extensible** — YAML-based broker configs for easy community contributions

## Requirements

- Python 3.11+
- A Chromium-compatible environment (Linux, macOS, Windows, or WSL)

## Install

```bash
# Clone the repo
git clone https://github.com/ajkammerer93/ghosted.git
cd ghosted

# Install in editable mode
pip install -e .

# Install the patched Chromium browser
patchright install chromium
```

### Linux / WSL

Chromium requires system libraries that may not be present on a minimal Linux or WSL install:

```bash
# Automatic (recommended)
sudo patchright install-deps chromium

# Or manual
sudo apt-get install -y libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
  libgbm1 libpango-1.0-0 libcairo2 libasound2
```

### Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -x -q
```

## Quick Start

```bash
# 1. Create your encrypted profile
ghosted init

# 2. Scan data brokers
ghosted scan

# 3. Remove your data from brokers that found you
ghosted remove
```

You'll be prompted to set a vault passphrase on first run. This encrypts your personal information locally — it never leaves your machine.

## Usage

```bash
# Set up your encrypted profile
ghosted init

# Set up a profile for someone else
ghosted init --profile spouse

# Scan data brokers for your info
ghosted scan

# Scan a specific profile
ghosted scan --profile spouse

# Scan all profiles at once
ghosted scan --all-profiles

# Run with a visible browser window (useful for debugging or solving CAPTCHAs)
ghosted scan --headed
ghosted remove --headed

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

# Delete a profile and all its data
ghosted destroy-profile --profile spouse

# Delete all profiles
ghosted destroy-profile --all-profiles
```

### Headed vs Headless Mode

By default, scans run **headless** (no browser window). Use `--headed` to watch the browser in real time — useful for:

- Debugging selector issues
- Solving CAPTCHAs during opt-out flows
- Verifying results on Cloudflare-protected sites

**WSL note:** Headed mode requires WSLg (Windows 11) or an X server like VcXsrv (Windows 10). Test with:

```bash
sudo apt-get install -y x11-apps && xclock
```

## How It Works

Ghosted uses browser automation ([Patchright](https://github.com/nicoll-douglas/patchright)) to search data broker sites for your personal information and execute opt-out requests. Patchright is a Playwright fork that patches the Chromium binary itself to hide automation artifacts, providing better anti-detection than traditional stealth plugins.

### Data Storage

Your personal information is stored in an encrypted local vault at `~/.ghosted/profiles/<name>/vault.enc`. Each profile gets its own:

- **Encrypted vault** — AES-256 via Fernet, keyed to your passphrase (PBKDF2-SHA256 key derivation)
- **Scan history database** — SQLite at `~/.ghosted/profiles/<name>/scan_history.db`
- **Debug snapshots** — HTML dumps saved to `~/.ghosted/debug/` when scans return UNKNOWN status

No data is ever sent anywhere except to the broker sites themselves during scans and opt-outs.

### Scan Status Classification

Each broker scan returns one of five statuses:

| Status | Meaning |
|--------|---------|
| **Found** | Your data was found on this broker |
| **Clear** | Broker confirmed no results for your info |
| **Blocked** | Cloudflare, CAPTCHA, or other protection prevented the scan |
| **Error** | HTTP error (404, 5xx) or configuration issue |
| **Unknown** | Page loaded but neither results nor no-results indicator matched (debug snapshot saved) |

### Anti-Detection

The browser engine uses:

- **Patchright** — patches the Chromium binary to hide CDP (Chrome DevTools Protocol) artifacts
- Randomized viewports and user agents
- Anti-detection Chrome launch flags
- Dialog dismissal and force-click fallbacks for overlay popups

This bypasses basic bot checks but **not Cloudflare Turnstile** — 12 of 20 configured brokers are Cloudflare-protected and will report "Blocked" in headless mode.

### CAPTCHA Handling

Some brokers require CAPTCHAs during opt-out. In headed mode (`--headed`), the engine pauses and prompts you to solve the CAPTCHA in the browser window. Brokers requiring phone verification (like Whitepages) are marked as `MANUAL_REQUIRED` with instructions.

## Supported Brokers

20 broker configs (19 enabled), including:

| Broker | Status | Notes |
|--------|--------|-------|
| Acxiom | Scannable | Incapsula WAF; result_selector works when page loads |
| Addresses.com | Scannable | Intelius network |
| BeenVerified | CF-protected | Blocked in headless |
| CocoFinder | CF-protected | Blocked in headless |
| CyberBackgroundChecks | CF-protected | Blocked in headless |
| FastPeopleSearch | CF-protected | Blocked in headless |
| MyLife | Phone-only | Search disabled; manual removal via phone |
| Nuwber | CF-protected | Blocked in headless |
| PeopleConnect | Bot-protected | Returns 404 (Intelius network) |
| PeopleFinders | CF-protected | Blocked in headless |
| PeopleLooker | CF-protected | Blocked in headless |
| PublicRecordsNow | Disabled | SSL certificate expired |
| Radaris | CF-protected | Blocked in headless |
| SearchPeopleFree | CF-protected | Blocked in headless |
| Spokeo | CF-protected | CF may auto-resolve in headed mode |
| ThatsThem | CAPTCHA | Custom CAPTCHA; may auto-solve in headed mode |
| TruePeopleSearch | CF-protected | Blocked in headless |
| USPhoneBook | CF-protected | Blocked in headless |
| VeriPages | Scannable | Works reliably |
| Whitepages | Scannable | Phone verification required for removal |

Run `ghosted brokers` to see the full list with current status.

## Adding Brokers

Broker definitions are YAML files in the `brokers/` directory. Each config defines search URLs, result selectors, and opt-out step sequences.

### Example Broker Config

```yaml
name: "VeriPages"
url: "https://veripages.com"
opt_out_url: "https://veripages.com/optout"
method: "web_form"
cloudflare: false
enabled: true
requires_email_verification: true

search:
  url: "https://veripages.com/people/{{user.first_name}}-{{user.last_name}}/{{user.city}}-{{user.state}}"
  result_selector: ".card-user"
  no_results_indicator: ".no-records-search"

opt_out_steps:
  - action: navigate
    url: "{{profile_url}}"
  - action: click
    selector: ".opt-out-btn"
  - action: fill
    selector: "#email"
    value: "{{user.opt_out_email}}"
  - action: click
    selector: "#submit"
  - action: await_email
```

### Key Fields

| Field | Description |
|-------|-------------|
| `enabled` | Set to `false` to disable without deleting the config |
| `cloudflare` | Set to `true` for CF-protected brokers (scans report "Blocked" instead of false "Clear") |
| `method` | `web_form`, `email`, `phone`, or `suppression_portal` |
| `search.url` | URL template with `{{user.first_name}}`, `{{user.last_name}}`, `{{user.city}}`, `{{user.state}}` |
| `search.result_selector` | CSS selector that matches result elements when data is found |
| `search.no_results_indicator` | CSS selector or text string that appears when no data is found |

### Opt-Out Step Actions

| Action | Description |
|--------|-------------|
| `navigate` | Go to a URL |
| `fill` | Fill a form field (selector + value) |
| `click` | Click an element |
| `wait` / `wait_seconds` | Pause for a duration |
| `capture_url` | Save the current page URL as `{{profile_url}}` |
| `dismiss_dialogs` | Close overlay popups and modals |
| `solve_captcha` | Pause for manual CAPTCHA solving (headed mode) |
| `manual_step` | Mark as requiring manual user action |
| `await_email` | Wait for verification email |
| `click_email_link` | Click verification link in email |

## Project Structure

```
ghosted/
  cli.py              # Typer CLI entry point (init, scan, remove, verify, status, brokers, profiles, destroy-profile)
  models.py           # Pydantic models (UserProfile, BrokerConfig, ScanResult, ScanStatus, etc.)
  brokers/
    engine.py          # Patchright automation engine with anti-detection
    registry.py        # YAML config loader
  core/
    scanner.py         # Scan orchestration (iterates brokers, skips disabled/phone-only)
    remover.py         # Removal orchestration (routes by method: web_form, email, phone)
    history.py         # SQLite scan/removal history with auto-migration
    emailer.py         # IMAP/SMTP email integration (not yet wired into CLI)
  vault/
    store.py           # Encrypted profile storage (per-profile subdirectories)
    crypto.py          # PBKDF2-SHA256 key derivation + Fernet encryption
  legal/
    generator.py       # Legal email template renderer
    templates/         # CCPA, GDPR, generic removal templates
  utils/
    reporting.py       # Rich tables/panels for CLI output
    captcha.py         # CAPTCHA detection helpers
brokers/               # YAML broker configs (20 files)
tests/
  test_e2e.py          # 70 end-to-end tests
```

## Troubleshooting

### "Patchright browser not installed"

Run `patchright install chromium` to download the patched Chromium binary.

### All brokers show "Blocked"

This usually means Cloudflare is blocking headless browser access. Try:

1. `ghosted scan --headed` to use a visible browser window
2. Check `~/.ghosted/debug/` for HTML snapshots of blocked pages

### "Navigation timeout" errors

The broker's page didn't load within 30 seconds. This can happen with heavy bot protection. The scan URL is preserved in the result so you can check it manually.

### WSL headed mode doesn't work

You need a display server. On Windows 11, WSLg should work automatically. On Windows 10, install [VcXsrv](https://sourceforge.net/projects/vcxsrv/) and set `export DISPLAY=:0`.

### Vault passphrase issues

The passphrase is required every time you run a command that accesses your profile. There is no recovery mechanism — if you forget it, delete the vault with `ghosted destroy-profile` and re-create it.

## License

MIT
