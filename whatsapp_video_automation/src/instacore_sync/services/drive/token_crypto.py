"""Encrypts the OAuth token cache at rest.

Before this, `GoogleAuthService` wrote the OAuth refresh token to
`config/token.json` as plain, unencrypted JSON. A refresh token is a
long-lived bearer credential — anyone who can read that one file (another
process running as the same Windows user, a backup that leaks, a support
screenshot, a synced folder) gets standing Drive + Sheets access to the
account until the token is manually revoked. "Never store secrets in
plaintext" is a direct, explicit requirement; this closes that gap.

On Windows (the shipped platform) this uses DPAPI via pywin32's
`win32crypt.CryptProtectData`/`CryptUnprotectData` — the same OS mechanism
Chrome and the Windows Credential Manager use to protect saved secrets. It
ties the encrypted blob to the current Windows user account with no key
file of our own to manage or lose. On non-Windows (local development, CI,
this sandbox), it falls back to Fernet symmetric encryption keyed by a
locally generated, file-permission-restricted key, so the app never writes
a plaintext token anywhere regardless of platform.

Neither backend is a substitute for full-disk encryption or a locked
screen — see docs/SECURITY.md — but both close the specific, high-severity
gap of a bare-plaintext long-lived OAuth credential sitting in a config
file.
"""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from pathlib import Path

from instacore_sync.core.logging_setup import get_logger

logger = get_logger(__name__)

_DPAPI_DESCRIPTION = "InstaCore Sync Google OAuth token"


class CredentialProtector:
    """Encrypts/decrypts small secrets (the OAuth token JSON) at rest."""

    def __init__(self, key_file: Path) -> None:
        self._key_file = key_file
        self._backend = self._select_backend()

    def _select_backend(self) -> str:
        if os.name == "nt":
            try:
                import win32crypt  # noqa: F401

                return "dpapi"
            except ImportError:
                logger.warning(
                    "token_crypto.dpapi_unavailable",
                    detail="pywin32 not installed; falling back to Fernet encryption",
                )
        return "fernet"

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def key_file(self) -> Path:
        """The local Fernet key file (unused, but harmless to check, on the DPAPI backend)."""
        return self._key_file

    def encrypt(self, plaintext: bytes) -> bytes:
        if self._backend == "dpapi":
            import win32crypt

            return bytes(win32crypt.CryptProtectData(plaintext, _DPAPI_DESCRIPTION, None, None, None, 0))
        return self._fernet().encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        if self._backend == "dpapi":
            import win32crypt

            _description, data = win32crypt.CryptUnprotectData(ciphertext, None, None, None, 0)
            return bytes(data)
        return self._fernet().decrypt(ciphertext)

    def _fernet(self):  # noqa: ANN202 - returns cryptography.fernet.Fernet
        from cryptography.fernet import Fernet

        return Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        if self._key_file.exists():
            return self._key_file.read_bytes()

        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        self._key_file.parent.mkdir(parents=True, exist_ok=True)
        self._key_file.write_bytes(key)
        self._restrict_permissions(self._key_file)
        logger.info("token_crypto.fernet_key_created", path=str(self._key_file))
        return key

    @staticmethod
    def _restrict_permissions(path: Path) -> None:
        """Best-effort: owner read/write only. On Windows this chmod call
        is a no-op in practice (NTFS ACLs, not POSIX mode bits, control
        access) — the DPAPI backend is preferred there specifically because
        it doesn't depend on file permissions at all."""
        with suppress(OSError):
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
