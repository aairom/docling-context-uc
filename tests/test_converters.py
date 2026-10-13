import pytest
from doclang import DocLangXDocument
from docling_context import PackageError

from dcuc.converters import MarkdownConverter, blocks_to_doclang, parse_markdown


def _nodes(package: bytes):
    document = DocLangXDocument()
    assert document.read_bytes(package)
    return [n for n in document.iter_nodes(None, limit=100, max_text_chars=500)
            if n["name"] in {"heading", "text"}]


def test_parse_headings_paragraphs_and_lists():
    blocks = parse_markdown(
        "# Title\n\nFirst **bold** line\ncontinued [link](http://x).\n\n- one\n- two\n\n## Sub\n"
    )
    assert [(b.kind, b.text, b.level) for b in blocks] == [
        ("heading", "Title", 1),
        ("text", "First bold line continued link.", 0),
        ("text", "one", 0),
        ("text", "two", 0),
        ("heading", "Sub", 2),
    ]


def test_code_fences_are_kept_verbatim():
    blocks = parse_markdown("text\n```\n# not a heading\nx = 1\n```\n")
    assert blocks[-1].text == "# not a heading\nx = 1"
    assert all(b.kind == "text" for b in blocks)


def test_unterminated_fence_is_not_dropped():
    assert parse_markdown("```\nleft open")[-1].text == "left open"


def test_xml_is_escaped():
    xml = blocks_to_doclang(parse_markdown("# A & B\n\n<script>x</script>"))
    assert "<script>" not in xml and "&lt;script&gt;" in xml and "A &amp; B" in xml


def test_title_added_only_without_headings():
    assert '<heading level="1">notes</heading>' in blocks_to_doclang(parse_markdown("hi"), "notes")
    assert "notes" not in blocks_to_doclang(parse_markdown("# Real"), "notes")


def test_empty_source_produces_valid_document():
    # The filename becomes the title heading, so the document is never empty.
    result = MarkdownConverter().convert(b"", "empty.md")
    assert [n["text"] for n in _nodes(result.package)] == ["empty"]
    assert "Empty document" in blocks_to_doclang([])  # placeholder without a title


def test_convert_round_trip_and_metadata():
    result = MarkdownConverter().convert("# Héllo\n\nWörld".encode(), "greet.md")
    assert result.converter == "dcuc-markdown"
    assert [n["text"] for n in _nodes(result.package)] == ["Héllo", "Wörld"]


def test_convert_rejects_binary_and_oversized():
    with pytest.raises(ValueError):
        MarkdownConverter().convert(b"\xff\xfe\x00bad", "bin.txt")
    with pytest.raises(ValueError):
        MarkdownConverter(max_file_bytes=4).convert(b"too long", "big.md")


def test_package_error_is_the_library_type():
    # The pipeline catches docling_context.PackageError; make sure it is importable.
    assert issubclass(PackageError, Exception)
