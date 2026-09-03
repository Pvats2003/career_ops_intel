"""Career OS web dashboard — a FastAPI layer over the existing `job_agent`
services (candidate parsing, job discovery, matching, resume versioning,
the application pipeline). This package adds NO new business logic beyond
what the CLI (`job_agent.cli.main`) already exercises; every route calls
straight into the same `job_agent.*.service`/`repository` modules the CLI
commands use, so the two front ends (CLI and web) can never silently
diverge in what "matching", "scanning", or "saving a job" actually means.

Recruiting-pipeline tracking (save/shortlist/kanban) reuses the existing
`Application` row and its new `pipeline_stage` column (see `job_agent.db.
models.Application`'s docstring) — it never touches `Application.status`
or the safety-gated automation state machine in `job_agent.applications.
state_machine`/`service`, which remain exactly as built.
"""
