# Career OS — single-container cloud deployment.
#
# Two stages: build the React frontend, then run the one FastAPI process
# that serves both the API and the built frontend, and (unless disabled)
# the in-process autonomous scheduler — see `job_agent.cli.main:serve`.
# There is no separate frontend server and no separate worker process;
# this container IS the whole deployment.

FROM node:20-slim AS frontend-builder

WORKDIR /app/web-ui
COPY web-ui/package.json web-ui/package-lock.json ./
RUN npm ci
COPY web-ui/ ./
RUN npm run build

FROM python:3.11-slim AS runtime

WORKDIR /app

# pyproject.toml first so dependency install is cached across rebuilds
# that only change application code.
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY config/ ./config/
COPY candidate/ ./candidate/

COPY --from=frontend-builder /app/web-ui/dist ./web-ui/dist

# Render/Railway/Fly.io all inject PORT at runtime; 8000 is only the
# fallback for `docker run` without -e PORT set.
ENV PORT=8000
EXPOSE 8000

# `job-agent serve` brings the database schema up to date (Alembic) before
# it starts accepting requests, then serves the API, the built frontend,
# and the autonomous scheduler from this one process. Binding 0.0.0.0
# (not 127.0.0.1) is required for the platform's load balancer/proxy to
# reach the container at all.
CMD ["sh", "-c", "job-agent serve --host 0.0.0.0 --port ${PORT}"]
