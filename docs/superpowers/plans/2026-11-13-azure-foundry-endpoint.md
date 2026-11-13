# Azure Foundry Endpoint Plug-and-Play Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Azure AI Foundry OpenAI-compatible credentials (endpoint + API key + model) work as a paste-in on the existing Settings Endpoint form by sending `api-key` auth for Azure/Foundry hosts.

**Architecture:** Keep the three existing credential fields and env keys. Extract header selection into helpers in `llm.py`: detect known Azure/Foundry host suffixes and send `api-key` instead of `Authorization: Bearer`. Update Settings hint and README copy only — no new settings rows, no URL rewriting, no `api-version`.

**Tech Stack:** Python 3.10+, stdlib `urllib`/`urlsplit`, existing pytest suite (`tests/test_llm_chat.py`, `tests/test_server_settings_api.py`), server-rendered Settings HTML.

## Global Constraints

- OpenAI-compatible Foundry only (endpoint + key + model/deployment); no `api-version`.
- No new Settings fields; no `AGENTDESK_AZURE_*` aliases; no provider preset UI.
- Auth: Azure/Foundry hosts → `api-key` header only; all other hosts → `Bearer` only (never both).
- Host suffixes (exact list): `.openai.azure.com`, `.services.ai.azure.com`, `.cognitiveservices.azure.com`, `.azure-api.net` (match hostname equals apex or ends with suffix; case-insensitive; ports ignored).
- Do not rewrite bases; user pastes the full API base (typically ending in `/openai/v1`).
- Existing failure vocabulary in `llm.py` stays unchanged.
- Spec: `docs/superpowers/specs/2026-11-13-azure-foundry-endpoint-design.md`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/agentdesk/llm.py` | Add `uses_azure_api_key` + `auth_headers`; `chat()` uses them when building the request |
| `tests/test_llm_chat.py` | Unit tests for host classification and header selection |
| `src/agentdesk/server/settings_view.py` | Name Foundry in `ENDPOINT_HINT` (and placeholders if needed) |
| `README.md` | Name Foundry in Configure it / LLM endpoint section |
| `tests/test_server_settings_api.py` | Assert Settings page names Foundry (keep existing hint asserts) |

No new modules.

---

### Task 1: Azure/Foundry auth header selection

**Files:**
- Modify: `src/agentdesk/llm.py` (after `base_url_problem` / near `_host_of`; and `chat()` headers at ~226–229)
- Test: `tests/test_llm_chat.py`

**Interfaces:**
- Consumes: `urlsplit` (already imported in `llm.py`); `chat(base_url, api_key, model, prompt, ...)`
- Produces:
  - `uses_azure_api_key(base_url: str) -> bool`
  - `auth_headers(base_url: str, api_key: str) -> dict[str, str]`  
    Always includes `"Content-Type": "application/json"`.  
    If Azure: also `"api-key": api_key` (no `Authorization`).  
    Else: also `"Authorization": f"Bearer {api_key}"` (no `api-key`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_llm_chat.py` (extend the existing import from `agentdesk.llm`):

```python
from agentdesk.llm import LlmUnavailable, auth_headers, chat, transport_cause, uses_azure_api_key


def test_uses_azure_api_key_matches_foundry_and_azure_hosts():
    assert uses_azure_api_key("https://my-resource.openai.azure.com/openai/v1")
    assert uses_azure_api_key("https://my-resource.services.ai.azure.com/openai/v1")
    assert uses_azure_api_key("https://my-resource.cognitiveservices.azure.com/openai/v1")
    assert uses_azure_api_key("https://my-gateway.azure-api.net/openai/v1")
    assert uses_azure_api_key("https://openai.azure.com/openai/v1")  # apex
    assert uses_azure_api_key("https://MY-RESOURCE.OPENAI.AZURE.COM/openai/v1")  # case
    assert uses_azure_api_key("https://my-resource.openai.azure.com:443/openai/v1")  # port


def test_uses_azure_api_key_rejects_non_azure_and_empty():
    assert not uses_azure_api_key("https://api.openai.com/v1")
    assert not uses_azure_api_key("https://llm.corp.example/v1")
    assert not uses_azure_api_key("https://api.anthropic.com/v1")
    assert not uses_azure_api_key("")
    assert not uses_azure_api_key("not-a-url")


def test_auth_headers_send_api_key_for_azure_and_bearer_otherwise():
    azure = auth_headers("https://x.openai.azure.com/openai/v1", "secret")
    assert azure["Content-Type"] == "application/json"
    assert azure["api-key"] == "secret"
    assert "Authorization" not in azure

    other = auth_headers("https://api.openai.com/v1", "secret")
    assert other["Content-Type"] == "application/json"
    assert other["Authorization"] == "Bearer secret"
    assert "api-key" not in other
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_llm_chat.py::test_uses_azure_api_key_matches_foundry_and_azure_hosts tests/test_llm_chat.py::test_uses_azure_api_key_rejects_non_azure_and_empty tests/test_llm_chat.py::test_auth_headers_send_api_key_for_azure_and_bearer_otherwise -v`

Expected: FAIL with `ImportError` / `cannot import name 'uses_azure_api_key'` (or `auth_headers`).

