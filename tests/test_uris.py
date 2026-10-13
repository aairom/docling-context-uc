from pathlib import Path

import pytest
from docling_context import parse_uri

from dcuc.uris import classify, slug, strip_suffix, uri_for, validate_collection


def test_slug_keeps_safe_names():
    assert slug("guide") == "guide"
    assert slug("v1.2_notes") == "v1.2_notes"


def test_slug_hashes_changed_names_to_avoid_collisions():
    a, b = slug("support hours"), slug("support-hours ")
    assert a.startswith("support-hours-") and b.startswith("support-hours-")
    assert a != b


def test_slug_rejects_empty():
    with pytest.raises(ValueError):
        slug("...")


@pytest.mark.parametrize(
    ("name", "expected"),
    [("a.dclg.xml", "a"), ("a.md", "a"), ("report.final.pdf", "report.final"), ("x", "x")],
)
def test_strip_suffix(name, expected):
    assert strip_suffix(name) == expected


@pytest.mark.parametrize(
    ("name", "kind"),
    [("a.dclx", "native"), ("A.DCLG.XML", "native"), ("n.md", "text"), ("t.txt", "text"),
     ("p.pdf", "docling"), ("d.docx", "docling"), ("x.exe", None)],
)
def test_classify(name, kind):
    assert classify(Path(name)) == kind


def test_uri_mirrors_folder_layout(tmp_path: Path):
    target = tmp_path / "eng" / "run books" / "rotate.md"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    uri = uri_for(target, tmp_path, "knowledge")
    parsed = parse_uri(uri)
    assert parsed.namespace == "resources"
    assert parsed.segments[0] == "knowledge"
    assert parsed.segments[1] == "eng"
    assert parsed.segments[2].startswith("run-books-")
    assert parsed.segments[3] == "rotate"


def test_uri_rejects_paths_outside_base(tmp_path: Path):
    with pytest.raises(ValueError):
        uri_for(tmp_path.parent / "elsewhere.md", tmp_path, "knowledge")


@pytest.mark.parametrize("name", ["Knowledge", "_context", "", "a/b", "x" * 65])
def test_invalid_collections(name):
    with pytest.raises(ValueError):
        validate_collection(name)
