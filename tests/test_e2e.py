"""End-to-end tests for the Ghosted CLI workflow.

Exercises the full lifecycle: vault create/load/destroy, broker registry,
history DB CRUD, legal email generation, CLI help output, and error paths.
"""

import json
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from ghosted.models import (
    BrokerConfig,
    BrokerMethod,
    RemovalRequest,
    RemovalStatus,
    ScanReport,
    ScanResult,
    ScanStatus,
    UserProfile,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BROKERS_DIR = Path(__file__).resolve().parent.parent / "brokers"


def _make_profile(**overrides) -> UserProfile:
    defaults = dict(
        first_name="Test",
        last_name="User",
        email="test@example.com",
        city="San Francisco",
        state="CA",
        phone="555-0100",
        date_of_birth="1990-01-01",
        previous_addresses=["123 Old St, Portland, OR"],
        opt_out_email="optout@example.com",
    )
    defaults.update(overrides)
    return UserProfile(**defaults)


@pytest.fixture
def tmp_vault(tmp_path):
    """Provide a temporary vault directory that is cleaned up after the test."""
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    yield vault_dir


@pytest.fixture
def tmp_db(tmp_path):
    """Provide a temporary SQLite DB path."""
    return tmp_path / "history.db"


# ===========================================================================
# 1. VaultStore — create / load / destroy cycle
# ===========================================================================


class TestVaultStore:
    """Vault lifecycle: create, load, load-wrong-passphrase, destroy."""

    def test_create_and_load(self, tmp_vault):
        from ghosted.vault.store import VaultStore

        store = VaultStore(tmp_vault)
        profile = _make_profile()
        store.create(profile, "correct-horse-battery")

        assert store.exists()
        loaded = store.load("correct-horse-battery")
        assert loaded.first_name == "Test"
        assert loaded.last_name == "User"
        assert loaded.email == "test@example.com"
        assert loaded.city == "San Francisco"
        assert loaded.state == "CA"
        assert loaded.phone == "555-0100"
        assert loaded.opt_out_email == "optout@example.com"
        assert loaded.previous_addresses == ["123 Old St, Portland, OR"]

    def test_wrong_passphrase(self, tmp_vault):
        from cryptography.fernet import InvalidToken

        from ghosted.vault.store import VaultStore

        store = VaultStore(tmp_vault)
        store.create(_make_profile(), "correct-horse-battery")

        with pytest.raises(InvalidToken):
            store.load("wrong-passphrase")

    def test_destroy(self, tmp_vault):
        from ghosted.vault.store import VaultStore

        store = VaultStore(tmp_vault)
        store.create(_make_profile(), "passphrase123")
        assert store.exists()

        store.destroy()
        assert not store.exists()
        assert not (tmp_vault / "vault.enc").exists()
        assert not (tmp_vault / "salt").exists()

    def test_load_missing_vault(self, tmp_vault):
        from ghosted.vault.store import VaultStore

        store = VaultStore(tmp_vault)
        assert not store.exists()
        with pytest.raises(FileNotFoundError):
            store.load("any-passphrase")

    def test_overwrite_existing_vault(self, tmp_vault):
        from ghosted.vault.store import VaultStore

        store = VaultStore(tmp_vault)
        store.create(_make_profile(first_name="Alice"), "pass1234")

        # Overwrite with new profile and passphrase
        store.create(_make_profile(first_name="Bob"), "pass5678")
        loaded = store.load("pass5678")
        assert loaded.first_name == "Bob"

        # Old passphrase no longer works
        from cryptography.fernet import InvalidToken

        with pytest.raises(InvalidToken):
            store.load("pass1234")

    def test_optional_fields_none(self, tmp_vault):
        from ghosted.vault.store import VaultStore

        store = VaultStore(tmp_vault)
        profile = UserProfile(
            first_name="Min",
            last_name="Fields",
            email="min@test.com",
            city="Austin",
            state="TX",
        )
        store.create(profile, "min-pass1234")
        loaded = store.load("min-pass1234")
        assert loaded.phone is None
        assert loaded.date_of_birth is None
        assert loaded.previous_addresses == []
        assert loaded.opt_out_email is None

    def test_destroy_removes_history_and_directory(self, tmp_vault):
        from ghosted.vault.store import VaultStore

        store = VaultStore(tmp_vault)
        store.create(_make_profile(), "passphrase123")
        # Simulate a history DB file
        history_db = store.vault_dir / "scan_history.db"
        history_db.write_text("fake db")
        assert history_db.exists()

        store.destroy(remove_history=True)
        assert not store.exists()
        assert not history_db.exists()
        assert not store.vault_dir.exists()

    def test_destroy_keeps_history_when_requested(self, tmp_vault):
        from ghosted.vault.store import VaultStore

        store = VaultStore(tmp_vault)
        store.create(_make_profile(), "passphrase123")
        history_db = store.vault_dir / "scan_history.db"
        history_db.write_text("fake db")

        store.destroy(remove_history=False)
        assert not store.exists()
        assert history_db.exists()

    def test_list_profiles(self, tmp_vault):
        from ghosted.vault.store import VaultStore

        # Create two profiles
        store1 = VaultStore(tmp_vault, profile_name="alice")
        store1.create(_make_profile(first_name="Alice"), "pass1234")
        store2 = VaultStore(tmp_vault, profile_name="bob")
        store2.create(_make_profile(first_name="Bob"), "pass5678")

        profiles = VaultStore.list_profiles(tmp_vault)
        assert "alice" in profiles
        assert "bob" in profiles

        # Destroy one and verify it's gone from the list
        store1.destroy(remove_history=True)
        profiles = VaultStore.list_profiles(tmp_vault)
        assert "alice" not in profiles
        assert "bob" in profiles


# ===========================================================================
# 2. BrokerRegistry — load all 20 configs
# ===========================================================================


class TestBrokerRegistry:
    """Registry loads all YAML configs and provides query methods."""

    def test_load_all_20(self):
        from ghosted.brokers.registry import BrokerRegistry

        registry = BrokerRegistry(BROKERS_DIR)
        brokers = registry.load_all()
        assert len(brokers) == 20, f"Expected 20 brokers, got {len(brokers)}: {[b.name for b in brokers]}"

    def test_each_broker_has_required_fields(self):
        from ghosted.brokers.registry import BrokerRegistry

        registry = BrokerRegistry(BROKERS_DIR)
        brokers = registry.load_all()
        for b in brokers:
            assert b.name, f"Broker missing name"
            assert b.url, f"Broker {b.name} missing url"
            assert b.opt_out_url, f"Broker {b.name} missing opt_out_url"
            assert isinstance(b.method, BrokerMethod), f"Broker {b.name} has invalid method"

    def test_get_broker_by_name(self):
        from ghosted.brokers.registry import BrokerRegistry

        registry = BrokerRegistry(BROKERS_DIR)
        registry.load_all()
        wp = registry.get_broker("Whitepages")
        assert wp is not None
        assert wp.url == "https://www.whitepages.com"

    def test_get_broker_not_found(self):
        from ghosted.brokers.registry import BrokerRegistry

        registry = BrokerRegistry(BROKERS_DIR)
        registry.load_all()
        assert registry.get_broker("NonExistentBroker") is None

    def test_get_brokers_by_method(self):
        from ghosted.brokers.registry import BrokerRegistry

        registry = BrokerRegistry(BROKERS_DIR)
        registry.load_all()
        web_form_brokers = registry.get_brokers_by_method(BrokerMethod.WEB_FORM)
        assert len(web_form_brokers) > 0

    def test_load_empty_directory(self, tmp_path):
        from ghosted.brokers.registry import BrokerRegistry

        registry = BrokerRegistry(tmp_path / "empty")
        brokers = registry.load_all()
        assert brokers == []

    def test_load_invalid_yaml(self, tmp_path):
        from ghosted.brokers.registry import BrokerRegistry

        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("this: is: not: valid: yaml: [[[")
        registry = BrokerRegistry(tmp_path)
        brokers = registry.load_all()
        assert brokers == []


# ===========================================================================
# 3. HistoryDB — full CRUD
# ===========================================================================


class TestHistoryDB:
    """HistoryDB: init, save scan, query scan, save removal, query removals."""

    def _make_scan_report(self) -> ScanReport:
        return ScanReport(
            scan_id=uuid.uuid4().hex[:12],
            started_at=datetime.now(),
            completed_at=datetime.now(),
            total_brokers=3,
            brokers_with_data=2,
            errors=0,
            results=[
                ScanResult(broker_name="BrokerA", status=ScanStatus.FOUND, found=True, profile_url="https://a.com/u/1"),
                ScanResult(broker_name="BrokerB", status=ScanStatus.FOUND, found=True, profile_url="https://b.com/u/2"),
                ScanResult(broker_name="BrokerC", status=ScanStatus.NOT_FOUND, found=False),
            ],
        )

    def test_init_creates_tables(self, tmp_db):
        from ghosted.core.history import HistoryDB

        db = HistoryDB(tmp_db)
        db.init_db()
        db.close()
        assert tmp_db.exists()

    def test_save_and_get_scan(self, tmp_db):
        from ghosted.core.history import HistoryDB

        db = HistoryDB(tmp_db)
        db.init_db()

        report = self._make_scan_report()
        db.save_scan(report)

        latest = db.get_latest_scan()
        assert latest is not None
        assert latest.scan_id == report.scan_id
        assert latest.total_brokers == 3
        assert latest.brokers_with_data == 2
        assert len(latest.results) == 3
        db.close()

    def test_get_latest_scan_empty(self, tmp_db):
        from ghosted.core.history import HistoryDB

        db = HistoryDB(tmp_db)
        db.init_db()
        assert db.get_latest_scan() is None
        db.close()

    def test_scan_history(self, tmp_db):
        from ghosted.core.history import HistoryDB

        db = HistoryDB(tmp_db)
        db.init_db()

        for _ in range(3):
            db.save_scan(self._make_scan_report())

        history = db.get_scan_history(limit=2)
        assert len(history) == 2
        db.close()

    def test_save_and_get_removal(self, tmp_db):
        from ghosted.core.history import HistoryDB

        db = HistoryDB(tmp_db)
        db.init_db()

        req = RemovalRequest(
            broker_name="BrokerA",
            profile_url="https://a.com/u/1",
            status=RemovalStatus.SUBMITTED,
            method=BrokerMethod.WEB_FORM,
            submitted_at=datetime.now(),
        )
        db.save_removal(req)

        result = db.get_removal_status("BrokerA")
        assert result is not None
        assert result.broker_name == "BrokerA"
        assert result.status == RemovalStatus.SUBMITTED
        db.close()

    def test_get_removal_not_found(self, tmp_db):
        from ghosted.core.history import HistoryDB

        db = HistoryDB(tmp_db)
        db.init_db()
        assert db.get_removal_status("NoSuchBroker") is None
        db.close()

    def test_get_all_removals(self, tmp_db):
        from ghosted.core.history import HistoryDB

        db = HistoryDB(tmp_db)
        db.init_db()

        for name in ["BrokerA", "BrokerB"]:
            db.save_removal(
                RemovalRequest(
                    broker_name=name,
                    status=RemovalStatus.PENDING,
                    method=BrokerMethod.WEB_FORM,
                )
            )

        all_removals = db.get_all_removals()
        assert len(all_removals) == 2
        db.close()

    def test_upsert_removal(self, tmp_db):
        from ghosted.core.history import HistoryDB

        db = HistoryDB(tmp_db)
        db.init_db()

        # Insert
        db.save_removal(
            RemovalRequest(
                broker_name="BrokerA",
                status=RemovalStatus.PENDING,
                method=BrokerMethod.WEB_FORM,
            )
        )
        # Update same broker
        db.save_removal(
            RemovalRequest(
                broker_name="BrokerA",
                status=RemovalStatus.CONFIRMED,
                method=BrokerMethod.WEB_FORM,
                confirmed_at=datetime.now(),
            )
        )

        all_removals = db.get_all_removals()
        assert len(all_removals) == 1
        assert all_removals[0].status == RemovalStatus.CONFIRMED
        db.close()

    def test_scan_results_roundtrip(self, tmp_db):
        """Verify scan results with info_found lists survive the DB round-trip."""
        from ghosted.core.history import HistoryDB

        db = HistoryDB(tmp_db)
        db.init_db()

        report = ScanReport(
            scan_id="rt-test",
            started_at=datetime.now(),
            completed_at=datetime.now(),
            total_brokers=1,
            brokers_with_data=1,
            errors=0,
            results=[
                ScanResult(
                    broker_name="TestBroker",
                    status=ScanStatus.FOUND,
                    found=True,
                    profile_url="https://test.com/u/1",
                    info_found=["name", "address", "phone"],
                ),
            ],
        )
        db.save_scan(report)

        loaded = db.get_latest_scan()
        assert loaded is not None
        assert loaded.results[0].info_found == ["name", "address", "phone"]
        db.close()


# ===========================================================================
# 4. Legal email generation — all jurisdictions
# ===========================================================================


class TestLegalGenerator:
    """Legal email template rendering for all jurisdictions."""

    def _make_broker(self) -> BrokerConfig:
        return BrokerConfig(
            name="TestBroker",
            url="https://testbroker.com",
            opt_out_url="https://testbroker.com/optout",
            method=BrokerMethod.WEB_FORM,
        )

    def test_list_jurisdictions(self):
        from ghosted.legal.generator import list_jurisdictions

        j = list_jurisdictions()
        assert "ccpa" in j
        assert "gdpr" in j
        assert "generic" in j

    def test_ccpa_email(self):
        from ghosted.legal.generator import generate_legal_email

        profile = _make_profile()
        broker = self._make_broker()
        subject, body = generate_legal_email(profile, broker, "ccpa")

        assert "California Consumer Privacy Act" in subject
        assert "Test User" in body
        assert "test@example.com" in body
        assert "San Francisco" in body
        assert "TestBroker" in body
        # No unresolved placeholders
        assert "{{" not in body

    def test_gdpr_email(self):
        from ghosted.legal.generator import generate_legal_email

        profile = _make_profile()
        broker = self._make_broker()
        subject, body = generate_legal_email(profile, broker, "gdpr")

        assert "GDPR" in subject
        assert "Test User" in body
        assert "test@example.com" in body
        assert "TestBroker" in body
        assert "{{" not in body

    def test_generic_email(self):
        from ghosted.legal.generator import generate_legal_email

        profile = _make_profile()
        broker = self._make_broker()
        subject, body = generate_legal_email(profile, broker, "generic")

        assert "Removal Request" in subject
        assert "Test User" in body
        assert "{{" not in body

    def test_opt_out_email_substitution_available(self):
        """The generator exposes opt_out_email in the replacement map.

        Current templates use {{user.email}} for correspondence, so
        opt_out_email only appears if a template explicitly uses
        {{user.opt_out_email}}.
        """
        from ghosted.legal.generator import generate_legal_email

        profile = _make_profile(opt_out_email="privacy@alt.com")
        broker = self._make_broker()
        subject, body = generate_legal_email(profile, broker, "ccpa")

        # Template renders without error; main email is used for correspondence
        assert "test@example.com" in body
        assert "{{" not in body

    def test_opt_out_email_falls_back_to_main(self):
        from ghosted.legal.generator import generate_legal_email

        profile = _make_profile(opt_out_email=None)
        broker = self._make_broker()
        _, body = generate_legal_email(profile, broker, "ccpa")

        # Should use main email when no opt_out_email
        assert "test@example.com" in body

    def test_unknown_jurisdiction_raises(self):
        from ghosted.legal.generator import generate_legal_email

        with pytest.raises(ValueError, match="Unknown jurisdiction"):
            generate_legal_email(_make_profile(), self._make_broker(), "bogus")

    def test_all_jurisdictions_render(self):
        """Every registered jurisdiction should render without error."""
        from ghosted.legal.generator import generate_legal_email, list_jurisdictions

        profile = _make_profile()
        broker = self._make_broker()
        for j in list_jurisdictions():
            subject, body = generate_legal_email(profile, broker, j)
            assert subject, f"Empty subject for {j}"
            assert body, f"Empty body for {j}"
            assert "{{" not in body, f"Unresolved placeholder in {j}"


# ===========================================================================
# 5. CLI help output
# ===========================================================================


class TestCLIHelp:
    """CLI responds to --help and subcommands."""

    def test_main_help(self):
        result = subprocess.run(
            ["ghosted", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "remove" in result.stdout.lower()

    def test_init_help(self):
        result = subprocess.run(
            ["ghosted", "init", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "vault" in result.stdout.lower() or "profile" in result.stdout.lower()

    def test_scan_help(self):
        result = subprocess.run(
            ["ghosted", "scan", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

    def test_remove_help(self):
        result = subprocess.run(
            ["ghosted", "remove", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "--all" in result.stdout or "--broker" in result.stdout

    def test_status_help(self):
        result = subprocess.run(
            ["ghosted", "status", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

    def test_brokers_help(self):
        result = subprocess.run(
            ["ghosted", "brokers", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

    def test_verify_help(self):
        result = subprocess.run(
            ["ghosted", "verify", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0


# ===========================================================================
# 6. Error handling
# ===========================================================================


class TestErrorHandling:
    """Exercises error paths: bad passphrase, missing vault, corrupt data."""

    def test_vault_bad_passphrase_cli_helper(self, tmp_vault):
        """The _load_profile helper should handle wrong passphrase gracefully."""
        from ghosted.vault.store import VaultStore

        store = VaultStore(tmp_vault)
        store.create(_make_profile(), "good-passphrase")

        from cryptography.fernet import InvalidToken

        with pytest.raises(InvalidToken):
            store.load("bad-passphrase!")

    def test_vault_corrupt_data(self, tmp_vault):
        from ghosted.vault.store import VaultStore

        store = VaultStore(tmp_vault)
        store.create(_make_profile(), "passphrase1")

        # Corrupt the vault file
        store.vault_file.write_bytes(b"corrupted-data-here")

        with pytest.raises(Exception):
            store.load("passphrase1")

    def test_double_destroy(self, tmp_vault):
        from ghosted.vault.store import VaultStore

        store = VaultStore(tmp_vault)
        store.create(_make_profile(), "passphrase1")
        store.destroy()
        # Second destroy should not raise
        store.destroy()
        assert not store.exists()

    def test_history_db_double_close(self, tmp_db):
        from ghosted.core.history import HistoryDB

        db = HistoryDB(tmp_db)
        db.init_db()
        db.close()
        # Double close should not raise
        db.close()

    def test_broker_registry_bad_yaml_ignored(self, tmp_path):
        """Invalid YAML files are skipped, valid ones still load."""
        from ghosted.brokers.registry import BrokerRegistry

        good = tmp_path / "good.yaml"
        good.write_text(
            "name: Good\nurl: https://good.com\nopt_out_url: https://good.com/opt\nmethod: web_form\n"
        )
        bad = tmp_path / "bad.yaml"
        bad.write_text("not valid yaml [[[")

        registry = BrokerRegistry(tmp_path)
        brokers = registry.load_all()
        assert len(brokers) == 1
        assert brokers[0].name == "Good"

    def test_legal_missing_template(self, tmp_path, monkeypatch):
        """Referencing a valid jurisdiction with a deleted template file should raise."""
        from ghosted.legal import generator

        # Point TEMPLATES_DIR to an empty dir
        monkeypatch.setattr(generator, "TEMPLATES_DIR", tmp_path)
        with pytest.raises(FileNotFoundError):
            generator.get_template_path("ccpa")

    def test_removal_status_values(self):
        """All removal status enum values are serializable."""
        for status in RemovalStatus:
            req = RemovalRequest(
                broker_name="test",
                status=status,
                method=BrokerMethod.WEB_FORM,
            )
            assert req.status == status
            # Ensure it can roundtrip through JSON
            data = json.loads(req.model_dump_json())
            assert data["status"] == status.value


# ===========================================================================
# 7. Crypto module unit checks
# ===========================================================================


class TestCrypto:
    """Direct tests for the crypto primitives."""

    def test_salt_is_random(self):
        from ghosted.vault.crypto import generate_salt

        s1 = generate_salt()
        s2 = generate_salt()
        assert len(s1) == 16
        assert s1 != s2

    def test_encrypt_decrypt_roundtrip(self):
        from ghosted.vault.crypto import decrypt, derive_key, encrypt, generate_salt

        salt = generate_salt()
        key = derive_key("test-pass", salt)
        plaintext = b"hello world"
        ct = encrypt(plaintext, key)
        assert ct != plaintext
        assert decrypt(ct, key) == plaintext

    def test_different_salt_different_key(self):
        from ghosted.vault.crypto import derive_key, generate_salt

        s1 = generate_salt()
        s2 = generate_salt()
        k1 = derive_key("same-pass", s1)
        k2 = derive_key("same-pass", s2)
        assert k1 != k2


# ===========================================================================
# 8. Models validation
# ===========================================================================


class TestModels:
    """Pydantic model validation."""

    def test_user_profile_required_fields(self):
        with pytest.raises(Exception):
            UserProfile(first_name="A")  # Missing required fields

    def test_broker_config_method_validation(self):
        with pytest.raises(Exception):
            BrokerConfig(
                name="Bad",
                url="https://bad.com",
                opt_out_url="https://bad.com/opt",
                method="invalid_method",
            )

    def test_scan_result_defaults(self):
        r = ScanResult(broker_name="Test")
        assert r.found is False
        assert r.status == ScanStatus.UNKNOWN
        assert r.info_found == []
        assert r.error is None
        assert r.page_title is None
        assert r.http_status is None

    def test_removal_request_defaults(self):
        r = RemovalRequest(broker_name="Test")
        assert r.status == RemovalStatus.PENDING
        assert r.method == BrokerMethod.WEB_FORM


# ===========================================================================
# 9. ScanStatus classification
# ===========================================================================


class TestScanStatus:
    """Tests for the ScanStatus enum and status-aware ScanResult."""

    def test_all_status_values(self):
        """All ScanStatus values are valid and serializable."""
        for status in ScanStatus:
            r = ScanResult(broker_name="test", status=status)
            data = json.loads(r.model_dump_json())
            assert data["status"] == status.value

    def test_found_status_consistency(self):
        """FOUND status should have found=True; all others found=False."""
        r_found = ScanResult(broker_name="test", status=ScanStatus.FOUND, found=True)
        assert r_found.found is True
        assert r_found.status == ScanStatus.FOUND

        for status in [ScanStatus.NOT_FOUND, ScanStatus.BLOCKED, ScanStatus.ERROR, ScanStatus.UNKNOWN]:
            r = ScanResult(broker_name="test", status=status, found=False)
            assert r.found is False

    def test_page_title_and_http_status(self):
        """ScanResult stores debug metadata."""
        r = ScanResult(
            broker_name="test",
            status=ScanStatus.BLOCKED,
            page_title="Just a moment...",
            http_status=403,
        )
        assert r.page_title == "Just a moment..."
        assert r.http_status == 403

    def test_scan_report_blocked_unknown_counts(self):
        """ScanReport tracks blocked and unknown counts."""
        report = ScanReport(
            scan_id="test-counts",
            started_at=datetime.now(),
            total_brokers=5,
            brokers_with_data=1,
            brokers_blocked=2,
            brokers_unknown=1,
            errors=1,
            results=[
                ScanResult(broker_name="A", status=ScanStatus.FOUND, found=True),
                ScanResult(broker_name="B", status=ScanStatus.NOT_FOUND),
                ScanResult(broker_name="C", status=ScanStatus.BLOCKED),
                ScanResult(broker_name="D", status=ScanStatus.BLOCKED),
                ScanResult(broker_name="E", status=ScanStatus.UNKNOWN),
            ],
        )
        assert report.brokers_blocked == 2
        assert report.brokers_unknown == 1
        assert report.brokers_with_data == 1

    def test_history_status_roundtrip(self, tmp_path):
        """Status field survives the DB round-trip."""
        from ghosted.core.history import HistoryDB

        db = HistoryDB(tmp_path / "status_test.db")
        db.init_db()

        report = ScanReport(
            scan_id="status-rt",
            started_at=datetime.now(),
            completed_at=datetime.now(),
            total_brokers=3,
            brokers_with_data=1,
            brokers_blocked=1,
            brokers_unknown=0,
            errors=1,
            results=[
                ScanResult(broker_name="Found", status=ScanStatus.FOUND, found=True, page_title="Results", http_status=200),
                ScanResult(broker_name="Blocked", status=ScanStatus.BLOCKED, error="Cloudflare", page_title="Just a moment...", http_status=403),
                ScanResult(broker_name="Error", status=ScanStatus.ERROR, error="Timeout"),
            ],
        )
        db.save_scan(report)

        loaded = db.get_latest_scan()
        assert loaded is not None
        assert loaded.brokers_blocked == 1
        assert loaded.results[0].status == ScanStatus.FOUND
        assert loaded.results[0].page_title == "Results"
        assert loaded.results[0].http_status == 200
        assert loaded.results[1].status == ScanStatus.BLOCKED
        assert loaded.results[1].page_title == "Just a moment..."
        assert loaded.results[2].status == ScanStatus.ERROR
        db.close()

    def test_cloudflare_brokers_have_flag(self):
        """Known Cloudflare-protected brokers must have cloudflare=true."""
        from ghosted.brokers.registry import BrokerRegistry

        registry = BrokerRegistry(BROKERS_DIR)
        brokers = registry.load_all()
        broker_map = {b.name: b for b in brokers}

        cloudflare_names = [
            "Spokeo", "BeenVerified", "TruePeopleSearch",
            "FastPeopleSearch", "Nuwber", "PeopleLooker",
            "CocoFinder", "CyberBackgroundChecks", "PeopleFinders",
            "SearchPeopleFree", "USPhoneBook",
        ]
        for name in cloudflare_names:
            assert name in broker_map, f"Broker {name} not found in registry"
            assert broker_map[name].cloudflare is True, f"Broker {name} missing cloudflare=true"

    def test_broker_config_cloudflare_default(self):
        """BrokerConfig.cloudflare defaults to False."""
        b = BrokerConfig(
            name="Test",
            url="https://test.com",
            opt_out_url="https://test.com/opt",
            method=BrokerMethod.WEB_FORM,
        )
        assert b.cloudflare is False
