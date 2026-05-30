"""Encrypted secrets management.

:class:`SecretsManager` encrypts sensitive values (API keys/secrets) at rest
using Fernet (AES-128-CBC + HMAC authentication). Keys can be supplied directly
or derived from a passphrase via PBKDF2-HMAC-SHA256. Encrypted blobs can be
stored to / loaded from disk so credentials never live in plaintext config.

This complements — it does not replace — a real secret store (Vault, AWS Secrets
Manager) in production; it ensures the bot never persists plaintext secrets and
can decrypt them at runtime from a single master key in the environment.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from quantbot.core.exceptions import EncryptionError
from quantbot.core.logging import get_logger

_log = get_logger(__name__)

_PBKDF2_ITERATIONS = 480_000


class SecretsManager:
    """Encrypt/decrypt secrets with a Fernet key."""

    def __init__(self, key: str | bytes) -> None:
        if isinstance(key, str):
            key = key.encode()
        try:
            self._fernet = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise EncryptionError("Invalid Fernet key") from exc

    # ------------------------------------------------------------------ key mgmt

    @staticmethod
    def generate_key() -> str:
        """Generate a new random Fernet key (store this securely)."""
        return Fernet.generate_key().decode()

    @classmethod
    def from_password(cls, password: str, salt: bytes) -> SecretsManager:
        """Derive a key from a passphrase + salt via PBKDF2 (deterministic)."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_PBKDF2_ITERATIONS
        )
        derived = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return cls(derived)

    # ------------------------------------------------------------------ encrypt

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string, returning a URL-safe token."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        """Decrypt a token produced by :meth:`encrypt`."""
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise EncryptionError("Decryption failed: invalid or tampered token") from exc

    def encrypt_dict(self, data: dict[str, str]) -> str:
        """Encrypt a mapping of secrets into a single token."""
        return self.encrypt(json.dumps(data))

    def decrypt_dict(self, token: str) -> dict[str, str]:
        """Decrypt a token produced by :meth:`encrypt_dict`."""
        return json.loads(self.decrypt(token))

    # ------------------------------------------------------------------ files

    def save_encrypted(self, data: dict[str, str], path: str | Path) -> Path:
        """Encrypt *data* and write it to *path* (mode 0600)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        token = self.encrypt_dict(data)
        path.write_text(token, encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:  # pragma: no cover - platform dependent
            pass
        _log.info("secrets_saved", path=str(path), keys=list(data))
        return path

    def load_encrypted(self, path: str | Path) -> dict[str, str]:
        """Load and decrypt a secrets file written by :meth:`save_encrypted`."""
        token = Path(path).read_text(encoding="utf-8").strip()
        return self.decrypt_dict(token)

    def rotate_key(self, new_key: str | bytes, tokens: list[str]) -> list[str]:
        """Re-encrypt *tokens* under *new_key* (key rotation)."""
        new_manager = SecretsManager(new_key)
        return [new_manager.encrypt(self.decrypt(t)) for t in tokens]


def load_secrets_manager(encryption_key: str | None) -> SecretsManager | None:
    """Build a :class:`SecretsManager` from a configured key, or ``None``."""
    if not encryption_key:
        return None
    return SecretsManager(encryption_key)


__all__ = ["SecretsManager", "load_secrets_manager"]
