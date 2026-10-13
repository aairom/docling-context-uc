"""LLM-backed implementation of docling-context's ``SummaryProvider`` protocol.

The Ingestor calls ``summarize(document, source_revision)`` and expects a
DocLang XML string. If the provider raises *anything*, the Ingestor stores an
extractive summary instead and records ``summary_method="extractive-fallback"``
in the revision provenance. We rely on that contract: this provider raises on
any problem rather than returning a half-valid summary.
"""

from __future__ import annotations

import logging
from xml.sax.saxutils import escape

from doclang import DocLangXDocument

from .llm import LLMClient

log = logging.getLogger(__name__)

# Bound the prompt so huge documents do not overflow small local models.
MAX_PROMPT_CHARS = 8_000
MAX_SUMMARY_CHARS = 1_200

SYSTEM_PROMPT = (
    "You summarise documents for a search index. Write 2-4 factual sentences "
    "covering the document's purpose and key facts. No preamble, no markdown."
)


def document_text(document: DocLangXDocument, limit: int = MAX_PROMPT_CHARS) -> str:
    """Collect heading/text content in reading order, bounded to ``limit`` characters."""
    pieces: list[str] = []
    size = 0
    for node in document.iter_nodes(None, limit=5_000, max_text_chars=2_000):
        if node["name"] not in {"heading", "text"} or not node["text"].strip():
            continue
        text = node["text"].strip()
        pieces.append(text)
        size += len(text) + 1
        if size >= limit:
            break
    return "\n".join(pieces)[:limit]


class LLMSummaryProvider:
    """Summarise each ingested revision with a local LLM."""

    def __init__(self, client: LLMClient):
        self.client = client

    def summarize(self, document: DocLangXDocument, source_revision: str) -> str:
        content = document_text(document)
        if not content:
            raise ValueError("document has no text to summarise")
        summary = self.client.chat(SYSTEM_PROMPT, content, max_tokens=300)
        summary = " ".join(summary.split())[:MAX_SUMMARY_CHARS]
        log.debug("LLM summary for revision %s: %d chars", source_revision, len(summary))
        # The summary sidecar must itself be DocLang; escaping makes it safe.
        return f"<doclang><text>{escape(summary)}</text></doclang>"
