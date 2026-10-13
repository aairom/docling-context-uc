"""Gradio web UI for the docling-context sample.

Run with ``uv run python app.py`` (or ``scripts/start.sh`` for detached mode).

Tabs: Status | Ingest | Search | Ask (chat with citations) | Explore (tree + document).

A single :class:`~dcuc.pipeline.ContextPipeline` is shared by all requests; it
serialises store access internally. SIGTERM/SIGINT close the store cleanly so
``scripts/stop.sh`` performs a graceful shutdown.
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import threading
from pathlib import Path

import gradio as gr

from dcuc.config import Settings
from dcuc.logging_setup import configure_logging
from dcuc.pipeline import TIER_NAMES, ContextPipeline
from dcuc.reporting import answer_markdown, ingest_markdown, write_report

log = logging.getLogger("dcuc.app")


def build_ui(pipeline: ContextPipeline) -> gr.Blocks:
    settings = pipeline.settings

    # ---- handlers: each catches expected errors and shows them in the UI ---- #
    def do_status() -> str:
        return json.dumps(pipeline.status(), indent=2)

    # Gradio injects progress tracking through this default argument (documented pattern).
    def do_ingest(force: bool, progress=gr.Progress()):  # noqa: B008
        try:
            report = pipeline.ingest_directory(
                force=force, progress=lambda i, n, name: progress(i / max(n, 1), desc=name)
            )
        except (FileNotFoundError, ValueError) as exc:
            return f"**Error:** {exc}", do_status()
        _, md_path = write_report(settings.output_dir, "ingest", report, ingest_markdown(report))
        return ingest_markdown(report) + f"\n\nReport saved to `{md_path}`", do_status()

    def do_upload(files: list[str] | None):
        if not files:
            return "No file selected.", do_status()
        lines = ["| File | Status | URI | Detail |", "| --- | --- | --- | --- |"]
        for name in files:
            path = Path(name)
            outcome = pipeline.ingest_bytes(path.read_bytes(), path.name)
            lines.append(
                f"| {path.name} | {outcome.status} | {outcome.uri or ''} | {outcome.detail} |"
            )
        return "\n".join(lines), do_status()

    def do_search(query: str, k: int, mode: str, tiers: list[str]):
        if not query.strip():
            return [], "Enter a query."
        tier_ids = tuple(i for i, name in TIER_NAMES.items() if name in tiers) or (0, 1, 2)
        try:
            result = pipeline.search(query, k=int(k), mode=mode, tiers=tier_ids)
        except ValueError as exc:
            return [], f"**Error:** {exc}"
        rows = [[c.number, c.score, TIER_NAMES[c.tier], c.uri, c.xpath, c.text]
                for c in pipeline.to_citations(result)]
        summary = f"{len(rows)} of {result.total_hits} matching nodes - {result.tokens_used} tokens"
        return rows, summary

    def do_ask(message: str, history: list, session_id: str | None):
        if not message.strip():
            return history, "", session_id
        session_id = session_id or pipeline.start_session()
        answer = pipeline.ask(message, session_id=session_id)
        write_report(settings.output_dir, "answer", answer, answer_markdown(answer))
        sources = "\n".join(f"- [{c.number}] `{c.uri}` `{c.xpath}`" for c in answer.citations)
        reply = f"{answer.answer}\n\n_{answer.method}_\n{sources}"
        history = [*history, {"role": "user", "content": message},
                   {"role": "assistant", "content": reply}]
        return history, "", session_id

    def do_new_session():
        return [], None

    def do_tree():
        entries = pipeline.tree()
        docs = [str(e["uri"]) for e in entries if e["kind"] == "document"]
        text = "\n".join(
            "  " * (int(e["depth"]) - 1) + str(e["uri"]).rsplit("/", 1)[-1]
            + ("/" if e["kind"] == "directory" else "") for e in entries
        )
        return text or "(empty - ingest documents first)", gr.update(choices=docs)

    def do_show(uri: str | None):
        if not uri:
            return "", "", ""
        try:
            info = pipeline.document_overview(uri)
        except Exception as exc:  # noqa: BLE001 - show any lookup error to the user
            return f"Error: {exc}", "", ""
        meta = {k: v for k, v in info.items() if k not in ("summary_xml", "toc_xml")}
        return info["summary_xml"], info["toc_xml"], json.dumps(meta, indent=2, default=str)

    # ---- layout ------------------------------------------------------------ #
    with gr.Blocks(title="docling-context sample") as ui:
        gr.Markdown(
            "# docling-context sample\n"
            f"Collection `docling://resources/{settings.collection}` - tenant "
            f"`{pipeline.principal.tenant_id}` - LLM **{'on' if pipeline.llm else 'off'}** - "
            f"vectors **{'on' if pipeline.vectors_enabled else 'off'}**"
        )
        with gr.Tab("Status"):
            status_box = gr.Code(language="json", value=do_status())
            gr.Button("Refresh").click(do_status, outputs=status_box)
        with gr.Tab("Ingest"):
            gr.Markdown(f"Ingest everything under `{settings.input_dir}` recursively, "
                        "or upload files directly.")
            force = gr.Checkbox(label="Force re-ingest unchanged files")
            ingest_btn = gr.Button("Ingest input folder", variant="primary")
            uploads = gr.File(file_count="multiple", type="filepath", label="Upload")
            upload_btn = gr.Button("Ingest uploads")
            ingest_out = gr.Markdown()
            ingest_btn.click(do_ingest, inputs=force, outputs=[ingest_out, status_box])
            upload_btn.click(do_upload, inputs=uploads, outputs=[ingest_out, status_box])
        with gr.Tab("Search"):
            with gr.Row():
                query = gr.Textbox(label="Query", scale=4)
                k = gr.Slider(1, 20, value=5, step=1, label="k")
                mode = gr.Dropdown(["auto", "lexical", "vector", "hybrid"], value="auto",
                                   label="Mode")
            tiers = gr.CheckboxGroup(list(TIER_NAMES.values()), value=list(TIER_NAMES.values()),
                                     label="Tiers (L0 summary / L1 toc / L2 body)")
            search_info = gr.Markdown()
            results = gr.Dataframe(headers=["#", "score", "tier", "uri", "xpath", "text"],
                                   wrap=True, interactive=False)
            for trigger in (query.submit, gr.Button("Search", variant="primary").click):
                trigger(do_search, inputs=[query, k, mode, tiers], outputs=[results, search_info])
        with gr.Tab("Ask"):
            session_state = gr.State(None)
            # Gradio 6 Chatbot uses the OpenAI-style {"role", "content"} message format.
            chat = gr.Chatbot(height=480)
            question = gr.Textbox(label="Question", placeholder="Ask about your documents")
            question.submit(do_ask, inputs=[question, chat, session_state],
                            outputs=[chat, question, session_state])
            gr.Button("New session").click(do_new_session, outputs=[chat, session_state])
        with gr.Tab("Explore"):
            tree_box = gr.Code(label="Context tree")
            doc_pick = gr.Dropdown(label="Document", choices=[])
            gr.Button("Refresh tree").click(do_tree, outputs=[tree_box, doc_pick])
            with gr.Row():
                summary_box = gr.Code(label="L0 summary (DocLang)", language="html")
                toc_box = gr.Code(label="L1 TOC (DocLang)", language="html")
            meta_box = gr.Code(label="Revision & provenance", language="json")
            doc_pick.change(do_show, inputs=doc_pick, outputs=[summary_box, toc_box, meta_box])
        ui.load(do_tree, outputs=[tree_box, doc_pick])
    return ui


def main() -> int:
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    configure_logging(settings.log_level)
    pipeline = ContextPipeline(settings)
    ui = build_ui(pipeline)
    stopped = threading.Event()

    def shutdown(signum: int, _frame: object) -> None:
        # Close Gradio first (stop accepting requests), then release the store.
        if stopped.is_set():
            return
        stopped.set()
        log.info("Received signal %s - shutting down gracefully", signum)
        try:
            ui.close()
        finally:
            pipeline.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    log.info("Serving on http://%s:%d", settings.app_host, settings.app_port)
    try:
        # Bind to localhost by default; no public share link (local-only app).
        ui.queue(default_concurrency_limit=4).launch(
            server_name=settings.app_host, server_port=settings.app_port,
            share=False, prevent_thread_lock=False,
        )
    finally:
        if not stopped.is_set():
            pipeline.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
