"""Connection health (spec 018): the free model-list check and its mapping.

Testing a connection is a GET of the model list at its base URL with its
key: free, and independent of any model. The one-token completion
(max_tokens=1) exists only as the explicit deeper check for endpoints
without a listing; neither ever runs as part of saving. Every failure is
classified with the adapter's own plain-language vocabulary into the
outcomes the store and the badge consume:

- ok: the listing answered, so the key works; the models refresh the cache.
- limited: a 429 quota answer. The connection is fine; the note says so,
  because a quota answer is not an outage.
- error: 401/403 (the key was rejected), a redirect or a web page (the
  base URL points at a portal, not the API), or an answer whose shape is
  not a model list.
- transient: 5xx answers and transport failures (a timeout, DNS, a
  refused port). The last status keeps; one bad minute must not flip a
  badge that only a real answer should set.
- no-models: the endpoint has no listing to read (the Anthropic
  compatibility case). The key was verified neither way, so the stored
  status keeps; typing the model by hand or the deeper check is the
  answer, never a blocked save.

The requests follow the adapter's discipline exactly: urllib, one short
timeout read at call time, and redirects never followed (a portal hop is
named, not chased). The adapter's cause classifier, host helper and
never-redirect opener are used through their module rather than copied,
so the vocabulary stays the adapter's single source.
"""

import http.client
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from nexuusbot import llm
from nexuusbot.llm import (
    REDIRECT_CAUSE,
    REQUEST_TIMEOUT_S,
    auth_headers,
    base_url_problem,
    transport_cause,
)

# The outcome vocabulary the store, the routes and the badge consume.
OUTCOME_OK = "ok"
OUTCOME_ERROR = "error"
OUTCOME_LIMITED = "limited"
OUTCOME_TRANSIENT = "transient"
OUTCOME_NO_MODELS = "no-models"

# The two notes that are health's own (the adapter's chat path has no
# quota or listing semantics to name); every other cause reuses its
# strings verbatim, so the surfaces never show a second vocabulary.
LIMITED_NOTE = (
    "the AI provider is rate limiting this key (HTTP 429); the"
    " connection works, the quota is the limit"
)
NO_MODELS_NOTE = (
    "this AI provider offers no model listing; type the model by hand,"
    " run the deeper check to verify the key"
)
BAD_MODELS_SHAPE_CAUSE = (
    "the AI provider answered JSON that is not a model list; check the"
    " URL is an OpenAI-compatible base, usually ending in /v1"
)

# One timeout for both checks, resolved inside each call so a test can
# shorten it without touching the adapter's own constant.
CHECK_TIMEOUT_S = REQUEST_TIMEOUT_S


@dataclass
class ProbeResult:
    """One check's outcome: the mapped result, its plain-language cause
    (empty when all is well), and the discovered model ids when the
    listing answered."""

    outcome: str
    cause: str
    models: list[str] = field(default_factory=list)


def _headers(base_url: str, api_key: str, extra: dict | None,
             *, body: bool) -> dict[str, str]:
    """Request headers for one check: the adapter's auth decision (Azure
    api-key hosts versus Bearer everywhere else) plus the connection's
    gateway headers. No key means no auth header, the local-server case;
    a GET carries no Content-Type."""
    headers: dict[str, str] = {}
    if api_key:
        headers = auth_headers(base_url, api_key)
        if not body:
            headers.pop("Content-Type", None)
    elif body:
        headers["Content-Type"] = "application/json"
    headers.update(extra or {})
    return headers


def _transient(exc: BaseException, base_url: str, timeout: float) -> ProbeResult:
    """One transport failure in the adapter's own words."""
    return ProbeResult(
        OUTCOME_TRANSIENT,
        transport_cause(exc, host=llm._host_of(base_url), timeout=timeout),
    )


def _base_problem(base_url: str) -> ProbeResult | None:
    """The named refusal for an unusable base URL, or None when usable."""
    if not base_url:
        return ProbeResult(OUTCOME_ERROR, llm.NO_ENDPOINT_CAUSE)
    problem = base_url_problem(base_url)
    if problem:
        return ProbeResult(OUTCOME_ERROR, problem)
    return None


def _models_status_error(code: int) -> ProbeResult:
    """One HTTP failure of the model-list GET, in the badge's mapping.

    404 and 405 mean the endpoint has no listing to read, which is a
    state to name (manual entry, deeper check), not a broken key; every
    other 4xx keeps the adapter's own words for it.
    """
    if code in (401, 403):
        return ProbeResult(OUTCOME_ERROR, llm._http_cause(code))
    if code == 429:
        return ProbeResult(OUTCOME_LIMITED, LIMITED_NOTE)
    if code in (404, 405):
        return ProbeResult(OUTCOME_NO_MODELS, NO_MODELS_NOTE)
    if 300 <= code < 400:
        return ProbeResult(OUTCOME_ERROR, REDIRECT_CAUSE)
    if 500 <= code < 600:
        return ProbeResult(OUTCOME_TRANSIENT, llm._http_cause(code))
    return ProbeResult(OUTCOME_ERROR, llm._http_cause(code))


