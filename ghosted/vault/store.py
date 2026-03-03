"""Encrypted vault for storing user profile data."""

import os
from pathlib import Path

from ghosted.models import UserProfile
from ghosted.vault.crypto import decrypt, derive_key, encrypt, generate_salt


class VaultStore:
    """Manages encrypted storage of user profile data.

    Stores an encrypted profile at ~/.ghosted/vault.enc with the
    salt kept separately at ~/.ghosted/salt.
    """

    def __init__(self, vault_dir: Path | None = None):
        self.vault_dir = vault_dir or Path.home() / ".ghosted"
        self.vault_file = self.vault_dir / "vault.enc"
        self.salt_file = self.vault_dir / "salt"

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