- [ ] **Step 3: Implement helpers and wire `chat()`**

In `src/agentdesk/llm.py`, after `base_url_problem` (or immediately before `_host_of`), add:

```python
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
```

In `chat()`, replace the inline headers dict with:

```python
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=auth_headers(base_url, api_key),
        method="POST",
    )
```

Do not change the payload, path, timeout, or exception handling.

- [ ] **Step 4: Run the new tests and the existing llm chat suite**

Run: `python -m pytest tests/test_llm_chat.py -v`

Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add src/agentdesk/llm.py tests/test_llm_chat.py
git commit -m "$(cat <<'EOF'
feat: use api-key auth for Azure Foundry LLM hosts

Detect known Azure/Foundry endpoint hosts and send the api-key header
instead of Bearer so Foundry credentials work in the existing endpoint form.
EOF
)"
```

---

### Task 2: Settings and README Foundry copy

**Files:**
- Modify: `src/agentdesk/server/settings_view.py` (`ENDPOINT_HINT` ~28–37; optional placeholders in `_endpoint_form` ~99–107)
- Modify: `README.md` (Configure it / LLM endpoint ~17–35)
- Modify: `tests/test_server_settings_api.py` (`test_endpoint_section_has_save_test_clear_and_the_hint` ~114–127)

**Interfaces:**
- Consumes: Task 1 behavior already live; this task is documentation/UI copy only.
- Produces: Settings page and README that name Azure AI Foundry; existing Anthropic/OpenRouter/LiteLLM strings must remain so current asserts still pass.

- [ ] **Step 1: Write the failing Settings assertion**

In `tests/test_server_settings_api.py`, inside `test_endpoint_section_has_save_test_clear_and_the_hint`, after the existing OpenRouter/LiteLLM assert, add:

```python
    assert "Azure AI Foundry" in page or "Foundry" in page
```

Keep all existing asserts in that test (`OpenAI-compatible`, Anthropic URL, OpenRouter, LiteLLM, `starts with http:// or https://`, `clears the saved key`).

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_server_settings_api.py::test_endpoint_section_has_save_test_clear_and_the_hint -v`

Expected: FAIL on the Foundry assertion (page does not yet mention Foundry).

- [ ] **Step 3: Update Settings hint (and placeholders)**

Replace `ENDPOINT_HINT` in `src/agentdesk/server/settings_view.py` with copy that still contains every string the existing test asserts, and names Foundry. Exact replacement:

```python
ENDPOINT_HINT = (
    "<p>Works with any OpenAI-compatible endpoint: your company gateway, "
    "OpenAI, OpenRouter, LiteLLM, Azure AI Foundry, or Anthropic's "
    "OpenAI-compatible URL (https://api.anthropic.com/v1 with a Claude "
    "model name). The base URL is the full API address: it starts with "
    "http:// or https:// and usually ends in the API version, like /v1 "
    "(Foundry often ends in /openai/v1); a portal sign-in page there is "
    "not an API base. Paste the key and, for Foundry, the model or "
    "deployment name; Azure/Foundry hosts use the API key header "
    "automatically. A key and a URL are the whole login; there is no "
    "separate sign-in step. Saved settings win over environment "
    "variables and config.env.</p>"
)
```

Optionally update the Base URL placeholder in `_endpoint_form` to still show a generic example (keep `https://llm.yourcompany.example/v1` or switch to a Foundry-shaped example only if it does not break any test that asserts the placeholder string — today none do). Leave the Model placeholder as `gpt-4o-mini` unless you add a short hint in the label text; do not add a fourth field.

- [ ] **Step 4: Update README Configure it**

In `README.md`, in the **LLM endpoint** bullet (~line 21), extend the compatible list to include Azure AI Foundry, e.g. keep the sentence structure and insert Foundry:

> Works with any OpenAI-compatible endpoint: a company gateway, OpenAI, OpenRouter, LiteLLM, Azure AI Foundry, or Anthropic's OpenAI-compatible URL (`https://api.anthropic.com/v1` with a Claude model name).

Optionally add a comment line above the env example:

```
# Foundry example: AGENTDESK_LLM_BASE=https://<resource>.openai.azure.com/openai/v1
```

Do not add new env variable names.

- [ ] **Step 5: Run Settings tests**

Run: `python -m pytest tests/test_server_settings_api.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agentdesk/server/settings_view.py README.md tests/test_server_settings_api.py
git commit -m "$(cat <<'EOF'
docs: name Azure AI Foundry in endpoint settings and README

Make Foundry paste-in discoverable on the existing three-field endpoint
form without adding a separate provider mode.
EOF
)"
```

---

## Plan Self-Review

1. **Spec coverage:** Auth detect + host list → Task 1. Settings/README copy → Task 2. No URL rewrite / no api-version / no new fields → Global Constraints + task scope. Tests for classifier + headers → Task 1; Foundry named on Settings page → Task 2. Acceptance criteria covered.
2. **Placeholders:** None; full code and commands included.
3. **Type consistency:** `uses_azure_api_key(base_url: str) -> bool` and `auth_headers(base_url: str, api_key: str) -> dict[str, str]` used consistently in Task 1 tests and implementation.
