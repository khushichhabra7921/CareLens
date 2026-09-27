"""The Groq client, with urllib's network call replaced (no real requests)."""

import io
import json
import urllib.error

import pytest

from app.llm import client as client_module
from app.llm.client import GroqClient, LLMError, LLMTimeout

KEY = "gsk_test_key_do_not_log"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_urlopen(behaviour, seen):
    def urlopen(request, timeout):
        seen.append((request, timeout))
        if isinstance(behaviour, Exception):
            raise behaviour
        return FakeResponse(json.dumps(behaviour).encode())
    return urlopen


def call(monkeypatch, behaviour):
    seen = []
    monkeypatch.setattr(client_module.urllib.request, "urlopen", fake_urlopen(behaviour, seen))
    result = GroqClient(KEY, "test-model", timeout_seconds=7).complete(
        [{"role": "user", "content": "hi"}])
    return result, seen


def test_success_parses_content_and_token_usage(monkeypatch):
    body = {"choices": [{"message": {"content": '{"a": 1}'}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16}}
    result, seen = call(monkeypatch, body)
    assert (result.content, result.total_tokens, result.prompt_tokens) == ('{"a": 1}', 16, 11)
    request, timeout = seen[0]
    sent = json.loads(request.data)
    assert timeout == 7
    assert sent["response_format"] == {"type": "json_object"} and sent["model"] == "test-model"
    assert request.get_header("Authorization") == f"Bearer {KEY}"


@pytest.mark.parametrize("error, expected", [
    (TimeoutError(), LLMTimeout),
    (urllib.error.URLError(TimeoutError()), LLMTimeout),
    (urllib.error.URLError("no route"), LLMError),
    (urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None), LLMError),
])
def test_network_errors_become_llm_errors_without_the_key(monkeypatch, error, expected):
    with pytest.raises(expected) as caught:
        call(monkeypatch, error)
    assert KEY not in str(caught.value)


def test_unexpected_response_shape_is_an_error(monkeypatch):
    with pytest.raises(LLMError, match="unexpected response shape"):
        call(monkeypatch, {"choices": []})
