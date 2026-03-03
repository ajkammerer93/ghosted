# Ghosted: Open-Source Personal Data Removal Tool
## Feasibility Report & Implementation Plan

---

## Executive Summary

**Verdict: Highly feasible and the market is wide open.**

An open-source personal data removal tool is not only technically feasible — it fills a significant gap in the current landscape. Our research found:

- **No production-ready open-source tool exists** despite strong demand. The two most promising projects (JustVanish, Privotron) are early-stage with limited coverage.
- **Commercial services charge $100-250/year** with mediocre results — Consumer Reports found the best only achieved 68% removal rates, while manual opt-out achieved 70%.
- **The legal landscape strongly favors users** — 20 US states now have privacy laws with deletion rights, GDPR covers the EU, and California's new DROP platform covers 500+ brokers.
- **60% of data brokers follow the same automatable opt-out pattern** (web form + email verification), making broad automation realistic.
- **EasyOptOuts proves the model works at $20/year**, suggesting operational costs are minimal and a free tool is sustainable.
- **Privacy-conscious users are forced to trust commercial services with their PII** — a fundamental contradiction that only a local-first, open-source tool can solve.

---

## 1. What We're Building

**Ghosted** is a local-first, open-source CLI tool that helps users find and remove their personal data from data brokers and people-search sites across the internet.

### Core Capabilities
1. **Scan** — Search 100+ data broker sites for the user's personal information
2. **Remove** — Automate opt-out requests via web forms and legal demand emails
3. **Monitor** — Periodically re-scan and re-submit removals (brokers re-list 73% of data within 90 days)
4. **Mask** — Optionally integrate with email aliasing services to protect identity during opt-outs

### Design Principles
- **Local-first**: All PII stays on the user's machine. No cloud, no telemetry.
- **Encrypted at rest**: User data stored in an encrypted local vault.
- **Transparent**: Open-source means full auditability of what data goes where.
- **Community-driven**: Plugin architecture so anyone can contribute broker support.
- **Semi-automated**: Automate everything possible, gracefully hand off to the user for CAPTCHAs and verification steps.

---

## 2. Market Context

### Commercial Landscape

| Service | Brokers | Price/Year | CR Effectiveness | Approach |
|---------|---------|-----------|-----------------|----------|
| Optery | 370-635 | $39-249 | 68% (best) | Tiered automated |
| EasyOptOuts | 160+ | $20 | 65% | Automated |
| Incogni | 420+ | $96 | Not tested | Automated recurring |
| DeleteMe | 181 automated | $105 | 44% | Hybrid |
| Cloaked | 120+ | $120 | Not tested | All-in-one privacy |
| Kanary | 1000+ scanned | $180 | 19% | Slow automated |

**Key insight**: Consumer Reports found manual opt-out achieved **70% success** — better than any commercial service. This validates that a well-guided tool assisting users through the process can outperform paid black-box services.

### Open-Source Landscape

| Project | Language | Approach | Brokers | Status |
|---------|----------|----------|---------|--------|
| JustVanish | Go | Email legal demands | Hundreds | Early dev (dry-run only) |
| Privotron | Python | Playwright automation | 3 | Early dev |
| DataBrokerBreaker | Python | CSV-driven steps | Limited | Active |
| databroker_remover | Next.js | Email-based | Limited | Active |
| BADBOOL | Markdown | Manual guide | 60+ | Actively maintained |

**The gap is clear**: No open-source tool combines browser automation + email-based legal demands + monitoring + community broker database into a production-ready package.

---

## 3. Technical Architecture

### Recommended Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Language | **Python 3.11+** | Largest scraping ecosystem, first-class Playwright support, rapid development |
| Browser Automation | **Playwright** | Multi-browser, built-in auto-waiting, stealth capabilities, active Microsoft maintenance |
| CLI Framework | **Typer + Rich** | Modern type-hint-based CLI with beautiful terminal output, progress bars, tables |
| Broker Configs | **YAML** | Declarative, human-readable, easy for community contributions |
| Local Database | **SQLite** | Zero-config, encrypted with sqlcipher or application-level Fernet encryption |
| Data Validation | **Pydantic** | Schema validation for broker configs and user profiles |
| Email Integration | **IMAP/SMTP** | For monitoring verification emails and sending legal demand letters |
| Scheduling | **Cron / APScheduler** | Periodic re-scanning (recommended every 2-4 weeks) |
| Email Masking | **SimpleLogin / addy.io** (optional) | Open-source email aliasing with REST APIs |

### Project Structure

