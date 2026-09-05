"""FastAPI application factory for the Career OS web dashboard.

`create_app()` (not a module-level `app` built from unvalidated global
state) so tests can construct a fresh app after `monkeypatch.setenv(...)`,
exactly like `job_agent.cli.main`'s Typer `app` is exercised per-test with
patched environment — see `tests/unit/test_web_api.py`.
"""

from __future__ import annotations

import base64
import binascii
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from job_agent.config.loader import load_config
from job_agent.diagnostics import get_health_status
from job_agent.logging.setup import redact_text
from job_agent.web.routers import (
    candidate,
    companies,
    dashboard,
    jobs,
    notifications,
    pipeline,
    settings,
    sources,
    watchlist,
)

_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "web-ui" / "dist"

# Exempt from the access gate below even when APP_USERNAME/APP_PASSWORD are
# set: a cloud platform's own health probe (Render/Railway/Fly.io) hits this
# path with no credentials at all, on a fixed schedule, to decide whether to
# keep the instance running — gating it would make the deployment platform
# itself repeatedly kill a perfectly healthy service.
_HEALTH_PATH = "/api/health"


def _request_is_authorized(request: Request, *, username: str, password: str) -> bool:
    header = request.headers.get("authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    supplied_username, sep, supplied_password = decoded.partition(":")
    if not sep:
        return False
    return secrets.compare_digest(supplied_username, username) and secrets.compare_digest(
        supplied_password, password
    )


def create_app() -> FastAPI:
    app = FastAPI(title="Career OS", description="AI-powered job intelligence dashboard")

    # Local-only dev server; the Vite dev server runs on a different port
    # during development. Not a public-facing service (BUILD PROMPT
    # section 26) — CORS is opened only for localhost.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _require_app_credentials_if_configured(request: Request, call_next):
        """No-op locally (APP_USERNAME/APP_PASSWORD unset by default — see
        EnvSettings), so today's localhost dev experience is unchanged.
        Once a candidate sets both for a public deployment, every request
        except the platform health check must present matching HTTP Basic
        credentials — this is a single-candidate personal dashboard
        (real name, resume, salary expectations, application history) and
        must never be reachable by an anonymous visitor of its public URL."""
        if request.url.path != _HEALTH_PATH:
            cfg = load_config()
            username, password = cfg.env.app_username, cfg.env.app_password
            if username and password and not _request_is_authorized(
                request, username=username, password=password
            ):
                return Response(
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="Career OS"'},
                )
        return await call_next(request)

    app.include_router(dashboard.router)
    app.include_router(candidate.router)
    app.include_router(jobs.router)
    app.include_router(pipeline.router)
    app.include_router(companies.router)
    app.include_router(watchlist.router)
    app.include_router(notifications.router)
    app.include_router(settings.router)
    app.include_router(sources.router)

    @app.get("/api/health")
    def health() -> dict:
        """Deployment health check — application running, database
        connected, migrations current, scheduler availability, job-source
        configuration status, and LLM configuration status. Never
        includes a `database_url`, API key, or any other credential;
        exempt from the access-gate middleware above (see `_HEALTH_PATH`)
        since a deployment platform's own health probe never authenticates.
        """
        try:
            cfg = load_config()
        except Exception as exc:  # noqa: BLE001
            return {"status": "config_error", "detail": redact_text(str(exc))}
        return get_health_status(cfg)

    # Serve the built frontend (if present) so `job-agent serve` alone is
    # enough in a non-dev setting — `npm run build` writes to web-ui/dist.
    # Falls back to API-only if the frontend hasn't been built yet.
    if _FRONTEND_DIST.exists():
        # Vite's hashed bundle output (JS/CSS) lives under dist/assets/ —
        # mounted directly rather than through the catch-all below so the
        # browser's cache-busting hashed filenames are served as real
        # static files, not re-processed by the SPA-fallback route.
        app.mount(
            "/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets"
        )

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str) -> FileResponse:
            """React Router uses client-side (`BrowserRouter`) routing, so
            a direct navigation or a page refresh on e.g. `/pipeline` or
            `/jobs/5` is a real GET this server receives, not something
            the SPA's own JS handles — without this, every route except
            `/` itself 404s the instant a user reloads or bookmarks it.
            Serves a real file under dist/ verbatim if the path matches
            one (favicon, manifest, etc.); otherwise falls back to
            index.html and lets the client-side router take over. Never
            intercepts `/api/*` — those 404 as real API 404s, never as
            the frontend shell."""
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found.")
            candidate_path = (_FRONTEND_DIST / full_path).resolve()
            if (
                full_path
                and candidate_path.is_file()
                and _FRONTEND_DIST in candidate_path.parents
            ):
                return FileResponse(candidate_path)
            return FileResponse(_FRONTEND_DIST / "index.html")

    return app


app = create_app()
