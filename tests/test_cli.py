from pathlib import Path

import pytest

from dcuc.cli import main


@pytest.fixture
def cli_env(settings, monkeypatch):
    """Point the CLI at the per-test folders through environment variables."""
    monkeypatch.setenv("DC_INPUT_DIR", str(settings.input_dir))
    monkeypatch.setenv("DC_OUTPUT_DIR", str(settings.output_dir))
    monkeypatch.setenv("DC_STORE_DIR", str(settings.store_dir))
    return settings


def test_ingest_exit_code_and_report(cli_env, capsys):
    # One sample file is intentionally broken, so ingest reports failure (exit 1).
    assert main(["--env-file", "none", "ingest"]) == 1
    assert "Ingested: 4" in capsys.readouterr().out
    assert list(Path(cli_env.output_dir).glob("*_ingest.md"))
    (cli_env.input_dir / "policies" / "broken-example.dclg.xml").unlink()
    assert main(["--env-file", "none", "ingest", "--force"]) == 0


def test_search_ask_tree_show_status(cli_env, capsys):
    main(["--env-file", "none", "ingest"])
    capsys.readouterr()
    assert main(["--env-file", "none", "search", "refund", "-k", "2"]) == 0
    assert "refund-policy" in capsys.readouterr().out
    assert main(["--env-file", "none", "ask", "How do I rotate the API credentials?"]) == 0
    assert "credential-rotation" in capsys.readouterr().out
    assert main(["--env-file", "none", "tree"]) == 0
    assert "runbooks/" in capsys.readouterr().out
    assert main(["--env-file", "none", "show",
                 "docling://resources/knowledge/policies/refund-policy"]) == 0
    assert '"revision_id"' in capsys.readouterr().out
    assert main(["--env-file", "none", "status"]) == 0
    assert '"documents"' in capsys.readouterr().out
    assert sorted(p.name.split("_", 1)[1] for p in Path(cli_env.output_dir).glob("*.md")) == [
        "answer.md", "ingest.md", "search.md"]


def test_demo_command(cli_env, capsys):
    assert main(["--env-file", "none", "demo"]) == 0
    assert "Session transcript" in capsys.readouterr().out


def test_error_exit_codes(cli_env, monkeypatch):
    assert main(["--env-file", "none", "show", "docling://resources/knowledge/missing"]) == 1
    assert main(["--env-file", "none", "show", "http://not-a-context-uri"]) == 2
    assert main(["--env-file", "none", "--collection", "Bad Name", "status"]) == 1
    monkeypatch.setenv("APP_PORT", "5000")
    assert main(["--env-file", "none", "status"]) == 2
