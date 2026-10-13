# Quickstart

This guide gets the docling-context sample running locally in about five minutes.

## 1. Prerequisites

| Tool | Why | Check |
|------|-----|-------|
| macOS or Linux with bash | Runs the scripts | `bash --version` |
| [uv](https://docs.astral.sh/uv/) | Python 3.13 environment and dependencies | `uv --version` |
| git | uv installs docling-context and DocLang from git | `git --version` |
| Optional: llama.cpp server or Ollama | LLM-written answers and summaries | `curl http://localhost:9931/v1/models` |

You don't need an LLM. Without one, the app gives extractive answers that quote the
best passages with citations.

## 2. Install and configure

```bash
cd docling-context-uc
cp .env.example .env        # scripts do this automatically if .env is missing
uv sync                     # creates .venv with the pinned dependencies
```

Edit `.env` if you need to change anything. The most common settings are:

- `LLM_BASE_URL`: your local OpenAI-compatible endpoint. The default is the llama.cpp
  server at `http://localhost:9931/v1`. For Ollama, use `http://localhost:11434/v1`
  and set `LLM_MODEL` to a pulled model, for example `granite3.3`. Leave the value
  empty to run without an LLM.
- `APP_PORT`: web UI port. The default is `7860`. Port `5000` is refused because
  AirDrop uses it on macOS.
- `DC_ENABLE_CONVERSION=true`: lets PDF and Office files be converted through
  Docling. This requires `uv sync --extra conversion`.
- `DC_ENABLE_VECTORS=true`: enables vector and hybrid search. This requires
  `uv sync --extra vectors` and downloads the embedding model the first time it is used.

The scripts install the matching extras automatically when these flags are on.

## 3. Add documents

Put your files in `input/`. Sub-folders are processed recursively and become URI
segments.

```bash
scripts/load-samples.sh     # copy the bundled samples/ into input/ (existing files are kept)
```

| Format | Handled by |
|--------|------------|
| `.dclg.xml`, `.dclg`, `.dclx` (DocLang) | Read natively by docling-context |
| `.md`, `.markdown`, `.txt` | The sample's `MarkdownConverter` |
| `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.csv`, `.adoc`, images | Docling (when `DC_ENABLE_CONVERSION=true`) |

Unsupported or failing files are listed as `skipped` or `failed` in the ingest
report. They never stop the run. The samples include a broken DocLang file on
purpose, so you can see this behaviour.

## 4. Run the CLI demo

```bash
scripts/demo.sh
```

The demo ingests `input/`, rebuilds the collection summary, runs a search and asks a
question. It writes timestamped reports such as these:

```
output/20261012-201942_ingest.json   output/20261012-201942_ingest.md
output/20261012-201942_answer.json   output/20261012-201942_answer.md
```

Individual commands:

```bash
uv run dcuc ingest                     # ingest input/ (unchanged files are skipped)
uv run dcuc ingest --force             # re-ingest everything
uv run dcuc search "credential rotation" -k 3
uv run dcuc ask "How long do refunds take?" --session demo-1
uv run dcuc tree
uv run dcuc show docling://resources/knowledge/policies/refund-policy
uv run dcuc status
uv run dcuc --no-llm ask "What is a SEV1 incident?"
```

## 5. Start the web UI

```bash
scripts/start.sh
# docling-context sample is running: http://127.0.0.1:7860
```

The script starts the app in detached mode, records its PID in `.run/app.pid` and
writes logs to `logs/app.log`. The UI has five tabs:

| Tab | What you can do |
|-----|-----------------|
| Status | View store statistics: documents, indexed nodes, embeddings, and whether the summary is stale. |
| Ingest | Ingest the `input/` folder (optionally with force), or upload files directly. |
| Search | Run lexical, vector, hybrid or auto search. Filter by tier (L0 summary, L1 TOC, L2 body) and see every hit with its URI and XPath. |
| Ask | Chat with the documents. Each answer lists citations, and turns are recorded in a session. **New session** starts a fresh one. |
| Explore | Browse the context tree and inspect a document's L0 summary, L1 TOC, revision and provenance. |

Stop the app gracefully:

```bash
scripts/stop.sh             # sends SIGTERM, waits, and escalates only if needed
```

## 6. Test

```bash
scripts/test.sh             # ruff lint + pytest with coverage
```

## 7. Clean up at the end of the project

```bash
scripts/cleanup.sh          # removes .venv, node_modules, __pycache__, caches and logs
scripts/cleanup.sh --all    # also removes context-data/ and the contents of input/ and output/
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `LLM answer failed, falling back to extractive` in the logs | The LLM endpoint is not reachable. Start llama.cpp or Ollama, or set `LLM_BASE_URL=` to silence it. |
| `APP_PORT 5000 is reserved on macOS` | Choose another port. 5000 is reserved by AirDrop on macOS. |
| `LLM_BASE_URL must be HTTPS or loopback HTTP` | By design, plain HTTP is only accepted for `localhost`, `127.0.0.1` or `::1`, so prompts are never sent unencrypted over a network. |
| A file shows as `skipped` | Its type is not supported, or it needs `DC_ENABLE_CONVERSION=true`. |
| `Already running` from `start.sh` | Run `scripts/stop.sh` first. |
