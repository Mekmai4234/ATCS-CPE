# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff AS uv
FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 AS build
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 MINIPROJECT_ROOT=/app
WORKDIR /app
COPY 02_api_backend/pyproject.toml ./02_api_backend/
COPY 03_video_ingestion/pyproject.toml ./03_video_ingestion/
COPY 04_rag_knowledge/pyproject.toml ./04_rag_knowledge/
COPY 05_ai_answers_analysis/pyproject.toml ./05_ai_answers_analysis/
COPY 06_research_learning_agent/pyproject.toml ./06_research_learning_agent/
COPY 07_testing_deployment/pyproject.toml 07_testing_deployment/uv.lock ./07_testing_deployment/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --project 07_testing_deployment --locked --no-install-local
COPY 02_api_backend/src ./02_api_backend/src
COPY 03_video_ingestion/src ./03_video_ingestion/src
COPY 04_rag_knowledge/src ./04_rag_knowledge/src
COPY 05_ai_answers_analysis/src ./05_ai_answers_analysis/src
COPY 06_research_learning_agent/src ./06_research_learning_agent/src
COPY Transcript /app/Transcript
RUN --mount=type=cache,target=/root/.cache/uv uv sync --project 07_testing_deployment --locked --no-editable
RUN /app/07_testing_deployment/.venv/bin/python -m youtube_ingestion.document_cli validate --root /app/Transcript

FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 AS runtime
ENV PATH="/app/07_testing_deployment/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MINIPROJECT_ROOT=/app
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app \
    && mkdir -p /app/runtime /app/07_testing_deployment/runtime \
    && chown -R app:app /app/runtime /app/07_testing_deployment
COPY --from=build /app/07_testing_deployment/.venv /app/07_testing_deployment/.venv
COPY 07_testing_deployment/scripts /app/07_testing_deployment/scripts
COPY --from=build /app/Transcript /app/Transcript
RUN python /app/07_testing_deployment/scripts/image_source.py record
WORKDIR /app
USER 10001:10001
EXPOSE 8000
CMD ["yk-api"]

FROM runtime AS test
USER 0:0
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update -o Acquire::Retries=2 -o APT::Update::Error-Mode=any \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
USER 10001:10001
COPY --from=build /app/02_api_backend /app/02_api_backend
COPY --from=build /app/03_video_ingestion /app/03_video_ingestion
COPY --from=build /app/04_rag_knowledge /app/04_rag_knowledge
COPY --from=build /app/05_ai_answers_analysis /app/05_ai_answers_analysis
COPY --from=build /app/06_research_learning_agent /app/06_research_learning_agent
COPY 02_api_backend/tests /app/02_api_backend/tests
COPY 02_api_backend/integration/tests /app/02_api_backend/integration/tests
COPY 02_api_backend/full/tests /app/02_api_backend/full/tests
COPY 03_video_ingestion/tests /app/03_video_ingestion/tests
COPY 03_video_ingestion/scripts /app/03_video_ingestion/scripts
COPY 04_rag_knowledge/tests /app/04_rag_knowledge/tests
COPY 04_rag_knowledge/fixtures /app/04_rag_knowledge/fixtures
COPY 05_ai_answers_analysis/tests /app/05_ai_answers_analysis/tests
COPY 05_ai_answers_analysis/fixtures /app/05_ai_answers_analysis/fixtures
# Includes tests AND any fixtures/ directory through the build allowlist; newer
# 06 also packages src/youtube_agent/data/ in the installed wheel.
COPY 06_research_learning_agent/ /app/06_research_learning_agent/
COPY 07_testing_deployment/tests /app/07_testing_deployment/tests
COPY 07_testing_deployment/fixtures /app/07_testing_deployment/fixtures
COPY 07_testing_deployment/pyproject.toml /app/07_testing_deployment/pyproject.toml
CMD ["python", "07_testing_deployment/scripts/check.py"]

# Browser dependencies are independent of application/test sources.
FROM node:24-bookworm-slim@sha256:8cabefbd444809cf0e319b5831c65da1ea202200ca552a5e75fd7938a6f86658 AS browser-deps
COPY --from=runtime /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
WORKDIR /web
RUN npm install --global pnpm@11.25.0
COPY 01_web_app/package.json 01_web_app/pnpm-lock.yaml ./
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update -o Acquire::Retries=2 -o APT::Update::Error-Mode=any \
    && apt-get install -y --no-install-recommends git
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    --mount=type=cache,target=/root/.cache/ms-playwright \
    pnpm install --frozen-lockfile && pnpm exec playwright install --with-deps chromium \
    && mkdir -p /opt/playwright && cp -a /root/.cache/ms-playwright/. /opt/playwright/

FROM browser-deps AS test-web
COPY --from=test /usr/local /usr/local
COPY --from=test /app /app
COPY --from=browser-deps --chown=10001:10001 /web/node_modules /app/01_web_app/node_modules
COPY --chown=10001:10001 01_web_app/ /app/01_web_app/
COPY 07_testing_deployment/playwright.config.ts /app/07_testing_deployment/playwright.config.ts
ENV PATH="/app/07_testing_deployment/.venv/bin:$PATH" MINIPROJECT_ROOT=/app PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN ldconfig && chown 10001:10001 /app/01_web_app \
    && python /app/07_testing_deployment/scripts/image_source.py record
WORKDIR /app/01_web_app
USER 10001:10001
CMD ["sh", "-c", "pnpm typecheck && pnpm format:check && pnpm test && pnpm build && pnpm exec playwright test --config ../07_testing_deployment/playwright.config.ts"]
