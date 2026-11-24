"""The corporate LLM endpoint adapter, shared by every model caller.

One module, one posture: the endpoint is OpenAI-compatible, configured
from the settings rows (llm_base, llm_key, llm_model) over the
environment (AGENTDESK_LLM_BASE, AGENTDESK_LLM_KEY,
AGENTDESK_LLM_MODEL), every call is a plain POST with a short timeout,
and every failure raises so the caller can degrade in its own language.
No telemetry, no retry storms: one attempt per ask.

Every failure carries a short plain-language cause (never a traceback),
so the surfaces can show exactly what happened: a redirect to a login
page, an HTML portal where the API base should be, a rejected key, a
host that does not resolve. Redirects are never followed: a 3xx is an
answer to report, not a hop to chase.
"""

import http.client
import json
import os
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit

REQUEST_TIMEOUT_S = 10
DEFAULT_MODEL = "gpt-4o-mini"

# The pinned cause vocabulary. Every surface (settings test, research
# bar, assistant, wizard) shows one of these strings as-is, so the words
# live here once and nowhere else.
NO_ENDPOINT_CAUSE = "no AI connection is saved"
NO_SCHEME_CAUSE = (
    "the base URL must start with http:// or https://, "
    "for example https://llm.yourcompany.example/v1"
)
NO_HOST_CAUSE = (
    "the base URL is missing its host, the part right after https://, "
    "for example https://llm.yourcompany.example/v1"
)
REDIRECT_CAUSE = "the AI provider answered a redirect (possibly a login page), not an API"
WEB_PAGE_CAUSE = (
    "the AI provider answered a web page, not the API; check the base URL "
    "is the API base, not the portal"
)
NOT_API_BASE_CAUSE = (
    "the AI provider answered 404; the base URL is likely not the API "
    "base: it usually ends in the API version, like /v1"
)
BAD_SHAPE_CAUSE = (
    "the AI provider answered JSON that is not an OpenAI chat reply; check "
    "the base URL is an OpenAI-compatible base, usually ending in /v1"
)


class LlmUnavailable(Exception):
    """No endpoint is configured, or the call did not go through."""


