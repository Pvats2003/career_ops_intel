"""Google OAuth2 (installed-app flow) for Drive + Sheets access.

Credentials are cached to `token.json` (per settings), **encrypted at
rest** (see `token_crypto.py`), so the user only goes through the browser
consent screen once; subsequent runs silently decrypt and refresh the
access token. See docs/GOOGLE_API_SETUP.md for how to obtain
`credentials.json` from Google Cloud Console.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from instacore_sync.core.constants import GOOGLE_DRIVE_SCOPES
from instacore_sync.core.exceptions import DriveAuthError
from instacore_sync.core.logging_setup import get_logger
from instacore_sync.domain.enums import GoogleAuthStatus
from instacore_sync.services.drive.token_crypto import CredentialProtector

logger = get_logger(__name__)


class GoogleAuthService:
    """Owns the OAuth credential lifecycle for the whole app (Drive + Sheets share it)."""

    def __init__(self, credentials_file: Path, token_file: Path) -> None:
        self._credentials_file = credentials_file
        self._token_file = token_file
        self._protector = CredentialProtector(token_file.with_suffix(".key"))
        self._credentials: Credentials | None = None
        self._status = GoogleAuthStatus.SIGNED_OUT
        self._lock = threading.Lock()
        self._account_email: str | None = None

    @property
    def status(self) -> GoogleAuthStatus:
        return self._status

    @property
    def account_email(self) -> str | None:
        return self._account_email

    def get_credentials(self) -> Credentials:
        with self._lock:
            if self._credentials and self._credentials.valid:
                return self._credentials
            self._credentials = self._load_or_authenticate()
            return self._credentials

    def sign_out(self) -> None:
        with self._lock:
            self._credentials = None
            self._status = GoogleAuthStatus.SIGNED_OUT
            self._account_email = None
            if self._token_file.exists():
                self._token_file.unlink()
            key_file = self._protector.key_file
            if key_file.exists():
                key_file.unlink()

    def _load_or_authenticate(self) -> Credentials:
        self._status = GoogleAuthStatus.AUTHENTICATING
        creds: Credentials | None = None

        if self._token_file.exists():
            creds = self._load_encrypted_token()

        if creds and creds.valid:
            self._status = GoogleAuthStatus.AUTHENTICATED
            return creds

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._persist(creds)
                self._status = GoogleAuthStatus.AUTHENTICATED
                return creds
            except RefreshError as exc:
                logger.warning("drive_auth.refresh_failed", error=str(exc))
                self._status = GoogleAuthStatus.EXPIRED

        if not self._credentials_file.exists():
            self._status = GoogleAuthStatus.ERROR
            raise DriveAuthError(
                f"Missing OAuth client secret file: {self._credentials_file}. "
                "See docs/GOOGLE_API_SETUP.md."
            )

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self._credentials_file), GOOGLE_DRIVE_SCOPES
            )
            creds = flow.run_local_server(port=0)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI as auth error
            self._status = GoogleAuthStatus.ERROR
            raise DriveAuthError(f"Google sign-in failed: {exc}") from exc

        self._persist(creds)
        self._status = GoogleAuthStatus.AUTHENTICATED
        return creds

    def _load_encrypted_token(self) -> Credentials | None:
        try:
            ciphertext = self._token_file.read_bytes()
            plaintext = self._protector.decrypt(ciphertext)
            info = json.loads(plaintext)
            return Credentials.from_authorized_user_info(info, GOOGLE_DRIVE_SCOPES)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            logger.warning("drive_auth.token_load_failed", error=str(exc))
            return None
        except Exception as exc:  # noqa: BLE001 - backend-specific decrypt errors (DPAPI/Fernet)
            logger.warning("drive_auth.token_decrypt_failed", error=str(exc))
            return None

    def _persist(self, creds: Credentials) -> None:
        self._token_file.parent.mkdir(parents=True, exist_ok=True)
        plaintext = creds.to_json().encode("utf-8")
        ciphertext = self._protector.encrypt(plaintext)
        self._token_file.write_bytes(ciphertext)
        logger.info("drive_auth.token_persisted", backend=self._protector.backend)
