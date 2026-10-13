"""Shared fixtures: an isolated store, input folder and settings per test."""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

from dcuc.config import LLMSettings, Settings
from dcuc.llm import LLMClient
from dcuc.pipeline import ContextPipeline

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make tests independent of the developer's shell and .env file."""
    for name in (
        "DC_TENANT_ID", "DC_USER_ID", "DC_INPUT_DIR", "DC_OUTPUT_DIR", "DC_STORE_DIR",
        "DC_COLLECTION", "DC_ENABLE_CONVERSION", "DC_ENABLE_VECTORS", "LLM_BASE_URL",
        "LLM_MODEL", "LLM_API_KEY", "LLM_SUMMARIES", "LLM_TIMEOUT_SECONDS", "APP_PORT",
        "APP_HOST", "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    input_dir = tmp_path / "input"
    shutil.copytree(SAMPLES, input_dir)
    return Settings(
        input_dir=input_dir,
        output_dir=tmp_path / "output",
        store_dir=tmp_path / "store",
        llm=LLMSettings(),  # disabled
    )


@pytest.fixture
def pipeline(settings: Settings):
    with ContextPipeline(settings) as p:
        yield p


def fake_llm(reply: str = "Mocked answer [1].", status: int = 200) -> tuple[LLMClient, list]:
    """An LLMClient backed by httpx.MockTransport; returns (client, captured_requests)."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(status, json={"choices": [{"message": {"content": reply}}]})

    client = LLMClient(
        LLMSettings(base_url="http://localhost:9931/v1", api_key="test-key"),
        transport=httpx.MockTransport(handler),
    )
    return client, seen
