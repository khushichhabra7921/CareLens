"""Minimal Groq chat-completions client using only the Python standard library.

One HTTPS POST: JSON body in, JSON body out, with a hard timeout and no automatic retries
(the report pipeline decides whether to retry, at most once).
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMError(Exception):
    """The LLM call failed (HTTP error, bad response). The message never contains the key."""


class LLMTimeout(LLMError):
    pass


@dataclass
class LLMResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class GroqClient:
    def __init__(self, api_key: str, model: str, timeout_seconds: float = 20,
                 max_completion_tokens: int = 1500, url: str = GROQ_URL):
        self._api_key = api_key
        self.model = model
        self.timeout = timeout_seconds
        self.max_completion_tokens = max_completion_tokens
        self.url = url

    def complete(self, messages: list[dict]) -> LLMResult:
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},   # Groq JSON mode
            "temperature": 0.2,                            # focused, repeatable wording
            "max_completion_tokens": self.max_completion_tokens,
        }).encode()
        request = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as err:
            raise LLMError(f"Groq returned HTTP {err.code}") from None
        except TimeoutError as err:   # (socket.timeout is the same class since Python 3.10)
            raise LLMTimeout(f"no response within {self.timeout}s") from err
        except urllib.error.URLError as err:
            if isinstance(err.reason, TimeoutError):
                raise LLMTimeout(f"no response within {self.timeout}s") from None
            raise LLMError("could not reach Groq") from None
        except json.JSONDecodeError:
            raise LLMError("Groq returned a non-JSON HTTP body") from None
        try:
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
        except (KeyError, IndexError, TypeError):
            raise LLMError("unexpected response shape") from None
        return LLMResult(content=content or "",
                         prompt_tokens=int(usage.get("prompt_tokens", 0)),
                         completion_tokens=int(usage.get("completion_tokens", 0)),
                         total_tokens=int(usage.get("total_tokens", 0)))
