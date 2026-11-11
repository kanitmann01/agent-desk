"""The corporate LLM endpoint adapter, shared by every model caller.

One module, one posture: the endpoint is OpenAI-compatible, configured
from the environment (AGENTDESK_LLM_BASE, AGENTDESK_LLM_KEY,
AGENTDESK_LLM_MODEL), every call is a plain POST with a short timeout,
and every failure raises so the caller can degrade in its own language.
No telemetry, no retry storms: one attempt per ask.
"""

import json
import os
import urllib.error
import urllib.request

REQUEST_TIMEOUT_S = 10
DEFAULT_MODEL = "gpt-4o-mini"


class LlmUnavailable(Exception):
    """No endpoint is configured, or the call did not go through."""


def env_config() -> tuple[str, str, str]:
    """(base_url, api_key, model) from the environment; base may be ''."""
    return (
        os.environ.get("AGENTDESK_LLM_BASE", ""),
        os.environ.get("AGENTDESK_LLM_KEY", ""),
        os.environ.get("AGENTDESK_LLM_MODEL", DEFAULT_MODEL),
    )


def chat(base_url: str, api_key: str, model: str, prompt: str) -> str:
    """One completion against the OpenAI-compatible chat endpoint."""
    if not base_url:
        raise LlmUnavailable("no corporate endpoint configured")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]
    except LlmUnavailable:
        raise
    except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError) as exc:
        raise LlmUnavailable(f"the company endpoint did not answer: {exc}") from exc


def env_chat():
    """A prompt-to-text callable bound to the environment config."""
    base_url, api_key, model = env_config()

    def complete(prompt: str) -> str:
        return chat(base_url, api_key, model, prompt)

    return complete
