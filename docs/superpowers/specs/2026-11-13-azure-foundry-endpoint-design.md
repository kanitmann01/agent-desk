# Azure Foundry endpoint plug-and-play

Date: 2026-11-13  
Status: approved for planning (pending user review of this spec)

## Problem

Nexuus Bot already accepts any OpenAI-compatible endpoint via Settings → Endpoint (Base URL, API key, Model) and `AGENTDESK_LLM_BASE` / `AGENTDESK_LLM_KEY` / `AGENTDESK_LLM_MODEL`. Azure AI Foundry’s OpenAI-compatible surface uses the same three credentials, but authenticates with the `api-key` header rather than `Authorization: Bearer`. The adapter today always sends Bearer, so Foundry paste-in is not reliably plug-and-play.

## Goals

- Paste Foundry endpoint, API key, and model/deployment into the **existing** three fields (or env vars) and have Test connection / research / assistant work without a restart.
- Detect Azure/Foundry hosts and send `api-key` instead of Bearer.
- Document Foundry as a supported OpenAI-compatible target in Settings hint and README.
- No new settings rows, no Azure provider mode, no `api-version` (Foundry OpenAI-compatible style only).

## Non-goals

- Classic Azure OpenAI deployment URLs that require `api-version` query params.
- URL rewriting or “fix” of incomplete Foundry bases (user pastes the full OpenAI-compatible API base, typically ending in `/openai/v1`).
- Dual-header auth, new env aliases (`AGENTDESK_AZURE_*`), or a separate Foundry UI preset.
- Azure AD / Entra token auth (API key only).

## Decision

**Auth detect only.** Keep the current Settings form and env keys. In `llm.py`, classify the base URL host; on known Azure/Foundry suffixes use `api-key`, otherwise keep Bearer. Update copy only.

## Architecture

```
Settings / config.env / env
        │
        ▼
effective_llm_config()  →  (base, key, model)   [unchanged]
        │
        ▼
chat()  →  POST {base}/chat/completions
             headers:
               Content-Type: application/json
               if azure/foundry host → api-key: <key>
               else                  → Authorization: Bearer <key>
             body: model, temperature, messages [, max_tokens]
```

Saved settings still win over environment over `config.env`. Resolution stays per call so a Settings save applies without restart.

## Components

### 1. `src/agentdesk/llm.py`

- Add a pure helper, e.g. `uses_azure_api_key(base_url: str) -> bool`, that parses the host via `urlsplit` and returns true when the hostname (lowercased) equals or ends with one of:

  - `.openai.azure.com`
  - `.services.ai.azure.com`
  - `.cognitiveservices.azure.com`
  - `.azure-api.net`

  Exact host matches for those apex forms are included by the “equals or ends with” rule (e.g. `openai.azure.com`). Ports do not affect matching. Unparseable or empty bases return false (existing empty-base / scheme checks still own those failures).

- In `chat()`, build headers from that helper: Azure → `{"Content-Type": "...", "api-key": api_key}`; else → current Bearer shape.
- Do not rewrite the path, add `api-version`, or send both auth headers.
- Existing failure vocabulary unchanged (401/403 still named as rejected API key, etc.).

### 2. `src/agentdesk/server/settings_view.py`

- Extend `ENDPOINT_HINT` to name Azure AI Foundry alongside company gateway / OpenAI / OpenRouter / LiteLLM / Anthropic.
- State plainly: paste the OpenAI-compatible API base (usually ending in `/openai/v1`), the key, and the model or deployment name; Foundry hosts authenticate with the key automatically.
- Adjust placeholders if useful (e.g. Base URL example that could be either a company gateway or a Foundry `/openai/v1` URL; Model placeholder can mention deployment names without adding a fourth field).

### 3. `README.md` (Configure it)

- Mention Azure AI Foundry in the LLM endpoint bullet.
- Keep the same three `AGENTDESK_LLM_*` keys; example comment or line may show a Foundry-shaped base URL.

## Data flow (user-visible)

1. User opens Settings → Endpoint (or edits `~/.agent-desk/config.env`).
2. Pastes Foundry base (e.g. `https://<resource>.openai.azure.com/openai/v1`), API key, and model/deployment name.
3. Save / Test connection / any research or assistant ask resolves config and calls `chat()`.
4. Adapter selects `api-key` for that host and POSTs `/chat/completions`.
5. Success returns content; failure shows the existing plain-language cause.

## Error handling

No new cause strings. Wrong base, rejected key, timeout, HTML portal, and wrong-shape JSON keep current wording. Host misclassification (non-Azure host that somehow needs `api-key`) is out of scope; users with a Foundry-compatible proxy on a custom domain can use a gateway that accepts Bearer, or we revisit later.

## Testing

- Unit tests for `uses_azure_api_key`: matching suffixes (with and without port), case-insensitivity, non-Azure hosts (`api.openai.com`, company gateway), empty/invalid → false.
- One (or more) stubbed `chat()` tests: Azure-shaped host on loopback is awkward for real DNS; prefer either (a) testing the header-selection helper in isolation plus a thin internal hook, or (b) recording headers in the existing scripted endpoint by pointing `base_url` at loopback while forcing the classifier via a test-only parameter **only if** the production API stays clean—prefer extracting header building so tests call the same function `chat()` uses without mocking DNS.
  - Preferred shape: `auth_headers(base_url, api_key) -> dict` used by `chat()`; tests assert that function’s output for Azure vs non-Azure bases without network.
  - Optional: extend the loopback stub to record `Authorization` / `api-key` and assert Bearer still for `127.0.0.1`.
- Existing Bearer / settings / research tests remain green.

## Acceptance

- Pasting Foundry OpenAI-compatible base + key + model into Settings and clicking Test connection authenticates with `api-key` when the host matches the suffix list.
- Non-Azure bases still send Bearer only.
- No new Settings fields; no `api-version`; docs and Settings hint name Foundry.
- Tests cover host classification and header selection.

## Out of scope follow-ups (explicit)

- Classic Azure OpenAI `api-version` + deployment path layout.
- Entra ID / managed identity.
- Auto-normalizing a resource root URL into `/openai/v1`.