def _chat_status_error(code: int) -> ProbeResult:
    """One HTTP failure of the one-token completion: the adapter's chat
    classification (a 404 here really is a wrong API base, a redirect
    really is a portal), with the 429 quota answer mapped to the limited
    note like every other check."""
    if code == 429:
        return ProbeResult(OUTCOME_LIMITED, LIMITED_NOTE)
    if 500 <= code < 600:
        return ProbeResult(OUTCOME_TRANSIENT, llm._http_cause(code))
    return ProbeResult(OUTCOME_ERROR, llm._http_cause(code))


def _model_ids(body) -> list[str] | None:
    """The model ids in one listing answer: the OpenAI shape (an object
    with a data list of {id}), or a bare list of ids some gateways
    answer. None when the body is neither shape; an empty listing is
    still a listing and answers []."""
    items = None
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            items = data
    elif isinstance(body, list):
        items = body
    if items is None:
        return None
    return [
        item["id"] for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]


def _models_from_body(raw: str, content_type: str) -> ProbeResult:
    """A 200 models answer into its outcome: a portal page and a
    wrong-shape body are errors (the base URL is not the API), a readable
    listing is ok with its ids."""
    if "html" in content_type.lower() or raw.lstrip().lower().startswith("<"):
        return ProbeResult(OUTCOME_ERROR, llm.WEB_PAGE_CAUSE)
    try:
        body = json.loads(raw)
    except ValueError:
        return ProbeResult(OUTCOME_ERROR, BAD_MODELS_SHAPE_CAUSE)
    ids = _model_ids(body)
    if ids is None:
        return ProbeResult(OUTCOME_ERROR, BAD_MODELS_SHAPE_CAUSE)
    return ProbeResult(OUTCOME_OK, "", ids)


def check_models(
    base_url: str,
    api_key: str,
    extra_headers: dict | None = None,
    timeout: float | None = None,
) -> ProbeResult:
    """GET {base_url}/models with the connection's key and classify it.

    The free check: no completion is ever made here. The outcome, cause
    and discovered ids feed the store's health stamp and the models
    cache; nothing is raised, every failure is a ProbeResult.
    """
    timeout = CHECK_TIMEOUT_S if timeout is None else timeout
    refusal = _base_problem(base_url)
    if refusal is not None:
        return refusal
    request = urllib.request.Request(
        base_url.rstrip("/") + "/models",
        headers=_headers(base_url, api_key, extra_headers, body=False),
        method="GET",
    )
    try:
        with llm._OPENER.open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return _models_status_error(exc.code)
    except urllib.error.URLError as exc:
        return _transient(exc.reason, base_url, timeout)
    except http.client.HTTPException as exc:
        # A non-HTTP answer or a truncated body, classified like any
        # transport failure rather than escaping raw.
        return _transient(exc, base_url, timeout)
    except OSError as exc:
        return _transient(exc, base_url, timeout)
    return _models_from_body(raw, content_type)


def deep_check(
    base_url: str,
    api_key: str,
    model: str,
    extra_headers: dict | None = None,
    timeout: float | None = None,
) -> ProbeResult:
    """One max_tokens=1 chat completion with the typed model.

    The only chat the keys surface ever sends, and only because the user
    pressed the deeper-check button: save and Test never complete one.
    The reply's content is discarded; what matters is that the endpoint
    accepted the key and the model, which answers ok.
    """
    timeout = CHECK_TIMEOUT_S if timeout is None else timeout
    refusal = _base_problem(base_url)
    if refusal is not None:
        return refusal
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(base_url, api_key, extra_headers, body=True),
        method="POST",
    )
    try:
        with llm._OPENER.open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return _chat_status_error(exc.code)
    except urllib.error.URLError as exc:
        return _transient(exc.reason, base_url, timeout)
    except http.client.HTTPException as exc:
        return _transient(exc, base_url, timeout)
    except OSError as exc:
        return _transient(exc, base_url, timeout)
    if "html" in content_type.lower() or raw.lstrip().lower().startswith("<"):
        # A portal answering 200 with a page: named like the adapter
        # names it, never mistaken for a working completion.
        return ProbeResult(OUTCOME_ERROR, llm.WEB_PAGE_CAUSE)
    return ProbeResult(OUTCOME_OK, "")
