# Ghosted

Open-source personal data removal tool. Scan, remove, and monitor your personal data across data brokers and people-search sites.

## Features

- **Scan** — Search 100+ data broker sites for your personal information
- **Remove** — Automate opt-out requests via web forms and legal demand emails
- **Monitor** — Periodically re-scan and re-submit removals
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

# Scan data brokers for your info
ghosted scan

# Remove your data from found brokers
ghosted remove --all

# Check verification email status
ghosted verify

# View removal status dashboard
ghosted status

# List available broker configs
ghosted brokers
```

## How It Works

Ghosted uses browser automation (Playwright) to search data broker sites for your personal information and execute opt-out requests on your behalf. For brokers that accept email-based removal requests, it generates legally-grounded demand letters citing CCPA, GDPR, or other applicable privacy laws.

Your personal information is stored in an encrypted local vault (`~/.ghosted/vault.enc`) and never leaves your machine.

## Supported Brokers

20 data brokers supported in the MVP, including Spokeo, WhitePages, BeenVerified, TruePeopleSearch, FastPeopleSearch, PeopleConnect (Intelius/TruthFinder/InstantCheckmate/USSearch), Radaris, and more.

## Adding Brokers

Broker definitions are YAML files in the `brokers/` directory. See any existing config for the format. Contributions welcome.

## License

MIT
