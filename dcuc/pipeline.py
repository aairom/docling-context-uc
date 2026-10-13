"""``ContextPipeline`` - the single facade the CLI and the web UI talk to.

It demonstrates the main docling-context building blocks end to end:

====================  =======================================================
docling-context API   Used here for
====================  =======================================================
``Principal``         Tenant/user identity; *every* store call is scoped by it
``LocalContextStore`` SQLite metadata + immutable SHA-256 DCLX packages
``Ingestor``          Convert + summarise + TOC + index one source revision
``CollectionWorker``  Durable jobs that rebuild per-collection summaries
``Retriever``         Scoped lexical / vector / hybrid search with citations
``SessionStore``      Revisioned, append-only conversation transcripts
``NodeAddress``       Stable citation (document, revision, xpath)
====================  =======================================================

Resource management: the store owns an SQLite connection, so the pipeline is a
context manager and must be closed. A single lock serialises store access,
because the web UI runs request handlers on several worker threads while
SQLite connections are not safe for concurrent use.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from docling_context import (
    CollectionWorker,
    ContextResult,
    Converter,
    Ingestor,
    LocalContextStore,
    NodeAddress,
    PackageError,
    Principal,
    RecordMissing,
    Retriever,
    SearchScope,
    SessionStore,
)

from .config import Settings
from .converters import MarkdownConverter
from .llm import LLMClient, LLMError
from .summaries import LLMSummaryProvider
from .uris import classify, uri_for, validate_collection

log = logging.getLogger(__name__)

# Upper bound on documents ingested per run, a guard against a mis-pointed input dir.
MAX_FILES_PER_RUN = 10_000

ANSWER_SYSTEM_PROMPT = (
    "You answer questions using ONLY the numbered context passages. "
    "Cite passages inline like [1] or [2]. If the context does not contain the "
    "answer, say you do not know. Be concise."
)


# --------------------------------------------------------------------------- #
# Result types (plain dataclasses so they serialise cleanly into reports/UI)   #
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class FileOutcome:
    path: str
    uri: str | None
    status: str  # ingested | unchanged | skipped | failed
    detail: str = ""
    revision_id: str | None = None
    summary_method: str | None = None


@dataclass(slots=True)
class IngestReport:
    collection: str
    started_at: float
    finished_at: float = 0.0
    files: list[FileOutcome] = field(default_factory=list)
    collection_jobs: int = 0

    def count(self, status: str) -> int:
        return sum(1 for item in self.files if item.status == status)

    @property
    def duration_seconds(self) -> float:
        return round(self.finished_at - self.started_at, 3)


@dataclass(slots=True)
class Citation:
    number: int
    uri: str
    xpath: str
    tier: int
    score: float
    text: str
    document_id: str
    revision_id: str


@dataclass(slots=True)
class Answer:
    question: str
    answer: str
    method: str  # "llm" | "extractive"
    citations: list[Citation]
    session_id: str | None = None


TIER_NAMES = {0: "summary", 1: "toc", 2: "body"}

# Common English function words. Lexical search ANDs all query words first and
# falls back to OR, so filler words in a natural-language question ("how do I
# ... the") either break the AND match or rank documents by "the". Removing
# them turns a question into a focused keyword query.
STOPWORDS = frozenset(
    "a an and any are as at be by can could do does for from had has have how i if in "
    "is it its me my of on or our should so that the their then there these this to "
    "was we were what when where which who why will with would you your".split()
)


def keyword_query(question: str) -> str:
    """Reduce a question to its content words; keep the original if nothing is left."""
    words = re.findall(r"\w+", question, flags=re.UNICODE)
    keywords = [w for w in words if w.lower() not in STOPWORDS]
    return " ".join(keywords) if keywords else question


# --------------------------------------------------------------------------- #
# Pipeline                                                                     #
# --------------------------------------------------------------------------- #
class ContextPipeline:
    """High-level operations over one docling-context store for one principal."""

    def __init__(self, settings: Settings, *, llm_client: LLMClient | None = None):
        self.settings = settings
        self.collection = validate_collection(settings.collection)
        # Principal validation (no '/', '%', '..', control chars) happens in the library.
        self.principal = Principal(settings.tenant_id, settings.user_id)
        self._lock = threading.RLock()

        # Opening the store migrates the schema and reconciles packages: any blob
        # that is missing or fails its SHA-256 check is marked unavailable.
        self.store = LocalContextStore(settings.store_dir)
        try:
            self.llm = llm_client if llm_client is not None else self._make_llm()
            self.retriever = Retriever(self.store, embedder=self._make_embedder())
            self.sessions = SessionStore(self.store)
            self.worker = CollectionWorker(self.store)
        except Exception:
            self.store.close()  # never leak the SQLite connection on a failed start
            raise
        log.info(
            "Pipeline ready: store=%s tenant=%s collection=%s llm=%s vectors=%s",
            settings.store_dir, self.principal.tenant_id, self.collection,
            "on" if self.llm else "off", "on" if self.vectors_enabled else "off",
        )

    # -- lifecycle ---------------------------------------------------------- #
    def close(self) -> None:
        with self._lock:
            if self.llm is not None:
                self.llm.close()
            self.store.close()
            log.info("Pipeline closed")

    def __enter__(self) -> ContextPipeline:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- optional components ------------------------------------------------ #
    def _make_llm(self) -> LLMClient | None:
        if not self.settings.llm.enabled:
            return None
        try:
            return LLMClient(self.settings.llm)
        except LLMError as exc:
            log.warning("LLM disabled: %s", exc)
            return None

    def _make_embedder(self):
        """Return an embedding provider, or None for lexical-only search.

        Vectors are optional: if the extra is not installed or the model cannot be
        loaded, the app keeps working with lexical search instead of failing.
        """
        if not self.settings.enable_vectors:
            return None
        try:
            from docling_context import local_embedding_provider

            return local_embedding_provider(self.settings.embedding_model)
        except Exception as exc:  # noqa: BLE001 - optional dependency may fail many ways
            log.warning("Vector search disabled (%s); using lexical search", exc)
            return None

    @property
    def vectors_enabled(self) -> bool:
        return self.retriever.vector_index is not None

    def _converter_for(self, kind: str) -> Converter | None:
        if kind == "text":
            return MarkdownConverter()
        if kind == "docling":
            if not self.settings.enable_conversion:
                return None
            from docling_context import LocalDoclingConverter, PdfConversionConfig

            # OCR off by default: faster, and most sample PDFs carry a text layer.
            return LocalDoclingConverter(PdfConversionConfig(do_ocr=False))
        return None  # native sources need no converter

    def _ingestor(self, root: Path, converter: Converter | None) -> Ingestor:
        summary_provider = (
            LLMSummaryProvider(self.llm)
            if self.llm is not None and self.settings.llm.use_for_summaries
            else None
        )
        # allowed_roots is a security boundary: the Ingestor refuses to read any
        # path (after resolving symlinks) outside these directories.
        return Ingestor(
            self.store,
            allowed_roots=(root.resolve(),),
            converter=converter,
            summary_provider=summary_provider,
        )

    # -- ingestion ---------------------------------------------------------- #
    def iter_input_files(self, root: Path) -> Iterator[Path]:
        """Yield files under ``root`` recursively, skipping hidden files/folders."""
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if path.is_file():
                yield path

    def ingest_directory(
        self,
        root: Path | None = None,
        *,
        force: bool = False,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> IngestReport:
        """Ingest every supported file below ``root`` (default: ``input/``).

        Each file is handled independently: one bad file is reported as ``failed``
        and the run continues. Re-running is cheap because unchanged files are
        detected by the Ingestor's source fingerprint and skipped.
        """
        root = (root or self.settings.input_dir).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"input directory does not exist: {root}")
        report = IngestReport(collection=self.collection, started_at=time.time())
        files = list(self.iter_input_files(root))
        if len(files) > MAX_FILES_PER_RUN:
            raise ValueError(f"refusing to ingest {len(files)} files (> {MAX_FILES_PER_RUN})")

        ingestors: dict[str, Ingestor] = {}
        for index, path in enumerate(files, start=1):
            if progress:
                progress(index, len(files), path.name)
            report.files.append(self._ingest_one(root, path, ingestors, force=force))

        report.collection_jobs = self.process_collection_jobs()
        report.finished_at = time.time()
        log.info(
            "Ingest finished in %.2fs: %d ingested, %d unchanged, %d skipped, %d failed",
            report.duration_seconds, report.count("ingested"), report.count("unchanged"),
            report.count("skipped"), report.count("failed"),
        )
        return report

    def _ingest_one(
        self, root: Path, path: Path, ingestors: dict[str, Ingestor], *, force: bool
    ) -> FileOutcome:
        relative = str(path.relative_to(root))
        kind = classify(path)
        if kind is None:
            return FileOutcome(relative, None, "skipped", "unsupported file type")
        converter = self._converter_for(kind)
        if kind == "docling" and converter is None:
            return FileOutcome(
                relative, None, "skipped",
                "needs Docling conversion "
                "(set DC_ENABLE_CONVERSION=true, uv sync --extra conversion)",
            )
        try:
            uri = uri_for(path, root, self.collection)
        except ValueError as exc:
            return FileOutcome(relative, None, "failed", f"invalid URI: {exc}")

        ingestor = ingestors.setdefault(kind, self._ingestor(root, converter))
        try:
            with self._lock:
                previous = self._current_revision(uri)
                record = ingestor.add_resource(self.principal, uri, path, force=force)
        except (PackageError, ValueError, PermissionError, RuntimeError, OSError) as exc:
            # Expected per-file problems (bad markup, too large, missing extra, ...).
            log.warning("Failed to ingest %s: %s", relative, exc)
            return FileOutcome(relative, uri, "failed", str(exc))
        status = "unchanged" if record.revision_id == previous else "ingested"
        log.info("%-9s %s -> %s", status, relative, uri)
        return FileOutcome(
            relative, uri, status, revision_id=record.revision_id,
            summary_method=record.source.get("summary_method"),
        )

    def _current_revision(self, uri: str) -> str | None:
        try:
            return self.store.get_record(self.principal, uri).revision_id
        except RecordMissing:
            return None

    def ingest_bytes(self, data: bytes, filename: str, *, subpath: str = "uploads") -> FileOutcome:
        """Ingest an uploaded file (no filesystem access - bytes + filename)."""
        kind = classify(Path(filename))
        if kind is None:
            return FileOutcome(filename, None, "skipped", "unsupported file type")
        converter = self._converter_for(kind)
        if kind == "docling" and converter is None:
            return FileOutcome(filename, None, "skipped", "Docling conversion is disabled")
        # Build the URI relative to a virtual root so the same slug rules apply.
        virtual_root = Path("/virtual")
        uri = uri_for(virtual_root / subpath / Path(filename).name, virtual_root, self.collection)
        ingestor = Ingestor(self.store, converter=converter)
        try:
            with self._lock:
                record = ingestor.add_resource(
                    self.principal, uri, data, filename=Path(filename).name,
                    origin_uri=f"upload:{Path(filename).name}",
                )
                self.process_collection_jobs()
        except (PackageError, ValueError, RuntimeError) as exc:
            return FileOutcome(filename, uri, "failed", str(exc))
        return FileOutcome(filename, uri, "ingested", revision_id=record.revision_id,
                           summary_method=record.source.get("summary_method"))

    def process_collection_jobs(self, limit: int = 1_000) -> int:
        """Drain the durable collection-summary job queue (in-process worker).

        In production you would run ``CollectionWorker.run_forever(stop_event)``
        in a separate process with its own store connection.
        """
        processed = 0
        with self._lock:
            while processed < limit and self.worker.run_once() is not None:
                processed += 1
        return processed

    # -- inspection --------------------------------------------------------- #
    def tree(self, depth: int = 4, limit: int = 500) -> list[dict[str, object]]:
        with self._lock:
            entries = self.store.walk(
                self.principal, f"docling://resources/{self.collection}", depth=depth, limit=limit
            )
        return [
            {"uri": entry.uri, "kind": entry.kind, "depth": entry.depth,
             "revision_id": entry.revision_id}
            for entry in entries
        ]

    def status(self) -> dict[str, object]:
        with self._lock:
            index = self.store.index_status(self.principal)
            collection = self.worker.status(self.principal, f"docling://resources/{self.collection}")
        return {
            "tenant": self.principal.tenant_id,
            "user": self.principal.user_id,
            "collection": self.collection,
            # None means nothing was ever written to the collection (no status row).
            "collection_summary_stale": None if collection is None else collection.stale,
            "llm_enabled": self.llm is not None,
            "vectors_enabled": self.vectors_enabled,
            **index,
        }

    def document_overview(self, uri: str) -> dict[str, object]:
        """Return L0 summary, L1 TOC XML and provenance for one document."""
        with self._lock:
            record = self.store.get_record(self.principal, uri)
            document = self.store.get_document(self.principal, uri)
            summary = document.summary()
            toc = document.toc()
        return {
            "uri": record.uri,
            "document_id": record.document_id,
            "revision_id": record.revision_id,
            "sha256": record.package.sha256,
            "size_bytes": record.package.size_bytes,
            "updated_at": record.updated_at,
            "source": record.source,
            "summary_xml": summary.xml() if summary is not None else "",
            "toc_xml": toc.xml() if toc is not None else "",
        }

    def read_citation(self, citation: Citation) -> str:
        """Re-read a cited node by its immutable address (document, revision, xpath)."""
        address = NodeAddress(citation.document_id, citation.revision_id, citation.xpath)
        with self._lock:
            return self.store.read_node(self.principal, address).text

    # -- retrieval ---------------------------------------------------------- #
    def search(
        self,
        query: str,
        *,
        k: int = 5,
        mode: str = "auto",
        uri: str | None = None,
        tiers: tuple[int, ...] = (0, 1, 2),
        max_tokens: int = 2_000,
    ) -> ContextResult:
        """Scoped search. ``mode='auto'`` picks hybrid when vectors are available."""
        if not query.strip():
            raise ValueError("query must not be empty")
        if mode == "auto":
            mode = "hybrid" if self.vectors_enabled else "lexical"
        scope = SearchScope(uri=uri or f"docling://resources/{self.collection}", tiers=tiers)
        with self._lock:
            return self.retriever.search(
                self.principal, query, scope=scope, k=k, mode=mode,
                max_tokens=max_tokens, per_result_tokens=min(400, max_tokens),
            )

    @staticmethod
    def to_citations(result: ContextResult) -> list[Citation]:
        return [
            Citation(i, hit.uri, hit.xpath, hit.tier, round(hit.score, 4), hit.text,
                     hit.document_id, hit.revision_id)
            for i, hit in enumerate(result.hits, start=1)
        ]

    # -- question answering (RAG) + sessions -------------------------------- #
    def ask(self, question: str, *, k: int = 5, session_id: str | None = None) -> Answer:
        """Retrieve context, answer with the local LLM (or extractively), log to a session."""
        try:
            citations = self.to_citations(self._answer_context(keyword_query(question), k))
        except ValueError as exc:
            # e.g. a query with no word characters; return a helpful message instead
            return Answer(question, f"Cannot search: {exc}", "extractive", [], session_id)

        answer_text, method = self._compose_answer(question, citations)
        answer = Answer(question, answer_text, method, citations, session_id)
        if session_id:
            self._record_turn(session_id, answer)
        return answer

    def _answer_context(self, query: str, k: int) -> ContextResult:
        """Pick passages for answering.

        Body nodes (tier 2) are precise and directly citable, so they are tried
        first; summaries/TOC (tiers 0-1) are the fallback when no body node
        matches. In both passes we over-fetch, drop the generated collection
        summary (it lists member URIs rather than answering anything) and
        de-duplicate identical text, e.g. a heading and its TOC entry.
        """
        for tiers in ((2,), (0, 1, 2)):
            result = self.search(query, k=min(k * 3, 50), tiers=tiers)
            seen: set[str] = set()
            hits = []
            for hit in result.hits:
                key = hit.text.strip().lower()
                if hit.uri.endswith("/_context/summary") or not key or key in seen:
                    continue
                seen.add(key)
                hits.append(hit)
            if hits:
                return ContextResult(tuple(hits[:k]), result.tokens_used, result.truncated,
                                     result.total_hits)
        return ContextResult((), 0, False, 0)

    def _compose_answer(self, question: str, citations: list[Citation]) -> tuple[str, str]:
        if not citations:
            return "No matching passages were found in the indexed documents.", "extractive"
        if self.llm is not None:
            context = "\n\n".join(f"[{c.number}] ({c.uri}) {c.text}" for c in citations)
            try:
                return self.llm.chat(
                    ANSWER_SYSTEM_PROMPT, f"Context:\n{context}\n\nQuestion: {question}"
                ), "llm"
            except LLMError as exc:
                log.warning("LLM answer failed, falling back to extractive: %s", exc)
        # Extractive fallback: return the best passages verbatim with citations.
        lines = [f"[{c.number}] {c.text}" for c in citations[:3]]
        return "Most relevant passages:\n" + "\n".join(lines), "extractive"

    def start_session(self, session_id: str | None = None) -> str:
        with self._lock:
            return self.sessions.start(self.principal, session_id).session_id

    def _record_turn(self, session_id: str, answer: Answer) -> None:
        """Append the question and answer as two events of one turn.

        ``key`` is an idempotency key: re-sending the same key is a no-op, which
        makes retries safe. Each event therefore gets a fresh unique key.
        """
        turn = uuid.uuid4().hex
        sources = ", ".join(f"[{c.number}] {c.uri}#{c.xpath}" for c in answer.citations)
        with self._lock:
            self.sessions.append(self.principal, session_id, key=f"{turn}-q", kind="turn",
                                 turn_id=turn, text=f"user: {answer.question}"[:20_000])
            self.sessions.append(self.principal, session_id, key=f"{turn}-a", kind="turn",
                                 turn_id=turn,
                                 text=f"assistant ({answer.method}): {answer.answer}\n"
                                      f"sources: {sources}"[:20_000])

    def session_transcript(self, session_id: str) -> list[dict[str, object]]:
        with self._lock:
            events = self.sessions.replay(self.principal, session_id)
        return [{"sequence": e.sequence, "kind": e.kind, "turn_id": e.turn_id,
                 "created_at": e.created_at, "text": e.text} for e in events]

    def list_sessions(self) -> list[dict[str, object]]:
        with self._lock:
            infos = self.sessions.list(self.principal)
        return [{"session_id": i.session_id, "status": i.status, "events": i.event_count,
                 "updated_at": i.updated_at} for i in infos]

    def close_session(self, session_id: str) -> None:
        with self._lock:
            self.sessions.close(self.principal, session_id)
