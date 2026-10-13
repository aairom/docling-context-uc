"""Timestamped reports written to ``output/``.

Every run produces a pair of files that share one timestamp prefix:
``<YYYYmmdd-HHMMSS>_<name>.json`` (machine-readable) and ``.md`` (human-readable).
Writes go to a temporary file first and are renamed, so a crash never leaves a
half-written report behind.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .pipeline import Answer, IngestReport


def timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"not serialisable: {type(value).__name__}")


def write_report(
    output_dir: Path, name: str, data: Any, markdown: str, *, now: datetime | None = None
) -> tuple[Path, Path]:
    """Write ``data`` as JSON and ``markdown`` as .md; return both paths."""
    stem = f"{timestamp(now)}_{name}"
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"
    _atomic_write(json_path, json.dumps(data, default=_jsonable, indent=2, ensure_ascii=False))
    _atomic_write(md_path, markdown)
    return json_path, md_path


def _cell(text: object) -> str:
    """Make a value safe for a Markdown table cell."""
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def ingest_markdown(report: IngestReport) -> str:
    lines = [
        f"# Ingestion report - collection `{report.collection}`",
        "",
        f"- Duration: {report.duration_seconds}s",
        f"- Ingested: {report.count('ingested')} | Unchanged: {report.count('unchanged')} | "
        f"Skipped: {report.count('skipped')} | Failed: {report.count('failed')}",
        f"- Collection summary jobs processed: {report.collection_jobs}",
        "",
        "| File | Status | URI | Summary | Detail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in report.files:
        lines.append(
            f"| {_cell(item.path)} | {item.status} | {_cell(item.uri)} | "
            f"{_cell(item.summary_method)} | {_cell(item.detail)} |"
        )
    return "\n".join(lines) + "\n"


def answer_markdown(answer: Answer) -> str:
    lines = [
        f"# Q&A - {answer.question}",
        "",
        f"_Method: {answer.method}_"
        + (f" - session `{answer.session_id}`" if answer.session_id else ""),
        "",
        answer.answer,
        "",
        "## Citations",
        "",
    ]
    for c in answer.citations:
        lines.append(f"{c.number}. `{c.uri}` `{c.xpath}` (tier {c.tier}, score {c.score})")
        lines.append(f"   > {c.text[:500]}")
    return "\n".join(lines) + "\n"


def search_markdown(query: str, citations: list) -> str:
    lines = [f"# Search - {query}", "", "| # | Score | Tier | URI | XPath | Text |",
             "| --- | --- | --- | --- | --- | --- |"]
    for c in citations:
        lines.append(f"| {c.number} | {c.score} | {c.tier} | {_cell(c.uri)} | {_cell(c.xpath)} | "
                     f"{_cell(c.text[:200])} |")
    return "\n".join(lines) + "\n"
