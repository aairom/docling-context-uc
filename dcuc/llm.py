"""Minimal client for an OpenAI-compatible *local* LLM (llama.cpp, Ollama, ...).

Only ``/chat/completions`` is used. The client is intentionally small:

* the endpoint is restricted to loopback HTTP or HTTPS so prompts containing
  document content are never sent over plain HTTP to a remote host;
* responses are size-bounded and parsed defensively;
* every failure surfaces as :class:`LLMError`, letting callers fall back to
  extractive behaviour instead of crashing.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from .config import LLMSettings

log = logging.getLogger(__name__)

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
MAX_RESPONSE_BYTES = 2_000_000


class LLMError(RuntimeError):
    """The LLM is unreachable, misconfigured, or returned an unusable answer."""


def validate_endpoint(base_url: str) -> str:
    """Allow HTTPS anywhere, plain HTTP only on loopback."""
    parsed = urlparse(base_url)
    if parsed.scheme == "https" and parsed.hostname:
        return base_url
    if parsed.scheme == "http" and parsed.hostname in _LOOPBACK:
        return base_url
    raise LLMError("LLM_BASE_URL must be HTTPS or loopback HTTP (e.g. http://localhost:9931/v1)")


class LLMClient:
    def __init__(self, settings: LLMSettings, *, transport: httpx.BaseTransport | None = None):
        if not settings.enabled:
            raise LLMError("LLM is disabled (LLM_BASE_URL is empty)")
        self.settings = settings
        headers = {"Content-Type": "application/json"}
        if settings.api_key:
            headers["Authorization"] = f"Bearer {settings.api_key}"
        # `transport` lets tests inject httpx.MockTransport without a server.
        self._client = httpx.Client(
            base_url=validate_endpoint(settings.base_url),
            headers=headers,
            timeout=settings.timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> LLMClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def chat(
        self, system: str, user: str, *, max_tokens: int = 512, temperature: float = 0.1
    ) -> str:
        payload = {
            "model": self.settings.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        try:
            response = self._client.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc.__class__.__name__}") from exc
        if response.status_code != 200:
            raise LLMError(f"LLM returned HTTP {response.status_code}")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise LLMError("LLM response is too large")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response is not an OpenAI-style chat completion") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM returned an empty answer")
        return content.strip()

    def ping(self) -> bool:
        """Return True if the server answers ``/models``; never raises."""
        try:
            return self._client.get("/models", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False
