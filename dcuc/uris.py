"""Map files in ``input/`` to canonical ``docling://`` URIs.

docling-context rejects ambiguous URIs (encoded separators, ``..``, control
characters, ...). Instead of letting arbitrary filenames reach the store, we
derive a *slug* for each path segment and append a short hash whenever the
slug differs from the original, so two different filenames can never collapse
into the same URI. This mirrors the strategy used by the upstream ``dc`` CLI.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from docling_context import parse_uri

# Native DocLang sources are always ingestible; others need Docling conversion.
NATIVE_SUFFIXES = (".dclg.xml", ".dclg", ".dclx")
# Converted by the lightweight in-repo converter (no heavy dependencies).
TEXT_SUFFIXES = (".md", ".markdown", ".txt")
# Converted by Docling when the `conversion` extra is installed.
DOCLING_SUFFIXES = (
    ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".csv", ".asciidoc", ".adoc",
)

_COLLECTION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def slug(value: str) -> str:
    """Return a URI-safe segment; append a hash suffix when the value had to change."""
    result = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip(".-")
    if not result:
        raise ValueError(f"cannot derive a URI segment from {value!r}")
    if result != value:
        result += "-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return result


def validate_collection(name: str) -> str:
    """Collections are the first URI segment; keep them simple and lowercase.

    The ``_context`` name is reserved by docling-context for collection summaries.
    """
    if not _COLLECTION_RE.fullmatch(name):
        raise ValueError(
            "collection must be 1-64 chars of lowercase letters, digits, '-' or '_'"
        )
    return name


def strip_suffix(name: str) -> str:
    """Remove the (possibly double) extension, e.g. ``a.dclg.xml`` -> ``a``."""
    lower = name.lower()
    for suffix in (*NATIVE_SUFFIXES, *TEXT_SUFFIXES, *DOCLING_SUFFIXES):
        if lower.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return Path(name).stem or name


def classify(path: Path) -> str | None:
    """Return ``native``, ``text``, ``docling`` or ``None`` (unsupported)."""
    lower = path.name.lower()
    if lower.endswith(NATIVE_SUFFIXES):
        return "native"
    if lower.endswith(TEXT_SUFFIXES):
        return "text"
    if lower.endswith(DOCLING_SUFFIXES):
        return "docling"
    return None


def uri_for(path: Path, base: Path, collection: str) -> str:
    """Build ``docling://resources/<collection>/<sub/dirs>/<stem>`` for ``path``.

    Sub-folders of ``input/`` become URI path segments so the context tree mirrors
    the folder layout. The result is validated with the library's own parser.
    """
    validate_collection(collection)
    # Symlinks are deliberately NOT resolved here: the URI follows the name the
    # user sees, and the Ingestor's ``allowed_roots`` check (which does resolve
    # them) remains the single security boundary for reading files.
    relative = Path(os.path.abspath(path)).relative_to(os.path.abspath(base))
    segments = [slug(part) for part in relative.parts[:-1]]
    segments.append(slug(strip_suffix(relative.parts[-1])))
    uri = f"docling://resources/{collection}/{'/'.join(segments)}"
    return parse_uri(uri).value  # raises InvalidURI if anything slipped through
