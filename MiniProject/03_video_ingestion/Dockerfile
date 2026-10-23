# syntax=docker/dockerfile:1
# Build context: MiniProject, with native 02 (#18) and 04 (#20) dependencies.
FROM ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff AS uv
FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 AS build
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never MINIPROJECT_ROOT=/app
WORKDIR /app
COPY 02_api_backend/pyproject.toml ./02_api_backend/
COPY 04_rag_knowledge/pyproject.toml ./04_rag_knowledge/
COPY 03_video_ingestion/pyproject.toml 03_video_ingestion/uv.lock ./03_video_ingestion/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --project 03_video_ingestion --locked --no-install-local --no-dev
COPY 02_api_backend/src ./02_api_backend/src
COPY 04_rag_knowledge/src ./04_rag_knowledge/src
COPY 03_video_ingestion/src ./03_video_ingestion/src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --project 03_video_ingestion --locked --no-editable --no-dev

FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 AS runtime
ENV PATH="/app/03_video_ingestion/.venv/bin:$PATH" MINIPROJECT_ROOT=/app PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 AUTH_ENABLED=true ADAPTER_MODE=custom ADAPTER_FACTORY=youtube_ingestion.member_adapters:create_member_adapters BACKEND_INTEGRATION_PROFILE=live
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app \
    && mkdir -p /app/runtime && chown app:app /app/runtime
COPY --from=build /app/03_video_ingestion/.venv /app/03_video_ingestion/.venv
WORKDIR /app
USER 10001:10001
EXPOSE 8000
CMD ["yk-api"]