```
ghosted/
├── ghosted/
│   ├── __init__.py
│   ├── cli.py                 # Typer CLI entry point
│   ├── core/
│   │   ├── scanner.py         # Scan brokers for user data
│   │   ├── remover.py         # Execute opt-out flows
│   │   ├── monitor.py         # Scheduled re-scanning
│   │   └── emailer.py         # IMAP monitoring + SMTP legal demands
│   ├── vault/
│   │   ├── store.py           # Encrypted local storage
│   │   └── crypto.py          # Fernet/AES encryption
│   ├── brokers/
│   │   ├── base.py            # Abstract broker plugin class
│   │   ├── registry.py        # Plugin discovery and loading
│   │   └── engine.py          # Playwright automation engine
│   ├── legal/
│   │   ├── templates/         # CCPA, GDPR, state-specific email templates
│   │   └── generator.py       # Legal demand letter generation
│   └── utils/
│       ├── captcha.py         # CAPTCHA detection + user handoff
│       └── reporting.py       # Scan results and removal status reports
├── brokers/                   # Community-contributed broker definitions
│   ├── schemas/
│   │   └── broker.schema.yaml # Validation schema for broker configs
│   ├── spokeo.yaml
│   ├── whitepages.yaml
│   ├── beenverified.yaml
│   ├── truepeoplesearch.yaml
│   ├── peopleconnect.yaml     # Covers Intelius, TruthFinder, etc.
│   └── ...
├── tests/
├── pyproject.toml
├── CONTRIBUTING.md            # Guide for adding new broker plugins
└── README.md
```

### Broker Plugin Format (YAML)

```yaml
# brokers/spokeo.yaml
name: Spokeo
url: https://www.spokeo.com
opt_out_url: https://www.spokeo.com/optout
method: web_form            # web_form | email | phone | suppression_portal
parent_company: null
captcha: recaptcha_v2
requires_email_verification: true
re_listing_rate: 89%        # Known re-listing within 60 days
recommended_rescan_days: 30

search:
  url: "https://www.spokeo.com/search?q={{user.first_name}}+{{user.last_name}}&l={{user.city}},+{{user.state}}"
  result_selector: ".search-result"
  name_selector: ".result-name"

opt_out_steps:
  - action: navigate
    url: "{{opt_out_url}}"
  - action: fill
    selector: "#url-input"
    value: "{{profile_url}}"
  - action: fill
    selector: "#email-input"
    value: "{{user.opt_out_email}}"
  - action: solve_captcha       # Pauses for user interaction
    type: recaptcha_v2
  - action: click
    selector: "#submit-btn"
  - action: await_email          # Monitor inbox for verification
    subject_pattern: "Spokeo Opt-Out"
    timeout_minutes: 60
  - action: click_email_link
    link_pattern: "spokeo.com/optout/verify"
```

### Five Automatable Opt-Out Patterns

| Pattern | Coverage | Method | Automation Level |
|---------|----------|--------|-----------------|
| **A: Web Form + Email Verify** | ~60% of brokers | Playwright fills form, monitors inbox for verification link | High (CAPTCHA is the bottleneck) |
| **B: URL Submit + Email Verify** | ~15% | Search site first, copy URL, submit to opt-out form | High |
| **C: Suppression Portal** | ~10% | Single portal covers multiple brands (e.g., PeopleConnect) | Very High |
| **D: Email Legal Demand** | ~10% | Generate CCPA/GDPR email, send via SMTP | Very High (fully automatable) |
| **E: Phone Call Required** | ~5% | Cannot automate — provide instructions + phone number | Manual only |

### Privacy-Preserving Data Model

```
~/.ghosted/
├── config.toml            # Non-sensitive settings (scan schedule, broker list)
├── vault.enc              # Encrypted user profile (name, addresses, emails, phones)
├── scan_history.db        # Encrypted SQLite (scan results, removal status, timestamps)
└── logs/                  # PII-redacted activity logs
```

- **Encryption**: AES-256 via Fernet, keyed to a user-provided passphrase
- **No network calls except to brokers**: Zero telemetry, no update checks, no crash reporting
- **PII never in configs**: Broker YAML uses `{{user.email}}` placeholders, never hardcoded values
- **Secure deletion**: `ghosted vault destroy` overwrites and deletes all user data

---

## 4. User Experience

### CLI Workflow

