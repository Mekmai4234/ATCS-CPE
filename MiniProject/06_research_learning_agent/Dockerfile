# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff AS uv
FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 AS tests
COPY --from=uv /uv /usr/local/bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 MINIPROJECT_ROOT=/app ANONYMIZED_TELEMETRY=False \
    RUFF_CACHE_DIR=/tmp/ruff-cache
WORKDIR /app/06_research_learning_agent
COPY 02_api_backend/pyproject.toml /app/02_api_backend/pyproject.toml
COPY 02_api_backend/src /app/02_api_backend/src
COPY 04_rag_knowledge/pyproject.toml /app/04_rag_knowledge/pyproject.toml
COPY 04_rag_knowledge/src /app/04_rag_knowledge/src
COPY 05_ai_answers_analysis/pyproject.toml /app/05_ai_answers_analysis/pyproject.toml
COPY 05_ai_answers_analysis/src /app/05_ai_answers_analysis/src
COPY 06_research_learning_agent/pyproject.toml 06_research_learning_agent/uv.lock ./
COPY 06_research_learning_agent/src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
ENV PATH="/app/06_research_learning_agent/.venv/bin:$PATH"
COPY 06_research_learning_agent/tests ./tests
COPY 06_research_learning_agent/fixtures ./fixtures
RUN groupadd --gid 10001 agent \
    && useradd --uid 10001 --gid agent --no-create-home agent
USER 10001:10001
CMD ["pytest", "tests", "-q", "-o", "cache_dir=/tmp/pytest-cache"]
