# Optional module-05 acceptance environment

This is a test environment, not a distributable package or an extra dependency of
`youtube-knowledge-agent`. Its own manifest/lock installs actual module 05 alongside 06.
The public agent manifest keeps its original dependencies so existing 02/05/07 consumer
locks and Docker contexts do not need additional module-05 source just to install 06.

From MiniProject:

```powershell
uv sync --project 06_research_learning_agent/acceptance --locked
uv run --project 06_research_learning_agent/acceptance --locked pytest -c 06_research_learning_agent/acceptance/pyproject.toml 06_research_learning_agent/acceptance/tests -q -W error
```

The two tests exercise real `AnswerService` comparison/citation mapping and cancellation,
sharing the core integration fixture's real SQLite/Chroma/RAG. Provider outputs and captions
are labelled fixtures, with no live calls. To run all 77 checks, include the core test path:

```powershell
uv run --project 06_research_learning_agent/acceptance --locked pytest -c 06_research_learning_agent/acceptance/pyproject.toml 06_research_learning_agent/tests 06_research_learning_agent/acceptance/tests -q -W error
docker compose -f 06_research_learning_agent/compose.test.yaml -p yk06-check build acceptance
docker compose -f 06_research_learning_agent/compose.test.yaml -p yk06-check run --rm --no-deps acceptance
```

Core-only users can continue using the original `06_research_learning_agent` environment
and `tests` Docker service (75 tests). No tests are silently skipped when 05 is missing.
The default evaluation dataset is installed under `youtube_agent/data`, so consumer images
copying only package source and core tests require no separate fixtures copy.
