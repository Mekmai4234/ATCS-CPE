# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff AS uv
FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 AS test
COPY --from=uv /uv /usr/local/bin/
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MINIPROJECT_ROOT=/app \
    ANONYMIZED_TELEMETRY=False \
    RUFF_CACHE_DIR=/tmp/ruff-cache
WORKDIR /app/04_rag_knowledge
COPY 02_api_backend/pyproject.toml /app/02_api_backend/pyproject.toml
COPY 02_api_backend/src /app/02_api_backend/src
COPY 04_rag_knowledge/pyproject.toml 04_rag_knowledge/uv.lock ./
COPY 04_rag_knowledge/src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
ENV PATH="/app/04_rag_knowledge/.venv/bin:$PATH"
COPY 04_rag_knowledge/tests ./tests
COPY 04_rag_knowledge/fixtures ./fixtures
COPY 04_rag_knowledge/scripts ./scripts
RUN groupadd --gid 10001 rag \
    && useradd --uid 10001 --gid rag --no-create-home rag \
    && mkdir -p /data /app/runtime \
    && chown -R rag:rag /data /app/runtime
ENV APP_ENV=test
USER 10001:10001
CMD ["pytest", "tests", "-q", "-o", "cache_dir=/tmp/pytest-cache"]