```bash
# Initial setup — encrypted vault for PII
$ ghosted init
  Enter a passphrase to encrypt your data: ********
  Full name: John Smith
  Email: john@example.com
  City, State: Portland, OR
  Phone (optional): 555-123-4567
  Previous addresses (optional): ...
  Vault created at ~/.ghosted/vault.enc

# Scan data brokers for your information
$ ghosted scan
  Scanning 147 data brokers...
  ████████████████████░░░░ 87/147

  Found on 23 brokers:
  ┌──────────────────┬────────────┬──────────────┐
  │ Broker           │ Info Found │ Opt-Out Type │
  ├──────────────────┼────────────┼──────────────┤
  │ Spokeo           │ Name,Phone │ Web Form     │
  │ WhitePages       │ Name,Addr  │ Web Form     │
  │ BeenVerified     │ Full       │ Web Form     │
  │ Intelius         │ Name,Phone │ Portal       │
  │ TruthFinder      │ Name,Addr  │ Portal       │
  │ Radaris          │ Full       │ Email        │
  │ Acxiom           │ Marketing  │ Phone Only   │
  │ ...              │            │              │
  └──────────────────┴────────────┴──────────────┘

# Remove your data from all found brokers
$ ghosted remove --all
  Processing 23 removal requests...

  [AUTO]  Intelius, TruthFinder, US Search — PeopleConnect portal (3 in 1)
  [AUTO]  TruePeopleSearch — submitted, awaiting email verification
  [AUTO]  Radaris — CCPA deletion email sent
  [NEED YOU] Spokeo — CAPTCHA required, opening browser...
  [MANUAL] Acxiom — phone call required: 877-774-2094

  Progress: 19/23 automated, 3 need your input, 1 manual
  Check email for 12 verification links.

# Monitor verification emails
$ ghosted verify
  Monitoring inbox for verification emails...
  ✓ TruePeopleSearch — verified
  ✓ Spokeo — verified
  ✓ BeenVerified — verified
  ⏳ FastPeopleSearch — waiting (expires in 47h)

# Schedule ongoing monitoring
$ ghosted monitor --schedule monthly
  Cron job created: re-scan on the 1st of each month
  You'll be notified if data reappears.

# Check status anytime
$ ghosted status
  Total brokers scanned: 147
  Data found on: 23
  Removals submitted: 23
  Removals confirmed: 18
  Pending verification: 3
  Manual action needed: 2
  Last scan: 2026-03-02
  Next scheduled scan: 2026-04-01
```

---

## 5. Legal Considerations

### Legal Templates (Multi-Jurisdiction)

The tool should ship with battle-tested legal templates for:

| Jurisdiction | Law | Key Right | Response Deadline |
|-------------|-----|-----------|-------------------|
| California | CCPA §1798.105 | Right to delete | 45 days |
| EU/EEA | GDPR Article 17 | Right to erasure | 30 days |
| Virginia | VCDPA | Right to delete | 45 days |
| Colorado | CPA | Right to delete | 45 days |
| Connecticut | CTDPA | Right to delete | 45 days |
| 15+ other states | Various | Right to delete | 30-45 days |

### California DROP Platform (Game-Changer)

As of January 2026, California's **Data Rights Online Portal (DROP)** allows CA residents to submit a single deletion request that reaches all 500+ registered data brokers. Brokers must process by August 2026.

**Ghosted should integrate with DROP** for California users while maintaining direct broker contact for non-CA users and brokers not in the DROP registry.

### Legal Risk Assessment

- **Low risk for the tool itself**: We're automating actions users are legally entitled to take. The tool acts as the user's agent.
- **CCPA explicitly allows authorized agents** to submit requests on behalf of consumers.
- **CAN-SPAM compliance**: Legal demand emails must include proper identification and not be deceptive.
- **Terms of Service**: Some broker sites prohibit automated access. However, automating opt-out requests that users have a legal right to make is a grey area that generally favors the user.

---

## 6. Key Challenges & Mitigations

| Challenge | Severity | Mitigation |
|-----------|----------|------------|
| **CAPTCHAs** | High | Semi-automated approach: prepare everything, hand off CAPTCHA to user in headed browser mode. Most brokers use simple reCAPTCHA v2 checkboxes. |
| **73% re-listing rate** | High | Mandatory scheduled re-scanning (monthly minimum). Track re-listing patterns per broker. Cite specific legal rights for more permanent deletion. |
| **Broker site changes** | Medium | YAML-based configs are easy to update. CI testing with mock responses. Version broker configs. Community maintenance model. |
| **Email deliverability** | Medium | Guide users on DKIM/SPF setup. Provide option to send from user's own email provider. Template emails designed to avoid spam filters. |
| **Anti-bot detection** | Medium | Run on user's own machine (residential IP). Headed browser mode. Human-speed delays. Playwright stealth plugin. For legitimate opt-outs, most brokers don't have aggressive anti-bot. |
| **Identity verification** | Low-Med | Some brokers require ID upload. Handle securely and locally. Provide clear instructions for manual steps. |
| **Broker database maintenance** | Medium | Community contribution model. Schema validation for new brokers. Seed from BADBOOL. CI testing. |

