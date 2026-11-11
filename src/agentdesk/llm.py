"""The corporate LLM endpoint adapter, shared by every model caller.

One module, one posture: the endpoint is OpenAI-compatible, configured
from the settings rows (llm_base, llm_key, llm_model) over the
environment (AGENTDESK_LLM_BASE, AGENTDESK_LLM_KEY,
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


def effective_llm_config(settings_store=None) -> tuple[str, str, str]:
    """(base, key, model) with the saved settings over env/config.env.

    A non-empty settings row wins; empty rows fall through to the
    environment. Resolved per call, so saving an endpoint in the app
    applies without a restart.
    """
    base, key, model = env_config()
    if settings_store is not None:
        s_base = settings_store.get("llm_base")
        s_key = settings_store.get("llm_key")
        s_model = settings_store.get("llm_model")
        if s_base:
            base = s_base
        if s_key:
            key = s_key
        if s_model:
            model = s_model
    return base, key, model


def chat(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout: float = REQUEST_TIMEOUT_S,
    max_tokens: int | None = None,
) -> str:
    """One completion against the OpenAI-compatible chat endpoint."""
    if not base_url:
        raise LlmUnavailable("no corporate endpoint configured")
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]
    except LlmUnavailable:
        raise
    except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError) as exc:
        raise LlmUnavailable(f"the company endpoint did not answer: {exc}") from exc


def chat_client(base_url: str, api_key: str, model: str):
    """A prompt-to-text callable bound to one endpoint config."""
    def complete(prompt: str) -> str:
        return chat(base_url, api_key, model, prompt)

    return complete


def env_chat():
    """A prompt-to-text callable bound to the environment config."""
    return chat_client(*env_config())


def settings_chat(settings_store=None):
    """A prompt-to-text callable that resolves settings over env on every
    call, so an endpoint saved in the app applies without a restart."""
    def complete(prompt: str) -> str:
        base, key, model = effective_llm_config(settings_store)
        return chat(base, key, model, prompt)

    return complete
