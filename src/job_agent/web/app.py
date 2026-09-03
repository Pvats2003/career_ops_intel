"""FastAPI application factory for the Career OS web dashboard.

`create_app()` (not a module-level `app` built from unvalidated global
state) so tests can construct a fresh app after `monkeypatch.setenv(...)`,
exactly like `job_agent.cli.main`'s Typer `app` is exercised per-test with
patched environment — see `tests/unit/test_web_api.py`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from job_agent.web.routers import candidate, dashboard, jobs, pipeline

_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "web-ui" / "dist"


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

    app.include_router(dashboard.router)
    app.include_router(candidate.router)
    app.include_router(jobs.router)
    app.include_router(pipeline.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

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
