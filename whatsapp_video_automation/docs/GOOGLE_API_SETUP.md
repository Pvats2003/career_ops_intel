# Google API Setup Guide

InstaCore Sync uses the Google Drive API (to create folders and upload
videos) and the Google Sheets API (to write the upload log row) via OAuth
2.0 "installed app" credentials — the same flow Google's own desktop sample
apps use. This guide creates the one-time `credentials.json` the app needs.

## 1. Create (or choose) a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com/).
2. Top-left project selector → **New Project**. Name it e.g. `instacore-sync`.
3. Wait for it to finish provisioning, then make sure it's selected.

## 2. Enable the two APIs

1. Left menu → **APIs & Services → Library**.
2. Search **Google Drive API** → **Enable**.
3. Search **Google Sheets API** → **Enable**.

## 3. Configure the OAuth consent screen

1. **APIs & Services → OAuth consent screen**.
2. User type: **External** (unless you have a Google Workspace org and want
   **Internal**, which skips the verification/testing-user limits below).
3. Fill in the required fields (app name `InstaCore Sync`, your email as
   support/developer contact). You don't need a logo, privacy policy, or
   homepage for a personal/internal tool.
4. **Scopes** step: click **Add or Remove Scopes** and add:
   - `https://www.googleapis.com/auth/drive`
   - `https://www.googleapis.com/auth/spreadsheets`
5. **Test users** step (External + "Testing" publish status): add the Google
   account(s) that will run InstaCore Sync. Unverified apps in Testing mode
   only allow sign-in from accounts listed here — this is fine for a single
   internal user and avoids Google's app-verification review process.

## 4. Create the OAuth client ID

1. **APIs & Services → Credentials → + Create Credentials → OAuth client ID**.
2. Application type: **Desktop app**.
3. Name it `InstaCore Sync Desktop`.
4. Click **Create**, then **Download JSON** on the resulting client.

## 5. Install the credentials file

Rename the downloaded file `credentials.json` and place it at:

```
whatsapp_video_automation/config/credentials.json
```

(or wherever `drive.credentials_file` in `config/settings.local.yaml` points
— the default is `config/credentials.json` relative to the project root).
This file is git-ignored; never commit it.

## 6. First sign-in

Run the app (`python -m instacore_sync`, or the installed `.exe`). On
startup it attempts silent auth; since no token exists yet, it opens your
default browser to the Google consent screen. Approve the two scopes
(Drive, Sheets) with the account you added as a test user. A local
`config/token.json` is then written and reused (with silent refresh) on
every subsequent launch — you should not be prompted again unless the
refresh token is revoked or expires from disuse.

If you ever need to switch Google accounts, delete `config/token.json` and
restart the app to force a fresh consent flow.

## 7. Share the Drive folder and Sheet with the signed-in account

The account you authenticated with needs **Editor** access to:

- The **Drive root folder** you set as `drive.root_folder_id` (this is where
  dated folders like `31 Aug` get created).
- The **Google Sheet** you set as `sheets.spreadsheet_id`.

If you're using a **Shared Drive** instead of a personal "My Drive" folder,
also set `drive.shared_drive_id` to the Shared Drive's ID (found in its URL:
`https://drive.google.com/drive/folders/<shared-drive-id>`), and make sure
the account is at least a **Content Manager** member of that Shared Drive.

## 8. Sheet layout expectations

InstaCore Sync writes to whatever columns you configure under
`sheets.columns` in Settings (defaults: `A`=Date, `B`=Device ID,
`C`=Filename, `D`=Drive Link, `E`=Status, `F`=Uploaded At, `G`=OCR
Confidence) on the worksheet named by `sheets.worksheet_name` (default
`Uploads`), starting one row after `sheets.header_row`. The sheet/tab must
already exist with that name — InstaCore Sync writes rows into it but does
not create new spreadsheets or tabs. Use **Settings → Google Sheets → Save**
after changing column letters; the app also has an internal
`SheetsClient.ensure_header_row()` helper that a maintainer can call once
(see `scripts/init_db.py` for the pattern) to stamp header labels.

## 9. Rotating / revoking access

To revoke InstaCore Sync's access entirely: go to
[myaccount.google.com/permissions](https://myaccount.google.com/permissions),
find "InstaCore Sync Desktop", and remove it. Then delete the local
`config/token.json` so the app doesn't try to use a dead refresh token.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Missing OAuth client secret file" error at startup | `config/credentials.json` doesn't exist at the configured path |
| Browser opens but shows "Access blocked: this app's request is invalid" | Redirect URI mismatch — re-download `credentials.json`; don't hand-edit it |
| "Access blocked: InstaCore Sync has not completed the Google verification process" | Your Google account isn't in the OAuth consent screen's **Test users** list (External + Testing mode) |
| Uploads succeed but "Anyone with the link" isn't set | Check `drive.make_public_link: true` in Settings; the signed-in account also needs permission to *share*, not just edit, the target folder |
| 403 `insufficientPermissions` on folder creation | The signed-in account lacks Editor/Content Manager access to `drive.root_folder_id` / the Shared Drive |