---

## 7. Implementation Roadmap

### Phase 1: MVP (Months 1-2)
**Goal**: Working CLI that can scan and remove from the top 20 brokers

- [ ] Project scaffolding (Python, Typer, Rich, Playwright)
- [ ] Encrypted vault for user PII
- [ ] Broker plugin system with YAML configs
- [ ] Playwright automation engine (Patterns A, B, C)
- [ ] Top 20 broker plugins (Spokeo, WhitePages, BeenVerified, TruePeopleSearch, FastPeopleSearch, PeopleConnect family, Radaris, Nuwber, ThatsThem, etc.)
- [ ] Email verification link monitoring (IMAP)
- [ ] Basic scan and remove commands
- [ ] Status reporting

### Phase 2: Legal & Email (Month 3)
**Goal**: Add email-based legal demand approach for broader coverage

- [ ] CCPA/GDPR legal demand email templates
- [ ] SMTP email sending for Pattern D brokers
- [ ] Multi-jurisdiction template selection
- [ ] Expand to 50+ brokers
- [ ] Scan result diffing (detect new vs returning listings)

### Phase 3: Monitoring & Scheduling (Month 4)
**Goal**: Automated ongoing protection

- [ ] Cron-based scheduled re-scanning
- [ ] Re-listing detection and automatic re-submission
- [ ] Notification system (email, desktop, webhook)
- [ ] Scan history and trend reporting
- [ ] Expand to 100+ brokers

### Phase 4: Community & Polish (Month 5-6)
**Goal**: Make it easy for others to contribute and use

- [ ] Broker contribution guide and schema validator
- [ ] CI/CD pipeline for testing broker configs
- [ ] TUI mode (Rich/Textual) for friendlier experience
- [ ] SimpleLogin/addy.io integration for email masking
- [ ] California DROP platform integration
- [ ] Documentation and onboarding
- [ ] Expand to 150+ brokers

### Phase 5: Future (6+ months)
- Tauri desktop app wrapper
- Browser extension companion
- International broker support (EU, UK, Canada, Brazil)
- Social media data detection (beyond traditional brokers)
- Google Search result monitoring

---

## 8. Competitive Advantages of Open Source

| Advantage | Ghosted (Open Source) | Commercial Services |
|-----------|----------------------|-------------------|
| **Trust** | Full source audit, local-only PII | Black box, PII sent to company |
| **Cost** | Free | $20-250/year |
| **Transparency** | See exactly what's sent where | No visibility |
| **Extensibility** | Community adds brokers | Limited to vendor's list |
| **Privacy** | PII never leaves your machine | Must trust vendor |
| **Customization** | Fork, modify, self-host | Take it or leave it |
| **Legal templates** | Community-maintained, multi-jurisdiction | Vendor-chosen |
| **Broker coverage** | Potentially unlimited via community | Capped by vendor resources |

---

## 9. Conclusion

Building **Ghosted** as an open-source, local-first data removal CLI is:

1. **Technically feasible** — Playwright + Python + YAML plugins is a proven architecture (Privotron validates this). 60% of brokers follow automatable patterns.

2. **Legally supported** — 20+ US states + GDPR give users strong deletion rights. CCPA explicitly allows authorized agents. California's DROP platform is a massive enabler.

3. **Market-validated** — Commercial services charge $100-250/yr proving demand. Consumer Reports showed manual opt-out beats most paid services, validating the assisted-automation approach.

4. **Differentiated** — No production-ready open-source tool exists. Local-first privacy, transparency, and community-driven broker coverage are genuine advantages over commercial offerings.

5. **Sustainable** — Plugin architecture means the community can maintain and expand broker coverage. The core engine is relatively stable; the broker configs are what need ongoing updates.

**The biggest risk is not technical — it's community adoption.** The tool needs enough contributors maintaining broker plugins to achieve meaningful coverage. Starting with the top 20 brokers (covering ~80% of exposed data) and growing from there is the right strategy.

The name "Ghosted" is fitting — help users disappear from the data broker internet.
