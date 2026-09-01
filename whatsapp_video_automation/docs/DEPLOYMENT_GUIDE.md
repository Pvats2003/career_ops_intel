# Deployment Guide

How to go from "this repository" to "InstaCore Sync running on your
team's machines." This is the map; each linked document covers one part
in depth.

## Decide your deployment shape first

**A. One person, their own machine.** Just follow
[`INSTALLATION_GUIDE.md`](INSTALLATION_GUIDE.md) and
[`QUICK_START.md`](QUICK_START.md). Nothing else in this document
applies to you.

**B. A team, each with their own Google Drive folder/Sheet.** Also just
per-machine installs — each person's install is fully independent, no
extra coordination needed. Still follow A above, once per person.

**C. A team sharing one Google Drive folder and Sheet** (the common
"everyone uploads to the same team tracker" setup). This is the scenario
the rest of this guide, and [`DEPLOYMENT_AT_SCALE.md`](DEPLOYMENT_AT_SCALE.md)
in full, is written for — read on.

## Deploying shape C

### 1. Build the installer

[`PACKAGING.md`](PACKAGING.md) — produces
`InstaCoreSync-Setup-<version>.exe`.

### 2. Set up the shared Google side *before* rolling out to anyone

- Create the OAuth client (`credentials.json`) —
  [`GOOGLE_API_SETUP.md`](GOOGLE_API_SETUP.md).
- **Resolve the OAuth verification question now.** If your team is all
  in one Google Workspace organization, publish the consent screen as
  **Internal** in Google Cloud Console — this is the fast path and
  avoids Google's 100-test-user cap entirely. If not, read
  [`DEPLOYMENT_AT_SCALE.md`](DEPLOYMENT_AT_SCALE.md#the-blocker-you-cannot-code-your-way-around-oauth-verification)
  for the slower alternative. Getting this wrong doesn't fail loudly
  until your 101st team member tries to sign in and can't — resolve it
  before rollout, not after.
- Create a **Shared Drive** (not a folder in someone's personal My
  Drive) as the upload destination, and a Sheet if you want centralized
  logging. Share both with everyone who'll run InstaCore Sync.

### 3. Distribute

See [`ADMIN_GUIDE.md`](ADMIN_GUIDE.md#rolling-out-to-a-team) — there's no
auto-updater, so plan for how you'll redistribute future versions too,
not just the first install.

### 4. What's already handled for you

The application itself is built to be safe under this exact scenario —
many independent installs writing into one shared destination at once:
new Sheet rows can't collide, Drive folder-creation races self-heal, and
a video forwarded to several team members is only ever uploaded once
even though each person's local duplicate-check has no way to know what
someone else's machine already uploaded. The mechanisms and their exact
guarantees (and residual limits) are documented in
[`DEPLOYMENT_AT_SCALE.md`](DEPLOYMENT_AT_SCALE.md#what-the-code-now-guarantees-under-concurrent-writers) —
worth reading once, not because you need to configure any of it, but so
you know what's actually being promised.

### 5. Ongoing operations

[`ADMIN_GUIDE.md`](ADMIN_GUIDE.md) — monitoring, backups, updates,
decommissioning.

## Full technical reference

[`DEPLOYMENT_AT_SCALE.md`](DEPLOYMENT_AT_SCALE.md) is the complete
write-up of the shared-destination architecture: what's guaranteed, the
OAuth verification blocker in full, Shared Drive vs. My Drive, API quota
considerations, and what's explicitly out of scope for this release (no
auto-updater, no fleet-wide diagnostics/telemetry).
