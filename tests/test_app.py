"""Exercise the Gradio handlers without starting a web server."""

import gradio as gr

import app


def _fn(ui: gr.Blocks, name: str):
    return next(dep.fn for dep in ui.fns.values() if dep.fn is not None and dep.fn.__name__ == name)


def test_ui_builds_and_handlers_work(pipeline):
    ui = app.build_ui(pipeline)
    assert isinstance(ui, gr.Blocks)

    markdown, status = _fn(ui, "do_ingest")(False, progress=lambda *a, **k: None)
    assert "Ingested: 4" in markdown and '"documents"' in status

    rows, info = _fn(ui, "do_search")("refund", 3, "lexical", ["body"])
    assert rows and rows[0][2] == "body" and "matching nodes" in info
    assert _fn(ui, "do_search")("  ", 3, "auto", [])[1] == "Enter a query."
    assert "Error" in _fn(ui, "do_search")("x", 3, "vector", [])[1]

    history, cleared, session = _fn(ui, "do_ask")("refund policy?", [], None)
    assert cleared == "" and session and history[-1]["role"] == "assistant"
    history, _, same = _fn(ui, "do_ask")("support hours?", history, session)
    assert same == session and len(history) == 4

    tree, update = _fn(ui, "do_tree")()
    assert "runbooks/" in tree and update["choices"]
    summary, toc, meta = _fn(ui, "do_show")(update["choices"][0])
    assert summary.startswith("<doclang>") and '"revision_id"' in meta
    assert _fn(ui, "do_show")(None) == ("", "", "")


def test_upload_handler(pipeline, tmp_path):
    ui = app.build_ui(pipeline)
    upload = tmp_path / "notes.md"
    upload.write_text("# Notes\n\nUploaded content")
    table, _ = _fn(ui, "do_upload")([str(upload)])
    assert "ingested" in table and "uploads/notes" in table
    assert _fn(ui, "do_upload")(None)[0] == "No file selected."
