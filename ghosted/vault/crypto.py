"""Cryptographic primitives for the encrypted vault."""

import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import base64


def generate_salt() -> bytes:
    """Generate a 16-byte random salt."""
    return os.urandom(16)


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive an encryption key from a passphrase using PBKDF2-SHA256.

    Uses 480,000 iterations as recommended by OWASP for PBKDF2-SHA256.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    raw_key = kdf.derive(passphrase.encode("utf-8"))
    return base64.urlsafe_b64encode(raw_key)


def encrypt(data: bytes, key: bytes) -> bytes:
    """Encrypt data using Fernet symmetric encryption."""
    f = Fernet(key)
    return f.encrypt(data)


def decrypt(data: bytes, key: bytes) -> bytes:
    """Decrypt data using Fernet symmetric encryption."""
    f = Fernet(key)
    return f.decrypt(data)
