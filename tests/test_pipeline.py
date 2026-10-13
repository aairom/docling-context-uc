"""Integration tests against a real LocalContextStore (no mocks of docling-context)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from docling_context import AccessDenied, Principal, RecordMissing

from dcuc.config import LLMSettings
from dcuc.pipeline import ContextPipeline

from .conftest import fake_llm

ROTATION = "docling://resources/knowledge/engineering/runbooks/credential-rotation"
REFUND = "docling://resources/knowledge/policies/refund-policy"


def test_ingest_directory_recursively(pipeline: ContextPipeline):
    report = pipeline.ingest_directory()
    by_path = {item.path: item for item in report.files}
    assert by_path["engineering/runbooks/credential-rotation.md"].uri == ROTATION
    assert report.count("ingested") == 4
    # The intentionally broken sample fails without aborting the run.
    assert by_path["policies/broken-example.dclg.xml"].status == "failed"
    assert report.collection_jobs >= 1
    assert pipeline.status()["collection_summary_stale"] is False


def test_reingest_is_idempotent_and_force_creates_revision(pipeline: ContextPipeline):
    first = {i.path: i.revision_id for i in pipeline.ingest_directory().files}
    second = pipeline.ingest_directory()
    assert second.count("ingested") == 0 and second.count("unchanged") == 4
    forced = {i.path: i.revision_id for i in pipeline.ingest_directory(force=True).files}
    key = "policies/refund-policy.dclg.xml"
    assert forced[key] != first[key]


def test_changed_file_creates_new_revision(pipeline: ContextPipeline, settings):
    pipeline.ingest_directory()
    before = pipeline.document_overview(ROTATION)["revision_id"]
    path = settings.input_dir / "engineering/runbooks/credential-rotation.md"
    path.write_text(path.read_text() + "\n\nNew appendix about hardware tokens.\n")
    pipeline.ingest_directory()
    assert pipeline.document_overview(ROTATION)["revision_id"] != before
    hits = pipeline.search("hardware tokens").hits
    assert hits and hits[0].uri == ROTATION


def test_unsupported_and_hidden_files_are_skipped(pipeline: ContextPipeline, settings):
    (settings.input_dir / "binary.exe").write_bytes(b"MZ")
    (settings.input_dir / "scan.pdf").write_bytes(b"%PDF-1.4")
    (settings.input_dir / ".hidden.md").write_text("# secret")
    files = {i.path: i for i in pipeline.ingest_directory().files}
    assert files["binary.exe"].status == "skipped"
    assert "DC_ENABLE_CONVERSION" in files["scan.pdf"].detail
    assert ".hidden.md" not in files


def test_symlink_escape_is_blocked(pipeline: ContextPipeline, settings, tmp_path: Path):
    secret = tmp_path / "outside.md"
    secret.write_text("# Outside\n\nshould never be ingested")
    (settings.input_dir / "link.md").symlink_to(secret)
    files = {i.path: i for i in pipeline.ingest_directory().files}
    # Ingestor resolves symlinks and enforces allowed_roots.
    assert files["link.md"].status == "failed"
    assert "outside allowed roots" in files["link.md"].detail


def test_missing_input_dir(pipeline: ContextPipeline, tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        pipeline.ingest_directory(tmp_path / "nope")


def test_search_scoping_and_citations(pipeline: ContextPipeline):
    pipeline.ingest_directory()
    result = pipeline.search("refund invoice", tiers=(2,))
    assert result.hits and all(h.tier == 2 for h in result.hits)
    assert result.hits[0].uri == REFUND
    # Scope to a subtree: no policy documents may leak into engineering results.
    scoped = pipeline.search("refund", uri="docling://resources/knowledge/engineering")
    assert all(h.uri.startswith("docling://resources/knowledge/engineering/") for h in scoped.hits)
    # A citation can be re-read by its immutable (document, revision, xpath) address.
    citation = pipeline.to_citations(result)[0]
    assert pipeline.read_citation(citation) == citation.text


def test_search_validation(pipeline: ContextPipeline):
    with pytest.raises(ValueError):
        pipeline.search("   ")
    with pytest.raises(ValueError):
        pipeline.search("x", mode="vector")  # no embedder configured


def test_document_overview_has_summary_toc_and_provenance(pipeline: ContextPipeline):
    pipeline.ingest_directory()
    info = pipeline.document_overview(ROTATION)
    assert "Credential Rotation Runbook" in info["summary_xml"]
    assert "Rotate the API credentials" in info["toc_xml"]
    assert info["source"]["converter"] == "dcuc-markdown"
    assert info["source"]["summary_method"] == "extractive"
    assert len(info["sha256"]) == 64
    with pytest.raises(RecordMissing):
        pipeline.document_overview("docling://resources/knowledge/missing")


def test_tree_mirrors_input_layout(pipeline: ContextPipeline):
    pipeline.ingest_directory()
    uris = {e["uri"] for e in pipeline.tree()}
    assert "docling://resources/knowledge/engineering/runbooks" in uris
    assert ROTATION in uris


def test_ask_extractive_and_session_transcript(pipeline: ContextPipeline):
    pipeline.ingest_directory()
    session = pipeline.start_session("chat-1")
    answer = pipeline.ask("How do I rotate the API credentials?", session_id=session)
    assert answer.method == "extractive"
    assert answer.citations and answer.citations[0].uri == ROTATION
    assert not any(c.uri.endswith("/_context/summary") for c in answer.citations)
    events = pipeline.session_transcript(session)
    assert [e["text"].split(":")[0] for e in events] == ["user", "assistant (extractive)"]
    assert events[0]["turn_id"] == events[1]["turn_id"]
    pipeline.ask("What is the refund policy?", session_id=session)
    assert len(pipeline.session_transcript(session)) == 4
    assert pipeline.list_sessions()[0]["session_id"] == "chat-1"
    pipeline.close_session(session)
    with pytest.raises(ValueError):
        pipeline.ask("again?", session_id=session)  # closed sessions reject new events


def test_ask_without_hits(pipeline: ContextPipeline):
    pipeline.ingest_directory()
    answer = pipeline.ask("zebra xylophone")
    assert answer.citations == [] and "No matching passages" in answer.answer
    assert "Cannot search" in pipeline.ask("???").answer


def test_ask_with_llm_uses_context(settings):
    client, seen = fake_llm("Generate a new key pair first [1].")
    with ContextPipeline(settings, llm_client=client) as p:
        p.ingest_directory()
        answer = p.ask("How do I rotate the API credentials?")
    assert answer.method == "llm" and answer.answer.endswith("[1].")
    prompt = seen[-1].content.decode()
    assert "Generate a new key pair" in prompt and ROTATION in prompt


def test_ask_falls_back_when_llm_fails(settings):
    client, _ = fake_llm(status=503)
    with ContextPipeline(settings, llm_client=client) as p:
        p.ingest_directory()
        answer = p.ask("refund policy")
    assert answer.method == "extractive" and answer.citations


def test_llm_summaries_and_fallback(settings):
    llm_settings = dataclasses.replace(settings, llm=LLMSettings(use_for_summaries=True))
    good, _ = fake_llm("A runbook for rotating billing API keys.")
    with ContextPipeline(llm_settings, llm_client=good) as p:
        p.ingest_directory()
        info = p.document_overview(ROTATION)
    assert info["source"]["summary_method"] == "model"
    assert "rotating billing API keys" in info["summary_xml"]

    bad, _ = fake_llm(status=500)
    with ContextPipeline(llm_settings, llm_client=bad) as p:
        p.ingest_directory(force=True)
        assert p.document_overview(ROTATION)["source"]["summary_method"] == "extractive-fallback"


def test_ingest_bytes_upload(pipeline: ContextPipeline):
    outcome = pipeline.ingest_bytes(b"# Uploaded\n\nQuarterly OKRs", "okrs.md")
    assert outcome.status == "ingested"
    assert outcome.uri == "docling://resources/knowledge/uploads/okrs"
    assert pipeline.search("Quarterly OKRs").hits[0].uri == outcome.uri
    assert pipeline.ingest_bytes(b"x", "a.exe").status == "skipped"
    assert pipeline.ingest_bytes(b"", "empty.md").status == "failed"


def test_tenants_are_isolated(settings):
    with ContextPipeline(settings) as acme:
        acme.ingest_directory()
    other = dataclasses.replace(settings, tenant_id="globex")
    with ContextPipeline(other) as globex:
        assert globex.search("refund").hits == ()
        assert globex.status()["documents"] == 0
        # The library refuses another user's session namespace outright.
        with pytest.raises(AccessDenied):
            globex.sessions.get(Principal("globex", "eve"),
                                "docling://users/demo/local/sessions/chat-1")


def test_store_persists_across_restarts(settings):
    with ContextPipeline(settings) as p:
        p.ingest_directory()
    with ContextPipeline(settings) as p:
        assert p.status()["documents"] >= 4
        assert p.search("crampons").hits == ()  # sanity: unknown word, no false positives
        assert p.search("SEV1").hits


def test_keyword_query():
    from dcuc.pipeline import keyword_query

    assert keyword_query("How do I rotate the API credentials?") == "rotate API credentials"
    assert keyword_query("What is it?") == "What is it?"  # nothing left: keep original


def test_answer_context_prefers_body_then_falls_back(pipeline: ContextPipeline):
    pipeline.ingest_directory()
    body = pipeline._answer_context("rotate API credentials", 5)
    assert body.hits and all(h.tier == 2 for h in body.hits)
    # "refund policy" only matches headings/summaries in AND mode -> tier fallback.
    fallback = pipeline._answer_context("refund policy", 5)
    assert fallback.hits[0].uri == REFUND
    texts = [h.text.strip().lower() for h in fallback.hits]
    assert len(texts) == len(set(texts))  # heading and identical TOC entry de-duplicated
    assert not any(h.uri.endswith("/_context/summary") for h in fallback.hits)
