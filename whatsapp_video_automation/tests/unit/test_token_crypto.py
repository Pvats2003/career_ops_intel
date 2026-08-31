"""Regression tests for the token-encryption-at-rest fix.

This sandbox/CI environment is Linux, so `CredentialProtector` always
selects the Fernet fallback backend here (DPAPI is Windows-only and is
exercised manually on the shipped platform) — that's exactly the backend
every non-Windows dev/CI run needs to be correct.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from instacore_sync.services.drive.token_crypto import CredentialProtector


def test_uses_fernet_backend_on_non_windows(tmp_path: Path) -> None:
    protector = CredentialProtector(tmp_path / "token.key")
    assert protector.backend == "fernet"


def test_encrypt_then_decrypt_round_trips(tmp_path: Path) -> None:
    protector = CredentialProtector(tmp_path / "token.key")
    plaintext = b'{"refresh_token": "super-secret-value", "client_id": "abc"}'

    ciphertext = protector.encrypt(plaintext)

    assert ciphertext != plaintext
    assert b"super-secret-value" not in ciphertext  # not stored verbatim
    assert protector.decrypt(ciphertext) == plaintext


def test_key_file_is_created_and_reused(tmp_path: Path) -> None:
    key_path = tmp_path / "token.key"
    protector = CredentialProtector(key_path)

    protector.encrypt(b"first payload")
    assert key_path.exists()
    first_key = key_path.read_bytes()

    # A second instance pointed at the same key file must decrypt data
    # encrypted by the first — the key must be persisted, not regenerated
    # per-instance (which would make every previously-saved token
    # undecryptable after a restart).
    other_protector = CredentialProtector(key_path)
    ciphertext = protector.encrypt(b"second payload")
    assert other_protector.decrypt(ciphertext) == b"second payload"
    assert key_path.read_bytes() == first_key


def test_key_file_permissions_are_restricted(tmp_path: Path) -> None:
    key_path = tmp_path / "token.key"
    protector = CredentialProtector(key_path)
    protector.encrypt(b"payload")

    mode = key_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_decrypting_garbage_raises(tmp_path: Path) -> None:
    protector = CredentialProtector(tmp_path / "token.key")
    with pytest.raises(Exception):  # noqa: B017 - backend-specific (Fernet InvalidToken)
        protector.decrypt(b"not a real ciphertext")
