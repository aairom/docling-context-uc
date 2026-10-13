import json
from datetime import datetime
from pathlib import Path

from dcuc.pipeline import Answer, Citation, FileOutcome, IngestReport
from dcuc.reporting import (
    answer_markdown,
    ingest_markdown,
    search_markdown,
    timestamp,
    write_report,
)

NOW = datetime(2026, 1, 2, 3, 4, 5)


def test_timestamp_format():
    assert timestamp(NOW) == "20260102-030405"


def test_write_report_pair_is_timestamped_and_atomic(tmp_path: Path):
    out = tmp_path / "output"  # created on demand
    report = IngestReport("knowledge", 1.0, 2.5, [FileOutcome("a|b.md", "docling://x", "ingested")])
    json_path, md_path = write_report(out, "ingest", report, ingest_markdown(report), now=NOW)
    assert json_path.name == "20260102-030405_ingest.json"
    assert md_path.name == "20260102-030405_ingest.md"
    assert json.loads(json_path.read_text())["files"][0]["status"] == "ingested"
    assert "a\\|b.md" in md_path.read_text()  # table cells are escaped
    assert not list(out.glob(".tmp-*"))


def test_answer_and_search_markdown():
    citation = Citation(1, "docling://resources/k/doc", "/doclang[1]/text[1]", 2, 0.9, "text",
                        "d", "r")
    answer = Answer("Q?", "A [1]", "llm", [citation], "s1")
    md = answer_markdown(answer)
    assert "# Q&A - Q?" in md and "session `s1`" in md and "/doclang[1]/text[1]" in md
    assert "| 1 | 0.9 | 2 |" in search_markdown("q", [citation])
