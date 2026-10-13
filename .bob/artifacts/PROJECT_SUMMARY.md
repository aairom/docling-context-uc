# Project summary: docling-context sample (dcuc)

Generated: 2026-10-12T18:29:02Z
Upstream: docling-context @ 58b2048, DocLang @ 92d2990 (pinned git sources in pyproject.toml)

## Delivered
- dcuc/ package: config, uris, converters (custom Converter), llm (OpenAI-compatible local client),
  summaries (custom SummaryProvider), pipeline (ContextPipeline facade), reporting, cli
- app.py: Gradio UI with Status, Ingest, Search, Ask and Explore tabs (verified in the browser)
- scripts/: start.sh (detached, prints URL), stop.sh (graceful SIGTERM), demo.sh, test.sh,
  load-samples.sh, cleanup.sh [--all]
- Docs/Quickstart.md, Docs/Architecture.md; README.md with Mermaid diagrams and the MIT licence
- samples/: Markdown, text and DocLang corpus, plus one intentionally broken file

## Validation
- ruff: clean
- pytest: 83 passed, 92% coverage (see test-results.txt)
- CLI demo: ingest/answer reports in output/ (copies in this folder)
- UI: Status, Ask (extractive answer with citation), Search (tiered hits) and Explore (tree) checked in Chrome
- start.sh / stop.sh: graceful stop confirmed

## Notes
- The LLM at http://localhost:9931/v1 was not running during validation; answers used the extractive fallback.
- No container images are pulled, so no image clean-up script is required.
