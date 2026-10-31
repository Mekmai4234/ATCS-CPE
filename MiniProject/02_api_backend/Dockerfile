# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff AS uv

FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 AS build
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MINIPROJECT_ROOT=/app
WORKDIR /app/02_api_backend
COPY 02_api_backend/pyproject.toml 02_api_backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY 02_api_backend/src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM build AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable
COPY 02_api_backend/tests/ ./tests/
RUN groupadd --gid 10001 backend && useradd --uid 10001 --gid backend --no-create-home backend
ENV PATH="/app/02_api_backend/.venv/bin:$PATH" \
    APP_ENV=test \
    ADAPTER_MODE=unavailable \
    RUFF_CACHE_DIR=/tmp/ruff-cache
USER 10001:10001
CMD ["pytest", "tests", "-q", "-o", "cache_dir=/tmp/pytest-cache"]

FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 AS runtime
ENV PATH="/app/02_api_backend/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MINIPROJECT_ROOT=/app \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    DATABASE_URL=sqlite:////app/runtime/app.db
RUN groupadd --gid 10001 backend \
    && useradd --uid 10001 --gid backend --no-create-home backend \
    && mkdir -p /app/runtime \
    && chown backend:backend /app/runtime
COPY --from=build /app/02_api_backend/.venv /app/02_api_backend/.venv
WORKDIR /app
USER 10001:10001
EXPOSE 8000
CMD ["yk-api"]
