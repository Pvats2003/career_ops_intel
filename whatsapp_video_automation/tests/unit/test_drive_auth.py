"""Regression tests for `GoogleAuthService`'s token-encryption-at-rest.

Verifies the plaintext-on-disk gap is actually closed (not just that the
crypto primitive works in isolation) and that a normal
persist -> restart -> reload cycle still functions end to end.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from instacore_sync.services.drive.drive_auth import GoogleAuthService


def _fake_credentials(token: str = "access-token", refresh_token: str = "refresh-token-secret"):
    creds = MagicMock()
    creds.valid = True
    creds.to_json.return_value = json.dumps(
        {
            "token": token,
            "refresh_token": refresh_token,
            "client_id": "client-123",
            "client_secret": "shh",
            "scopes": ["https://www.googleapis.com/auth/drive"],
        }
    )
    return creds


def test_persisted_token_file_never_contains_plaintext_secret(tmp_path: Path) -> None:
    service = GoogleAuthService(tmp_path / "credentials.json", tmp_path / "token.json")
    creds = _fake_credentials(refresh_token="super-secret-refresh-token")

    service._persist(creds)

    raw_bytes = (tmp_path / "token.json").read_bytes()
    assert b"super-secret-refresh-token" not in raw_bytes
    assert b"refresh_token" not in raw_bytes  # not even the JSON key name is visible


def test_persist_then_load_round_trips_via_encrypted_file(tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    service = GoogleAuthService(tmp_path / "credentials.json", token_path)
    creds = _fake_credentials()
    service._persist(creds)

    # Simulate a fresh app launch: a brand-new GoogleAuthService instance
    # pointed at the same (encrypted) token file must be able to decrypt
    # and reconstruct usable credentials from it.
    fresh_service = GoogleAuthService(tmp_path / "credentials.json", token_path)
    loaded = fresh_service._load_encrypted_token()

    assert loaded is not None
    assert loaded.token == "access-token"
    assert loaded.refresh_token == "refresh-token-secret"


def test_load_encrypted_token_returns_none_for_corrupted_file(tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_bytes(b"not a valid ciphertext at all")
    service = GoogleAuthService(tmp_path / "credentials.json", token_path)

    assert service._load_encrypted_token() is None


def test_sign_out_removes_token_and_key_files(tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    service = GoogleAuthService(tmp_path / "credentials.json", token_path)
    service._persist(_fake_credentials())
    key_path = service._protector.key_file
    assert token_path.exists()
    assert key_path.exists()

    service.sign_out()

    assert not token_path.exists()
    assert not key_path.exists()
