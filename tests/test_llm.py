import json

import httpx
import pytest
from doclang import DocLangXDocument

from dcuc.config import LLMSettings
from dcuc.llm import LLMClient, LLMError, validate_endpoint
from dcuc.summaries import LLMSummaryProvider, document_text

from .conftest import fake_llm


@pytest.mark.parametrize(
    "url", ["http://localhost:9931/v1", "http://127.0.0.1:8080/v1", "https://llm.example.com/v1"]
)
def test_allowed_endpoints(url):
    assert validate_endpoint(url) == url


@pytest.mark.parametrize("url", ["http://10.0.0.5/v1", "ftp://localhost", "localhost:1"])
def test_rejected_endpoints(url):
    with pytest.raises(LLMError):
        validate_endpoint(url)


def test_disabled_settings_cannot_build_client():
    with pytest.raises(LLMError):
        LLMClient(LLMSettings())


def test_chat_sends_openai_payload_and_auth_header():
    client, seen = fake_llm("Hello")
    assert client.chat("sys", "user msg") == "Hello"
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/v1/chat/completions"
    assert seen[0].headers["Authorization"] == "Bearer test-key"
    assert body["messages"][1] == {"role": "user", "content": "user msg"}
    assert client.ping() is True
    client.close()


@pytest.mark.parametrize(
    "response",
    [httpx.Response(500), httpx.Response(200, json={"oops": 1}), httpx.Response(200, text="nope"),
     httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]})],
)
def test_bad_responses_raise_llm_error(response):
    client = LLMClient(LLMSettings(base_url="http://localhost:1/v1"),
                       transport=httpx.MockTransport(lambda _: response))
    with pytest.raises(LLMError):
        client.chat("s", "u")


def test_network_errors_raise_llm_error():
    def boom(_):
        raise httpx.ConnectError("refused")

    client = LLMClient(LLMSettings(base_url="http://localhost:1/v1"),
                       transport=httpx.MockTransport(boom))
    with pytest.raises(LLMError):
        client.chat("s", "u")
    assert client.ping() is False


def _doc(xml: str) -> DocLangXDocument:
    document = DocLangXDocument()
    assert document.read_xml(xml)
    return document


def test_document_text_is_bounded():
    document = _doc("<doclang><heading>T</heading><text>" + "word " * 500 + "</text></doclang>")
    assert len(document_text(document, limit=100)) == 100


def test_summary_provider_escapes_llm_output():
    client, _ = fake_llm("Summary with <tags> & ampersand")
    summary = LLMSummaryProvider(client).summarize(_doc("<doclang><text>x</text></doclang>"), "r1")
    assert summary == "<doclang><text>Summary with &lt;tags&gt; &amp; ampersand</text></doclang>"
    assert DocLangXDocument().read_xml(summary)


def test_summary_provider_rejects_empty_documents():
    client, _ = fake_llm()
    with pytest.raises(ValueError):
        LLMSummaryProvider(client).summarize(_doc("<doclang></doclang>"), "r1")
