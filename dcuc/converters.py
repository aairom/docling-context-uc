"""A lightweight Markdown / plain-text -> DocLang converter.

docling-context accepts any object implementing its ``Converter`` protocol::

    def convert(self, source: bytes, filename: str) -> ConversionResult

Docling itself (``LocalDoclingConverter``) handles PDF, Office and images but
pulls in a large ML stack. For text-first knowledge bases (READMEs, runbooks,
notes) this small converter keeps the sample fast and dependency-free while
showing *how to plug a custom converter into the Ingestor*.

Design decisions
----------------
* Only ``<heading>`` and ``<text>`` elements are emitted. They are what the
  docling-context indexer, summary and TOC builders understand best.
* Markdown headings become ``<heading level="n">`` so the generated L1 TOC
  reflects the document outline and search hits get a ``section_xpath``.
* Lists, quotes and fenced code are flattened into text paragraphs; nothing is
  silently dropped.
* All content is XML-escaped; the converter never trusts input markup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from xml.sax.saxutils import escape

from doclang import DocLangXDocument
from docling_context import ConversionResult, PackageError

CONVERTER_VERSION = "1"

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
# Inline Markdown that adds noise to search text: links, emphasis, inline code.
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_INLINE = re.compile(r"(\*\*|__|\*|_|`)")


@dataclass(frozen=True, slots=True)
class Block:
    """One logical block extracted from the source."""

    kind: str  # "heading" | "text"
    text: str
    level: int = 0


def _clean_inline(text: str) -> str:
    text = _LINK.sub(r"\1", text)
    text = _INLINE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_markdown(source: str) -> list[Block]:
    """Split Markdown into heading and paragraph blocks.

    Blank lines end a paragraph; each list item is its own paragraph so search
    results point at the specific bullet rather than the whole list.
    """
    blocks: list[Block] = []
    paragraph: list[str] = []
    in_fence = False
    fence: list[str] = []

    def flush() -> None:
        if paragraph:
            text = _clean_inline(" ".join(paragraph))
            if text:
                blocks.append(Block("text", text))
            paragraph.clear()

    for raw in source.splitlines():
        line = raw.rstrip()
        if _FENCE.match(line):
            if in_fence:
                code = "\n".join(fence).strip()
                if code:
                    blocks.append(Block("text", code))
                fence.clear()
            else:
                flush()
            in_fence = not in_fence
            continue
        if in_fence:
            fence.append(line)
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            blocks.append(Block("heading", _clean_inline(heading.group(2)), len(heading.group(1))))
        elif not line.strip():
            flush()
        elif _LIST.match(line):
            flush()
            paragraph.append(_LIST.sub("", line))
        else:
            paragraph.append(line.lstrip("> ").strip())
    if in_fence and fence:  # unterminated fence: keep the content anyway
        blocks.append(Block("text", "\n".join(fence).strip()))
    flush()
    return blocks


def blocks_to_doclang(blocks: list[Block], title: str | None = None) -> str:
    """Render blocks as DocLang XML; prepend ``title`` when the source has no heading."""
    parts = ["<doclang>"]
    if title and not any(block.kind == "heading" for block in blocks):
        parts.append(f'<heading level="1">{escape(title)}</heading>')
    for block in blocks:
        if block.kind == "heading":
            parts.append(f'<heading level="{block.level}">{escape(block.text)}</heading>')
        else:
            parts.append(f"<text>{escape(block.text)}</text>")
    if len(parts) == 1:
        parts.append("<text>Empty document</text>")
    parts.append("</doclang>")
    return "".join(parts)


class MarkdownConverter:
    """``docling_context.Converter`` implementation for ``.md`` and ``.txt``."""

    def __init__(self, *, max_file_bytes: int = 5_000_000):
        self.max_file_bytes = max_file_bytes

    def fingerprint_options(self) -> dict[str, object]:
        # The Ingestor hashes these options together with the source bytes. If the
        # options or converter version change, files are re-ingested; otherwise an
        # unchanged file is skipped (idempotent ingestion).
        return {"converter_version": CONVERTER_VERSION, "max_file_bytes": self.max_file_bytes}

    def convert(self, source: bytes, filename: str) -> ConversionResult:
        if len(source) > self.max_file_bytes:
            raise ValueError(f"{filename}: exceeds {self.max_file_bytes} bytes")
        try:
            text = source.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{filename}: not valid UTF-8 text") from exc

        title = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        xml = blocks_to_doclang(parse_markdown(text), title=title)
        document = DocLangXDocument()
        if not document.read_xml(xml):
            # Should not happen because all content is escaped; fail loudly if it does.
            raise PackageError(document.last_error() or "generated DocLang is invalid")
        return ConversionResult(
            package=document.write_bytes(),
            converter="dcuc-markdown",
            version=CONVERTER_VERSION,
            options=self.fingerprint_options(),
        )
