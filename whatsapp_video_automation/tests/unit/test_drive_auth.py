"""Regression tests for `GoogleAuthService`'s token-encryption-at-rest and
its silent-vs-interactive sign-in split.

Verifies the plaintext-on-disk gap is actually closed (not just that the
crypto primitive works in isolation) and that a normal
persist -> restart -> reload cycle still functions end to end.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from instacore_sync.core.exceptions import DriveAuthError
from instacore_sync.domain.enums import GoogleAuthStatus
from instacore_sync.services.drive import drive_auth as drive_auth_module
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


def test_non_interactive_get_credentials_never_launches_browser_flow_when_signed_out(
    tmp_path: Path, monkeypatch
) -> None:
    """Regression test for a real startup-hang bug: with no stored token at
    all (first run, or after sign-out), the default (non-interactive) path
    must fail fast with DriveAuthError instead of opening a browser and
    blocking — this call happens inside PipelineOrchestrator.start(),
    awaited before the folder watcher or upload pool ever start, so a
    silent interactive flow here would hang the entire pipeline for any
    of 500 installs that haven't signed in yet."""
    (tmp_path / "credentials.json").write_text("{}")  # exists, so this isn't the "missing file" path
    service = GoogleAuthService(tmp_path / "credentials.json", tmp_path / "token.json")

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("run_local_server must never be invoked without interactive=True")

    monkeypatch.setattr(
        drive_auth_module.InstalledAppFlow,
        "from_client_secrets_file",
        lambda *a, **kw: type("FakeFlow", (), {"run_local_server": _must_not_be_called})(),
    )

    with pytest.raises(DriveAuthError):
        service.get_credentials(interactive=False)
    assert service.status == GoogleAuthStatus.SIGNED_OUT


def test_interactive_get_credentials_runs_the_consent_flow_when_signed_out(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "credentials.json").write_text("{}")
    token_path = tmp_path / "token.json"
    service = GoogleAuthService(tmp_path / "credentials.json", token_path)

    fake_creds = _fake_credentials()

    class _FakeFlow:
        def run_local_server(self, port: int = 0):
            return fake_creds

    monkeypatch.setattr(
        drive_auth_module.InstalledAppFlow, "from_client_secrets_file", lambda *a, **kw: _FakeFlow()
    )

    result = service.get_credentials(interactive=True)

    assert result is fake_creds
    assert service.status == GoogleAuthStatus.AUTHENTICATED
    assert token_path.exists()  # persisted for next time


def test_non_interactive_silent_refresh_succeeds_without_ever_needing_interactive(
    tmp_path: Path, monkeypatch
) -> None:
    """An expired-but-refreshable token must never need the interactive
    flag at all — only a *dead* token (no refresh token, or refresh
    itself fails) should ever require it."""
    token_path = tmp_path / "token.json"
    service = GoogleAuthService(tmp_path / "credentials.json", token_path)

    refreshed = _fake_credentials(token="new-access-token")
    stale = MagicMock()
    stale.valid = False
    stale.expired = True
    stale.refresh_token = "refresh-token-secret"

    def _refresh(request):
        stale.valid = True

    stale.refresh.side_effect = _refresh
    stale.to_json.return_value = refreshed.to_json.return_value
    monkeypatch.setattr(service, "_load_encrypted_token", lambda: stale)

    def _flow_must_not_be_built(*a, **kw):
        raise AssertionError("interactive flow must not be constructed for a refreshable token")

    monkeypatch.setattr(drive_auth_module.InstalledAppFlow, "from_client_secrets_file", _flow_must_not_be_built)

    # _load_or_authenticate only calls _load_encrypted_token when the
    # token file exists on disk.
    token_path.write_bytes(b"placeholder-ciphertext")

    result = service.get_credentials(interactive=False)

    assert result is stale
    assert service.status == GoogleAuthStatus.AUTHENTICATED