class _NeverRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx is an answer to classify, not a hop to follow: an SSO
    portal redirect must be named to the user, never chased into a
    login page the adapter cannot answer."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Refuse every redirect, so the 3xx surfaces as an HTTPError.

        urllib follows a redirect only when this returns a request; None makes it
        stop and raise, which is how an SSO portal is named instead of chased.
        """
        return None


_OPENER = urllib.request.build_opener(_NeverRedirect)


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


def base_url_problem(base: str) -> str:
    """Empty when the base URL is usable, else the named reason it is not.

    The whole requirement is an http(s) scheme and a host; the path is
    the caller's to get right and is never rewritten here. An empty
    base is fine: that is the documented unconfigured state. A URL
    urlsplit cannot even parse (an unclosed IPv6 bracket, say) is the
    no-scheme refusal: it is not a usable address either way."""
    base = (base or "").strip()
    if not base:
        return ""
    try:
        parts = urlsplit(base)
    except ValueError:
        return NO_SCHEME_CAUSE
    if parts.scheme not in ("http", "https"):
        return NO_SCHEME_CAUSE
    if not parts.hostname:
        return NO_HOST_CAUSE
    return ""


_AZURE_API_KEY_HOST_SUFFIXES = (
    ".openai.azure.com",
    ".services.ai.azure.com",
    ".cognitiveservices.azure.com",
    ".azure-api.net",
)


def uses_azure_api_key(base_url: str) -> bool:
    """True when the base host is an Azure / Foundry API host.

    Those hosts expect the ``api-key`` header; everything else keeps
    ``Authorization: Bearer``. Matching is case-insensitive on the
    hostname only; ports and paths are ignored. Empty or unparseable
    bases are not Azure.
    """
    try:
        host = (urlsplit(base_url or "").hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    for suffix in _AZURE_API_KEY_HOST_SUFFIXES:
        apex = suffix[1:]  # strip leading dot
        if host == apex or host.endswith(suffix):
            return True
    return False


def auth_headers(base_url: str, api_key: str) -> dict[str, str]:
    """Request headers for one chat call: Azure api-key or Bearer."""
    headers = {"Content-Type": "application/json"}
    if uses_azure_api_key(base_url):
        headers["api-key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _host_of(base_url: str) -> str:
    """The host (with port) the causes name, or "". The userinfo that
    may ride in a URL (user:pass@) is dropped here and never echoed
    into a cause or the audit log; an unparseable address names no
    host, and the causes fall back to their own words."""
    try:
        parts = urlsplit(base_url)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return ""
    return f"{host}:{port}" if port is not None else host


def _http_cause(code: int) -> str:
    """The cause for one HTTP status the endpoint answered with."""
    if 300 <= code < 400:
        return REDIRECT_CAUSE
    if code in (401, 403):
        return f"the AI provider rejected the API key (HTTP {code}); check the key"
    if code == 404:
        return NOT_API_BASE_CAUSE
    if 500 <= code < 600:
        return (
            f"the AI provider failed on its own side (HTTP {code}); nothing "
            "is wrong with the key or the base URL"
        )
    return f"the AI provider refused the request (HTTP {code})"


def transport_cause(exc: BaseException, host: str = "",
                    timeout: float | None = None) -> str:
    """The plain-language cause of one transport failure: DNS, TLS, a
    timeout, a refused port, or the endpoint not answering. Short
    strings the surfaces show as-is; never a traceback."""
    if isinstance(exc, socket.gaierror):
        return (
            f"could not resolve the host {host or 'in the base URL'}: "
            "check the base URL spelling, or the network"
        )
    if isinstance(exc, ssl.SSLError):
        return (
            "could not open a secure connection to the AI provider's host "
            "(TLS failed): check that the address and port are right"
        )
    if isinstance(exc, (socket.timeout, TimeoutError)):
        waited = f"{timeout:g} seconds" if timeout is not None else "the waiting period"
        return f"the AI provider did not answer within {waited} (timeout)"
    if isinstance(exc, ConnectionRefusedError):
        return (
            f"the AI provider's host refused the connection: nothing is "
            f"listening at {host or 'that address'}"
        )
    return f"the AI provider did not answer: {exc}"


def _reply_text(raw: str, content_type: str) -> str:
    """The assistant message from one endpoint reply, or the named
    cause it is not one: an HTML page is a portal answer, and anything
    that is not an OpenAI chat object is a wrong-shape answer."""
    if "html" in content_type.lower() or raw.lstrip().lower().startswith("<"):
        raise LlmUnavailable(WEB_PAGE_CAUSE)
    try:
        body = json.loads(raw)
    except ValueError:
        raise LlmUnavailable(BAD_SHAPE_CAUSE) from None
    choices = body.get("choices") if isinstance(body, dict) else None
    message = (
        choices[0].get("message")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict)
        else None
    )
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise LlmUnavailable(BAD_SHAPE_CAUSE)
    return content


def chat(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout: float = REQUEST_TIMEOUT_S,
    max_tokens: int | None = None,
    extra_headers: dict | None = None,
) -> str:
    """One completion against the OpenAI-compatible chat endpoint.

    extra_headers are the connection's gateway headers (spec 018): they
    ride on top of the auth headers, so a corporate gateway that needs
    its own header (even one named Authorization) is served as written.
    """
    if not base_url:
        raise LlmUnavailable(NO_ENDPOINT_CAUSE)
    problem = base_url_problem(base_url)
    if problem:
        raise LlmUnavailable(problem)
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    headers = auth_headers(base_url, api_key)
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    host = _host_of(base_url)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            content_type = response.headers.get("Content-Type", "")
        return _reply_text(raw, content_type)
    except LlmUnavailable:
        raise
    except urllib.error.HTTPError as exc:
        raise LlmUnavailable(_http_cause(exc.code)) from exc
    except urllib.error.URLError as exc:
        raise LlmUnavailable(
            transport_cause(exc.reason, host=host, timeout=timeout)
        ) from exc
    except http.client.HTTPException as exc:
        # Broken responses http.client raises without an OSError
        # wrapper: a non-HTTP answer (BadStatusLine), a truncated body
        # (IncompleteRead), a nonnumeric port (InvalidURL). Classified
        # like any transport failure, never a raw escape.
        raise LlmUnavailable(transport_cause(exc, host=host, timeout=timeout)) from exc
    except OSError as exc:
        # Timeouts and resets that escape URLError arrive bare.
        raise LlmUnavailable(transport_cause(exc, host=host, timeout=timeout)) from exc


def chat_client(base_url: str, api_key: str, model: str,
                extra_headers: dict | None = None):
    """A prompt-to-text callable bound to one endpoint config."""
    def complete(prompt: str, timeout: float = REQUEST_TIMEOUT_S) -> str:
        """One completion against the endpoint this client was built with.

        Callers that omit timeout keep the 10 second cap. The presentation
        agent passes its own, longer, timeout.
        """
        return chat(base_url, api_key, model, prompt, timeout=timeout,
                    extra_headers=extra_headers)

    return complete


def env_chat():
    """A prompt-to-text callable bound to the environment config."""
    return chat_client(*env_config())


def settings_chat(settings_store=None):
    """A prompt-to-text callable that resolves settings over env on every
    call, so an endpoint saved in the app applies without a restart.

    The explicit timeout parameter (spec 018 #233) is the one adapters
    honor by contract: a caller hands the seconds it is willing to wait
    and the socket cap is really set to them, which is what let the
    presentations pipeline drop the introspection it used to paper over
    this closure's fixed cap.
    """
    def complete(prompt: str, timeout: float = REQUEST_TIMEOUT_S) -> str:
        """One completion, resolving the endpoint from settings over env right now."""
        base, key, model = effective_llm_config(settings_store)
        return chat(base, key, model, prompt, timeout=timeout)

    return complete

