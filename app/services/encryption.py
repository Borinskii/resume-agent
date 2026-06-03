from __future__ import annotations

import os
import stat
from pathlib import Path


class EncryptionService:
    """Wrap Fernet with on-disk key persistence.

    Why: Rule 14 requires CV content to be encrypted at rest, not just
    relying on filesystem permissions.
    """

    def __init__(self, key_path: Path) -> None:
        self._key_path = key_path
        self._cached_fernet = None

    def _load(self):
        if self._cached_fernet is not None:
            return self._cached_fernet
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:  # noqa: BLE001
            raise RuntimeError(
                "cryptography is required for CV encryption. Install with: pip install cryptography"
            ) from exc

        env_key = os.environ.get("CV_ENCRYPTION_KEY", "").strip()
        if env_key:
            key = env_key.encode("utf-8")
        elif self._key_path.exists():
            key = self._key_path.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            self._key_path.parent.mkdir(parents=True, exist_ok=True)
            self._key_path.write_bytes(key)
            try:
                os.chmod(self._key_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass

        self._cached_fernet = Fernet(key)
        return self._cached_fernet

    def encrypt(self, value: str) -> bytes:
        if not value:
            return b""
        return self._load().encrypt(value.encode("utf-8"))

    def decrypt(self, value: bytes) -> str:
        if not value:
            return ""
        return self._load().decrypt(value).decode("utf-8")

    def encrypt_bytes(self, data: bytes) -> bytes:
        if not data:
            return b""
        return self._load().encrypt(data)

    def decrypt_bytes(self, token: bytes) -> bytes:
        if not token:
            return b""
        return self._load().decrypt(token)
