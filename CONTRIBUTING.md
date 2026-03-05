# Contributing to Ghosted

Thanks for your interest in contributing to Ghosted! The most impactful way to contribute is by adding new broker configs — there are 750+ data brokers out there and we only have 20 configured so far.

## Getting Started

```bash
# Fork and clone the repo
git clone https://github.com/<your-username>/ghosted.git
cd ghosted

# Install in dev mode
pip install -e ".[dev]"

# Install the patched Chromium browser
patchright install chromium

# Run the test suite
python -m pytest tests/ -x -q
```

## Adding a Broker Config

This is the easiest and most valuable contribution. Each broker is a single YAML file in the `brokers/` directory.

### 1. Research the Broker

Before writing any config, manually visit the broker site and find:

- **Search URL pattern** — How does the site search for people? Look at the URL after searching for a name + location.
- **Result selector** — What CSS selector matches result elements on the search page?
- **No-results indicator** — What CSS selector or text appears when there are no results?
- **Opt-out page** — Where is the removal/opt-out form? What fields does it require?
- **Cloudflare/bot protection** — Does the site use Cloudflare, Incapsula, or other WAF?

Use your browser's DevTools (F12) to inspect elements and find reliable selectors.

### 2. Create the YAML Config

Create `brokers/<broker_name>.yaml`:

```yaml
name: "BrokerName"
url: "https://example.com"
opt_out_url: "https://example.com/optout"
method: "web_form"
cloudflare: false
enabled: true
requires_email_verification: false
recommended_rescan_days: 60

search:
  url: "https://example.com/search?name={{user.first_name}}+{{user.last_name}}&city={{user.city}}&state={{user.state}}"
  result_selector: ".result-card"
  no_results_indicator: "No results found"

opt_out_steps:
  - action: navigate
    url: "{{profile_url}}"
  - action: click
    selector: ".opt-out-button"
  - action: fill
    selector: "#email"
    value: "{{user.opt_out_email}}"
  - action: click
    selector: "#submit"
```

### 3. Template Variables

These variables are available in `url` and `value` fields:

| Variable | Source |
|----------|--------|
| `{{user.first_name}}` | User's encrypted vault |
| `{{user.last_name}}` | User's encrypted vault |
| `{{user.city}}` | User's encrypted vault |
| `{{user.state}}` | User's encrypted vault |
| `{{user.opt_out_email}}` | User's encrypted vault |
| `{{profile_url}}` | Captured during scan or opt-out via `capture_url` action |

### 4. Config Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Display name for the broker |
| `url` | Yes | Broker's homepage |
| `opt_out_url` | Yes | Direct URL to the opt-out/removal page |
| `method` | Yes | One of: `web_form`, `email`, `phone`, `suppression_portal` |
| `cloudflare` | No | Set `true` if Cloudflare-protected (defaults to `false`) |
| `enabled` | No | Set `false` to disable (defaults to `true`) |
| `requires_email_verification` | No | Whether opt-out requires email confirmation |
| `recommended_rescan_days` | No | How often to re-scan (days) |
| `parent_company` | No | Parent company name (e.g., Intelius) |
| `captcha` | No | CAPTCHA type: `recaptcha_v2`, `recaptcha_v3`, `hcaptcha`, `generic` |
| `search.url` | Yes | URL template for people search |
| `search.result_selector` | Yes | CSS selector matching result elements |
| `search.name_selector` | No | CSS selector for the person's name within results |
| `search.no_results_indicator` | Yes | CSS selector or text that appears when no results found |
| `notes` | No | Free-text notes about quirks, timing, or known issues |

### 5. Opt-Out Step Actions

| Action | Fields | Description |
|--------|--------|-------------|
| `navigate` | `url` | Navigate to a URL |
| `fill` | `selector`, `value` | Type into a form field |
| `click` | `selector` | Click an element |
| `wait_seconds` | `wait_seconds` | Pause for N seconds |
| `capture_url` | `type: "profile_url"` | Save the current page URL as `{{profile_url}}` |
| `dismiss_dialogs` | — | Close overlay popups and modals |
| `solve_captcha` | `type` | Pause for manual CAPTCHA solving (headed mode) |
| `manual_step` | `description` | Display instructions for a step requiring manual action |
| `await_email` | `subject_pattern`, `timeout_minutes` | Wait for a verification email |
| `click_email_link` | `link_pattern` | Click a verification link in the received email |

### 6. Test Your Config

```bash
# Run the test suite to make sure nothing breaks
python -m pytest tests/ -x -q

# Test a scan against your broker (requires a vault)
ghosted scan --headed

# Check debug snapshots if the result is UNKNOWN
ls ~/.ghosted/debug/
```

Use `--headed` mode to watch the browser and verify your selectors work. Check the HTML snapshots in `~/.ghosted/debug/` if the scan returns UNKNOWN — this means neither the result selector nor the no-results indicator matched.

### Tips for Good Selectors

- **Prefer IDs and data attributes** over class names (less likely to change)
- **Be specific** — `.search-results .person-card` is better than `.card`
- **Test the no-results indicator** by searching for a name that won't exist (e.g., "Zzzzyx Qqqqppp")
- **Mark `cloudflare: true`** if the site uses Cloudflare — this prevents false "Clear" results when the scanner can't reach the actual page
- **Add `notes`** explaining any quirks you discovered — this helps future maintainers

## Bug Fixes and Features

1. **Fork the repo** and create a feature branch from `main`
2. **Make your changes** — keep them focused and minimal
3. **Run the tests** — `python -m pytest tests/ -x -q` (all 70 tests must pass)
4. **Submit a PR** against `main` with a clear description of what and why

### Code Style

- Python 3.11+ features are fine
- Use type hints for function signatures
- Follow existing patterns in the codebase — look at similar code before writing new code
- Keep changes small and focused — one PR per feature or fix

### What We're Looking For

- **New broker configs** — the biggest impact, lowest barrier to entry
- **Bug fixes** — especially for selector breakage on existing brokers
- **Improved anti-detection** — better approaches to bypass Cloudflare Turnstile or other WAFs
- **Email verification flow** — wiring `ghosted/core/emailer.py` into the `verify` command
- **Documentation improvements** — clearer instructions, more examples

### What to Avoid

- Large refactors without prior discussion
- Adding heavy dependencies
- Changes that break the encrypted vault format (backwards compatibility matters)
- Scraping or automation that violates a site's terms in ways that could create legal risk

## Reporting Issues

Open an issue on [GitHub](https://github.com/ajkammerer93/ghosted/issues) with:

- What you expected vs. what happened
- The broker name (if broker-specific)
- Whether you ran in headed or headless mode
- Any relevant output or debug snapshots

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
