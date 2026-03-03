"""Encrypted vault for storing user profile data."""

import os
import shutil
from pathlib import Path

from ghosted.models import UserProfile
from ghosted.vault.crypto import decrypt, derive_key, encrypt, generate_salt


class VaultStore:
    """Manages encrypted storage of user profile data.

    Stores an encrypted profile at ~/.ghosted/profiles/<name>/vault.enc
    with the salt kept separately.
    """

    def __init__(self, vault_dir: Path | None = None, profile_name: str = "default"):
        base = vault_dir or Path.home() / ".ghosted"
        self.base_dir = base
        self.profile_name = profile_name
        self.vault_dir = base / "profiles" / profile_name
        self.vault_file = self.vault_dir / "vault.enc"
        self.salt_file = self.vault_dir / "salt"
        # Auto-migrate legacy vault if this is the default profile
        if profile_name == "default" and not self.vault_file.exists():
            self._migrate_legacy()

    def _migrate_legacy(self) -> None:
        """Move a legacy flat vault (~/.ghosted/vault.enc) into profiles/default/."""
        legacy_vault = self.base_dir / "vault.enc"
        legacy_salt = self.base_dir / "salt"
        legacy_history = self.base_dir / "scan_history.db"
        if legacy_vault.exists() and legacy_salt.exists():
            self.vault_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self.vault_dir, 0o700)
            shutil.move(str(legacy_vault), str(self.vault_file))
            shutil.move(str(legacy_salt), str(self.salt_file))
            # Also migrate the history DB if it exists at the old flat path
            if legacy_history.exists():
                new_history = self.vault_dir / "scan_history.db"
                shutil.move(str(legacy_history), str(new_history))

    @classmethod
    def list_profiles(cls, vault_dir: Path | None = None) -> list[str]:
        """Return names of all existing profiles."""
        base = vault_dir or Path.home() / ".ghosted"
        # Trigger migration for default profile before listing
        cls(vault_dir=base, profile_name="default")
        profiles_dir = base / "profiles"
        if not profiles_dir.exists():
            return []
        return sorted(
            d.name for d in profiles_dir.iterdir()
            if d.is_dir() and (d / "vault.enc").exists()
        )

    def exists(self) -> bool:
        """Check if a vault already exists."""
        return self.vault_file.exists() and self.salt_file.exists()

    def create(self, profile: UserProfile, passphrase: str) -> None:
        """Encrypt and save a user profile to the vault.

        Creates the vault directory if it doesn't exist.
        Overwrites any existing vault.
        """
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.vault_dir, 0o700)

        salt = generate_salt()
        key = derive_key(passphrase, salt)

        profile_json = profile.model_dump_json().encode("utf-8")
        encrypted = encrypt(profile_json, key)

        self.salt_file.write_bytes(salt)
        os.chmod(self.salt_file, 0o600)
        self.vault_file.write_bytes(encrypted)
        os.chmod(self.vault_file, 0o600)

    def load(self, passphrase: str) -> UserProfile:
        """Decrypt and return the stored user profile.

        Raises FileNotFoundError if vault doesn't exist.
        Raises cryptography.fernet.InvalidToken if passphrase is wrong.
        """
        if not self.exists():
            raise FileNotFoundError("No vault found. Run 'ghosted vault create' first.")

        salt = self.salt_file.read_bytes()
        key = derive_key(passphrase, salt)

        encrypted = self.vault_file.read_bytes()
        decrypted = decrypt(encrypted, key)

        return UserProfile.model_validate_json(decrypted)

    def destroy(self) -> None:
        """Securely delete vault files by overwriting before removal."""
        for path in (self.vault_file, self.salt_file):
            if path.exists():
                # Overwrite with random data before unlinking
                size = path.stat().st_size
                path.write_bytes(b"\x00" * size)
                path.unlink()
