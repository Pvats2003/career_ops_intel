# Preferences

Structured, machine-consumed preferences live in `config/preferences.yaml`
and `config/profile.yaml` (target roles, location, salary, visa/work
authorization). This file is a human-readable pointer, not a duplicate
source of truth, so the two never drift apart.

Current state (2026-08-27): most preference fields are `UNKNOWN` because
the resume does not state them and the candidate has not yet filled them
into `config/preferences.yaml`. Per `config/rules.yaml`, any application
question touching an `UNKNOWN` field (salary, visa/sponsorship, relocation,
notice period) must be routed to `HUMAN_REVIEW_REQUIRED` — never guessed.

Action needed from the candidate before Level 4 (auto-submit) automation is
safe to enable: fill in `config/preferences.yaml` (`salary_preferences`,
`visa_information`, `work_preferences.willing_to_relocate`, etc.).
