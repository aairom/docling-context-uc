"""Typed application settings.

All values come from environment variables (optionally loaded from ``.env``).
Nothing environment-specific is hard-coded in the application code: defaults
here are safe, local-only values that mirror ``.env.example``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _bool(name: str, default: bool) -> bool:
    """Parse a boolean env var strictly so typos fail loudly instead of silently."""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"{name} must be a boolean (true/false), got {raw!r}")


def _int(name: str, default: int, *, low: int, high: int) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw in (None, "") else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}, got {value}")
    return value


@dataclass(frozen=True, slots=True)
class LLMSettings:
    """Connection details for an OpenAI-compatible *local* LLM server."""

    base_url: str = ""
    model: str = "local-model"
    # repr=False keeps the key out of logs and tracebacks.
    api_key: str = field(default="", repr=False)
    timeout_seconds: int = 60
    use_for_summaries: bool = False

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the pipeline, CLI and UI need, resolved once at start-up."""

    tenant_id: str = "demo"
    user_id: str = "local"
    input_dir: Path = Path("./input")
    output_dir: Path = Path("./output")
    store_dir: Path = Path("./context-data")
    collection: str = "knowledge"
    enable_conversion: bool = False
    enable_vectors: bool = False
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    llm: LLMSettings = field(default_factory=LLMSettings)
    app_host: str = "127.0.0.1"
    app_port: int = 7860
    log_level: str = "INFO"

    def with_overrides(self, **changes: object) -> Settings:
        """Return a copy with selected fields replaced (used by the CLI and tests)."""
        return replace(self, **changes)  # type: ignore[arg-type]

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> Settings:
        """Build settings from the process environment.

        ``.env`` is loaded first but never overrides variables already exported
        in the shell, so CI and containers keep full control.
        """
        if env_file is not None and Path(env_file).is_file():
            load_dotenv(env_file, override=False)

        port = _int("APP_PORT", 7860, low=1024, high=65535)
        if port == 5000:
            # Port 5000 is taken by AirDrop/ControlCenter on macOS.
            raise ValueError("APP_PORT 5000 is reserved on macOS; choose another port")

        llm = LLMSettings(
            base_url=os.getenv("LLM_BASE_URL", "").strip().rstrip("/"),
            model=os.getenv("LLM_MODEL", "local-model").strip() or "local-model",
            api_key=os.getenv("LLM_API_KEY", ""),
            timeout_seconds=_int("LLM_TIMEOUT_SECONDS", 60, low=1, high=600),
            use_for_summaries=_bool("LLM_SUMMARIES", False),
        )
        return cls(
            tenant_id=os.getenv("DC_TENANT_ID", "demo"),
            user_id=os.getenv("DC_USER_ID", "local"),
            input_dir=Path(os.getenv("DC_INPUT_DIR", "./input")),
            output_dir=Path(os.getenv("DC_OUTPUT_DIR", "./output")),
            store_dir=Path(os.getenv("DC_STORE_DIR", "./context-data")),
            collection=os.getenv("DC_COLLECTION", "knowledge"),
            enable_conversion=_bool("DC_ENABLE_CONVERSION", False),
            enable_vectors=_bool("DC_ENABLE_VECTORS", False),
            embedding_model=os.getenv("DC_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
            llm=llm,
            app_host=os.getenv("APP_HOST", "127.0.0.1"),
            app_port=port,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
