"""Command line interface: ``uv run dcuc <command>``.

Commands
--------
``ingest``   recursively ingest ``input/`` and write a timestamped report
``search``   scoped search with citations
``ask``      retrieval-augmented answer (local LLM or extractive), session-logged
``tree``     print the context tree of the collection
``show``     print summary / TOC / provenance of one document
``status``   index, vector and collection-summary status
``demo``     run ingest + search + ask in one go (used by scripts/demo.sh)

Exit codes: 0 success, 1 runtime error, 2 usage/configuration error.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from docling_context import AccessDenied, InvalidURI, RecordMissing

from .config import Settings
from .logging_setup import configure_logging
from .pipeline import ContextPipeline
from .reporting import answer_markdown, ingest_markdown, search_markdown, write_report

log = logging.getLogger("dcuc")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dcuc", description=__doc__.split("\n")[0])
    parser.add_argument("--env-file", default=".env", help="dotenv file (default: .env)")
    parser.add_argument("--store", type=Path, help="override DC_STORE_DIR")
    parser.add_argument("--collection", help="override DC_COLLECTION")
    parser.add_argument("--no-llm", action="store_true", help="disable the LLM for this run")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="ingest the input folder recursively")
    ingest.add_argument("--input", type=Path, help="override DC_INPUT_DIR")
    ingest.add_argument("--force", action="store_true", help="re-ingest unchanged files")

    for name in ("search", "ask"):
        cmd = sub.add_parser(name)
        cmd.add_argument("query")
        cmd.add_argument("-k", type=int, default=5)
    sub.choices["search"].add_argument(
        "--mode", choices=("auto", "lexical", "vector", "hybrid"), default="auto")
    sub.choices["search"].add_argument("--uri", help="restrict to a URI subtree")
    sub.choices["ask"].add_argument("--session", help="session id to record the turn in")

    sub.add_parser("tree").add_argument("-L", "--depth", type=int, default=4)
    sub.add_parser("show").add_argument("uri")
    sub.add_parser("status")
    demo = sub.add_parser("demo", help="ingest + search + ask")
    demo.add_argument("--input", type=Path)
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env(args.env_file)
    changes: dict[str, object] = {}
    if args.store:
        changes["store_dir"] = args.store
    if args.collection:
        changes["collection"] = args.collection
    if getattr(args, "input", None):
        changes["input_dir"] = args.input
    if args.no_llm:
        changes["llm"] = settings.llm.__class__()  # empty base_url == disabled
    return settings.with_overrides(**changes) if changes else settings


def _print(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def run(args: argparse.Namespace, pipeline: ContextPipeline) -> int:
    settings = pipeline.settings
    out = settings.output_dir
    if args.command in ("ingest", "demo"):
        report = pipeline.ingest_directory(force=getattr(args, "force", False))
        json_path, md_path = write_report(out, "ingest", report, ingest_markdown(report))
        print(ingest_markdown(report))
        print(f"Report: {md_path}")
        if args.command == "ingest":
            return 1 if report.count("failed") else 0
        # Demo: run two representative queries against the sample corpus.
        session = pipeline.start_session()
        for question in ("How do I rotate the API credentials?", "What is the refund policy?"):
            answer = pipeline.ask(question, session_id=session)
            _, md = write_report(out, "answer", answer, answer_markdown(answer))
            print(answer_markdown(answer))
            print(f"Report: {md}")
        print(f"Session transcript ({session}): {len(pipeline.session_transcript(session))} events")
        return 0
    if args.command == "search":
        result = pipeline.search(args.query, k=args.k, mode=args.mode, uri=args.uri)
        citations = pipeline.to_citations(result)
        _, md = write_report(out, "search", {"query": args.query, "hits": citations},
                             search_markdown(args.query, citations))
        print(search_markdown(args.query, citations))
        print(f"{len(citations)} of {result.total_hits} matching nodes, "
              f"{result.tokens_used} tokens")
        print(f"Report: {md}")
        return 0
    if args.command == "ask":
        session = args.session or pipeline.start_session()
        answer = pipeline.ask(args.query, k=args.k, session_id=session)
        _, md = write_report(out, "answer", answer, answer_markdown(answer))
        print(answer_markdown(answer))
        print(f"Report: {md}")
        return 0
    if args.command == "tree":
        for entry in pipeline.tree(depth=args.depth):
            indent = "  " * (int(entry["depth"]) - 1)
            marker = "/" if entry["kind"] == "directory" else ""
            print(f"{indent}{str(entry['uri']).rsplit('/', 1)[-1]}{marker}")
        return 0
    if args.command == "show":
        _print(pipeline.document_overview(args.uri))
        return 0
    if args.command == "status":
        _print(pipeline.status())
        return 0
    raise AssertionError(f"unhandled command {args.command}")  # argparse prevents this


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = _settings(args)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    configure_logging(settings.log_level)
    try:
        with ContextPipeline(settings) as pipeline:
            return run(args, pipeline)
    except (InvalidURI, AccessDenied) as exc:
        log.error("Invalid or unauthorised URI: %s", exc)
        return 2
    except RecordMissing as exc:
        log.error("Not found: %s", exc)
        return 1
    except (FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        log.warning("Interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
