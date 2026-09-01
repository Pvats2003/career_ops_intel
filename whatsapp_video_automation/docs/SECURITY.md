# Security Notes

This document covers what InstaCore Sync does to protect the credentials
and data it handles, and — just as importantly — what it does **not**
protect against, so that's a known, documented tradeoff rather than a
silent gap.

## Credentials at rest

**OAuth token (`config/token.json`)** — the long-lived Google refresh token
is encrypted before it ever touches disk (see
`src/instacore_sync/services/drive/token_crypto.py`):

- On Windows, via **DPAPI** (`win32crypt.CryptProtectData`) — the same OS
  mechanism Chrome and Windows Credential Manager use. The encryption key
  is derived from the logged-in Windows user's credentials and never
  leaves the OS; there is no key file for an attacker to steal separately
  from the encrypted blob itself.
- On non-Windows (development, CI), via **Fernet** (AES-128-CBC +
  HMAC-SHA256, from the `cryptography` package) with a locally generated
  key file (`token.key`, next to `token.json`) restricted to the owner's
  read/write permission (`chmod 600`) on POSIX filesystems.

**OAuth client secret (`config/credentials.json`)** — this file, downloaded
once from Google Cloud Console during setup (see
`docs/GOOGLE_API_SETUP.md`), identifies the *application*, not a specific
user account, and is git-ignored. It is not encrypted at rest; Google's own
guidance treats it as safe to distribute with a desktop app (it cannot by
itself authenticate as a user — see
[Google's documentation on installed-app OAuth clients](https://developers.google.com/identity/protocols/oauth2/native-app)).

**Settings backups** (Settings → Export Settings) never include
`credentials.json` or `token.json`/`token.key` — see
`AppSettings.export_backup`'s docstring. Restoring a settings backup on a
new machine requires signing in to Google again there, by design.

## Input validation

- **Device ID validation**: every Device ID that reaches a Drive folder
  name or a Google Sheets cell is checked against the configured regex
  pattern (`utils/text_sanitize.is_valid_device_id`) — including a manual
  override typed on the Needs Review screen, which is free text a human
  entered and must not be trusted implicitly. A value that fails validation
  routes the video to Needs Review with a clear reason instead of creating
  a folder or row from it.
- **Spreadsheet formula injection**: `SheetsClient.upsert_row` writes with
  Sheets' `USER_ENTERED` input option, which parses a leading `=`, `+`,
  `-`, or `@` as a formula. Since the video filename is attacker-influenced
  (it's whatever a WhatsApp group member named the file before sending
  it), every value written to a cell is passed through
  `utils/text_sanitize.sanitize_for_spreadsheet_cell`, which prefixes a
  literal-forcing `'` when needed. This is the standard, documented
  mitigation for this OWASP-recognized vulnerability class (CSV/spreadsheet
  formula injection).
- **Path traversal**: filenames are taken from `Path(...).name` at the
  point a video is discovered (`FolderWatcher`/`PipelineOrchestrator`),
  which strips any directory components before the name is used anywhere
  else — a video can't be named its way into writing outside the intended
  Processed/NeedsReview/Failed folders.

## Google API scopes

The app requests exactly two OAuth scopes (`core/constants.py`,
`GOOGLE_DRIVE_SCOPES`): `drive` (needed for folder creation, upload, and
setting link-sharing permissions — Drive's more narrow scopes don't cover
folder creation) and `spreadsheets`. It never requests broader account
access.

`drive` is a Google-designated **restricted** scope, which has real
deployment consequences once this stops being one person's own sign-in —
an unverified consent screen is capped at 100 test users, and full
external verification for a restricted scope requires a CASA security
assessment. See
[`docs/DEPLOYMENT_AT_SCALE.md`](DEPLOYMENT_AT_SCALE.md#the-blocker-you-cannot-code-your-way-around-oauth-verification)
for what this means for a team rollout and the two ways to resolve it.

## What this does **not** protect against

Being direct about the boundary matters more than the boundary itself:

- **Anyone with access to the logged-in Windows user account** can run
  InstaCore Sync itself and use its already-authenticated Drive/Sheets
  session — encryption at rest protects the token file from being *copied
  off the machine and used elsewhere*, not from local misuse under the
  same OS account. This is inherent to any desktop app using OS-level
  credential protection (DPAPI, Keychain, etc.) and is the same boundary
  Chrome/Windows Credential Manager operate under.
- **No application-level audit trail of who ran the app** — it's built for
  a single operator's machine, not a shared/multi-user deployment. Running
  it on a shared machine without separate Windows user accounts extends
  Drive/Sheets access to anyone with access to that shared session.
- **The SQLite database (`instacore_sync.db`) is not encrypted.** It
  contains filenames, Device IDs, Drive links, and OCR confidence scores —
  no credentials — but it is plaintext on disk. Full-disk encryption
  (BitLocker) is the appropriate layer for protecting this, not the
  application.
- **No rate limiting/abuse protection on the Needs Review manual-entry
  field** beyond pattern validation — this is a local single-operator
  desktop tool, not a network-facing service, so this class of protection
  (e.g. against a malicious *local* actor spamming garbage into the
  review dialog) is deliberately out of scope.

## Reporting a concern

This is an internal tool; route security concerns the same way as any
other bug — through whoever maintains this repository.
