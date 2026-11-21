# BYOK UX in developer tools: how OpenRouter, LiteLLM, Cursor, Continue, Raycast, Zed, Aider, Open WebUI, LobeChat, Dify, and n8n implement bring-your-own-key

Research date: 2026-11-21. Every claim below was checked against a fetched page; the source URL is listed per product. Anything not confirmed on a fetched page is marked UNVERIFIED.

What this is for: agent-desk BYOK design. Users save their own LLM API keys, pick providers, assign keys/models to jobs. We studied each product's flow from "I have an API key" to "model is usable", multi-key management, provider presets, Anthropic handling, and error UX.

---

## 1. OpenRouter (key + credits + unified catalog)

Sources:
- https://openrouter.ai/docs/quickstart (fetched)
- https://openrouter.ai/docs/api-reference/errors (fetched)
- https://openrouter.ai/docs/guides/overview/auth/management-api-keys.md (fetched)
- https://openrouter.ai/docs/guides/best-practices/spend-controls.md (fetched)

### Flow from key to usable model
1. User creates a key in the dashboard and buys credits (prepaid). The quickstart page does not document the key-creation UI steps; it documents usage. Key creation specifics: UNVERIFIED beyond what the management API docs show.
2. Any OpenAI SDK works by changing the base URL to `https://openrouter.ai/api/v1` (an EU mirror `https://eu.openrouter.ai/api/v1` exists for Business/Enterprise).
3. Auth is `Authorization: Bearer <OPENROUTER_API_KEY>`. Optional `HTTP-Referer` and `X-OpenRouter-Title` headers attribute the app on leaderboards.
4. Model discovery is a first-class feature: browse humans at `openrouter.ai/models`, or `GET /api/v1/models` programmatically ("every available slug"). Models also have `latest` aliases (e.g. `~openai/gpt-sol-latest`) that always resolve to the newest model in a family.

### Multi-key and money management
- Keys are first-class objects with their own settings: `name`, `limit` (credit limit), `limit_reset` (e.g. `"daily"`, resets at midnight UTC), `disabled`, and `include_byok_in_limit`. The management API exposes full CRUD at `/api/v1/keys` (list, create, get by hash, patch, delete) plus usage telemetry per key: `usage`, `usage_daily`, `usage_weekly`, `usage_monthly`, `limit_remaining`.
- Management keys are separated from inference keys: management keys "cannot be used to make API calls to OpenRouter's completion endpoints", are scoped org or workspace, have fixed permissions (read/write, read only, custom grants) and expiry; shown once at creation.
- Spend controls are layered: workspace budget (pooled emergency cap, checked first on every request) stacked with per-member/per-key "guardrails" (each enforced independently, first limit reached blocks). Spend attribution follows the key creator, not the caller. A per-workspace "Include BYOK spend" toggle counts BYOK inference against budgets.
- OpenRouter itself supports BYOK of provider keys and private endpoints (docs pages `byok.md` and `private-endpoints.md` exist in the index; details not fetched, UNVERIFIED).

### Error UX (best-documented of any product)
- Uniform error shape, HTTP status matches `error.code`:
  `{"error": {"code": 402, "message": "...", "metadata": {...}}}`
- Codes: 401 invalid/expired/disabled key, 402 insufficient credits, 403 guardrail or moderation, 404 model not found, 429 rate limited, 502 chosen model down, 503 "no available model provider that meets your routing requirements", 504 provider timeout.
- Provider errors are normalized to a stable typed `error.metadata.error_type` (`rate_limit_exceeded`, `context_length_exceeded`, `authentication`, `payment_required`, `provider_overloaded`, `provider_unavailable`, `server` with masked message, `unmapped`). This lets clients branch on semantics instead of parsing strings.
- `Retry-After` header on 429/503 and budget-related 402s.
- Mid-stream failures: HTTP 200 already sent, then the error arrives as an SSE event (top-level `error` plus a terminating choice with `"finish_reason": "error"`). This is the correct model for streaming UX: a stream that dies mid-answer still delivers a machine-readable error.

---

## 2. LiteLLM (SDK + proxy gateway)

Sources:
- https://docs.litellm.ai/docs/ (SDK quickstart, fetched)
- https://docs.litellm.ai/docs/proxy/virtual_keys (fetched)
- https://docs.litellm.ai/docs/proxy/reliability (fetched)
- https://docs.litellm.ai/docs/proxy/configs (fetched)
- https://docs.litellm.ai/docs/proxy/load_balancing (fetched)
- https://docs.litellm.ai/docs/routing (fetched)
- https://docs.litellm.ai/docs/router/api_reference/configuration (fetched)

### SDK flow (key to usable model)
- One function for every provider: `litellm.completion(model="openai/gpt-6.1-sol", messages=[...])`. The provider prefix in the model string ("openai/", "anthropic/", "azure/", "bedrock/", "vertex_ai/", "ollama/") selects the integration; keys come from standard env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, ...). You can pass `api_key` and `api_base` per call instead of env vars (the Ollama example passes `api_base="http://localhost:11434"` with no key).
- "Every response follows the OpenAI Chat Completions format, regardless of provider", and errors map to OpenAI exception types (`litellm.AuthenticationError`, `litellm.RateLimitError`, `litellm.APIError`).

### Proxy: virtual keys, budgets, routing
- `config.yaml` has `model_list` where each entry is a deployment: a public `model_name` alias plus `litellm_params` (provider-prefixed model, `api_key: os.environ/OPENAI_API_KEY`, optional `api_base`). Multiple deployments sharing one `model_name` are load balanced as one model.
- Virtual keys require Postgres plus a `master_key` (must start with `sk-`). `POST /key/generate` mints keys with: `models` (allowlist of usable models), `max_budget` (USD), `budget_duration` (e.g. `"10d"` reset window), `tpm_limit`/`rpm_limit`, `max_parallel_requests`, `key_alias` (names enforceable via `key_alias_pattern` regex). Ownership drives inheritance: keys inherit tpm/rpm/budgets from their owner user/team.
- Guardrail pattern worth copying: `upperbound_key_generate_params` rejects key-creation requests above policy limits with HTTP 400 rather than silently clamping them.
- Admin keys manage everything via `/key/info`, `/user/info`, `/team/info`, `/key/block`, `/key/unblock`. Team keys exist for keys "owned by multiple people".
- Routing/reliability: `routing_strategy` (simple-shuffle, least-busy, usage-based-routing, latency-based-routing), `num_retries`, `timeout`, `fallbacks` (per model group, on any error), `context_window_fallbacks` (fallback specifically for ContextWindowExceededError), `content_policy_fallbacks`, `default_fallbacks`, `max_fallbacks` (hop limit), `allowed_fails` + `cooldown_time` (put a deployment in cooldown after N failures), `enable_weighted_failover` (retry inside the group before cross-group escalation), `order` field for priority failover within a group, `model_group_alias`.
- Rate-limit errors from the proxy return OpenAI-shaped errors with detail ("Model rate limit exceeded. RPM limit=60, current usage=60") plus a `retry-after` header that already accounts for the reset time.

---

## 3. Cursor (custom API keys)

Sources:
- https://cursor.com/docs/settings/api-keys (fetched, after redirect from docs.cursor.com)
- https://cursor.com/help/models-and-usage/api-keys (fetched via search result content)
- https://help.openai.com/en/articles/20001506-using-openai-models-in-cursor (fetched via search result content)
- https://forum.cursor.com/t/no-verify-button-when-setting-custom-openai-api-key-in-settings-models/140843 (fetched via search)
- https://forum.cursor.com/t/anthropic-api-key-simply-does-not-work/150300 (fetched via search)

### Flow
1. "Open Cursor Settings > Models".
2. "Find the provider you want (OpenAI, Anthropic, Google, Azure, or AWS Bedrock)".
3. "Paste your API key into the text field".
4. "Click Save". The provider's models "appear in the model picker".

### Multi-key and per-feature behavior
- Keys are per-provider, each with its own enable toggle. One key per provider slot.
- There is an "Override OpenAI Base URL" toggle for pointing OpenAI-compatible traffic at gateways (OpenRouter, Vercel AI Gateway, local servers); docs recommend NOT overriding for official keys. Custom model names can be added by hand.
- Scope is explicitly limited: "Custom API keys only work with chat models. Tab completion continues using Cursor's built-in models." The OpenAI help article adds that own keys do not apply to Cursor Tab, Auto model selection, Cloud/Background Agents, Automations, CLI, or the Cursor API/SDK.
- Privacy story: the key is "not stored on our servers"; requests are routed through Cursor's backend (prompts built server-side), the key is sent with each request and not persisted; the provider's data policy governs instead of Cursor's Zero Data Retention.
- Billing: individual plans get unlimited messages at own cost; Teams/Enterprise still pay the Cursor Token Rate ($0.25/M tokens) on eligible models.

### Validation and error UX
- There used to be a Verify button next to each key field. Cursor staff confirm it "was intentionally removed in recent versions" because it "often caused an error"; keys now save without validation and failures surface only when a request actually runs. An older staff tip reveals the flaw: "Cursor uses that model (gpt-4o) during its validation fn call. So if you have it disabled, validation fails prematurely."
- Invalid or rejected keys: "requests using that provider fail until you update or remove the key" (no proactive banner documented).
- A staff-endorsed debugging step shows the conflict pattern: a stale OpenAI base URL override or OpenAI key can break Anthropic requests; clearing the override fixes it (forum thread above).

### Anthropic note
Cursor has a dedicated Anthropic key slot ("All Claude models available through the Anthropic API"), so Anthropic goes over its native integration, not through the OpenAI-compat shim.

---

## 4. Continue.dev (config file + hub)

Sources:
- https://docs.continue.dev/reference (YAML reference, fetched via search result content)
- https://docs.continue.dev/customize/model-providers/overview (fetched via search result content)
- https://docs.continue.dev/reference/yaml-migration (fetched via search result content)
- https://docs.continue.dev/customize/models (fetched via search result content)
- https://betterstack.com/community/guides/ai/continue-dev-ai (third-party walkthrough of the UI flow; UI labels are from this guide)

### Flow (config.yaml)
The unit of configuration is a model entry, not a provider:
```yaml
models:
  - name: Claude 4 Sonnet
    provider: anthropic
    model: claude-sonnet-4-20250514
    apiKey: ${{ secrets.ANTHROPIC_API_KEY }}
    roles: [chat, edit, apply]
```
- `provider` selects the preset (openai, anthropic, ollama, mistral, voyage, gemini, bedrock, azure, xai, ...); the preset fills base URL and auth style. `apiBase` overrides it per model. `apiKey` supports `${{ secrets.VAR }}` interpolation so keys never live in the file (pulled from shell env or Continue Hub secrets).
- `roles` is the standout pattern: one array per model assigns it to jobs (`chat`, `edit`, `apply`, `autocomplete`, `embed`, `rerank`, `summarize`; default `[chat, edit, apply, summarize]`). Different models for different jobs is a first-class concept, and the docs ship a "Best Models by Role" recommendation table.
- YAML anchors (`&model_defaults`, `<<: *model_defaults`) let several models share one provider/key block.
- Special model name `AUTODETECT` (Ollama) pulls the live model list from the server.
- `requestOptions.headers` supports custom auth headers (e.g. `X-Auth-Token`) for gateways that do not use Bearer.
- The setup instructions in docs are consistently four steps: get key from provider, add model to config, add `PROVIDER_API_KEY` to environment, click "Reload config".

### UI flow (hub-assisted, per Better Stack guide)
Chat panel model dropdown, "+ Add Model", Provider dropdown, Model dropdown, API key field, "Connect" button. Repeatable for multiple providers; switch models per conversation from the same dropdown. (UI details: third-party guide; UNVERIFIED against first-party docs.)

### Error UX
- Wrong model IDs surface as a 404 from the gateway; the recommended fix is to re-run the catalog list (`GET /models` with the key) and use IDs verbatim (AskCodi guide, third party, UNVERIFIED).
- Codestral gotcha documented in official docs: the Codestral API key and the general Mistral API key are different; you must set `apiBase` explicitly if you share a key (docs.continue.dev/customize/deep-dives/autocomplete).

---

## 5. Raycast AI (BYOK + custom providers)

Sources:
- https://manual.raycast.com/ai/bring-your-own-key (fetched via search result content)
- https://manual.raycast.com/ai/custom-providers (fetched via search result content)
- https://manual.raycast.com/enterprise/custom-provider (fetched via search result content)
- https://github.com/raycast/extensions/issues/28414 (Sync Models feature discussion, fetched via search)
- https://developers.raycast.com/api-reference/ai (fetched via search)

### BYOK flow (the cleanest key-entry flow found)
1. "Open Settings → AI → Models & Providers."
2. "In the API Keys section, click to add your key."
3. "Select your provider from the dropdown."
4. "Paste your key into the API Key field, then click Verify. Raycast will check the key with the provider to ensure it can be used."
5. "Once verified, click Save. The key is stored securely and the provider appears in your API Key list."
- If the user has no key yet, a "Manage in [Provider] Console" button deep-links to the provider's key console page. Small detail, huge onboarding win.
- One key per provider, from Anthropic, Google, OpenAI, and OpenRouter. A toggle enables/disables each key without deleting it; disabled keys are skipped for every AI request. Each entry links to the provider console for rotation.
- When a BYOK key is active, "a small key icon appears next to that provider's model names" so users always know which requests bill their key.
- Routing/privacy is documented per provider: Anthropic/Google/OpenAI BYOK requests are processed through Raycast's servers (to unify APIs and add fallbacks); OpenRouter is the exception and goes direct, and an OpenRouter key unlocks "OpenRouter's full model catalog" while the other three only expose the models Raycast already integrates.

### Custom providers (OpenAI-compatible)
- A YAML file at `~/.config/raycast/ai/providers.yaml` (also deployable org-wide from the Raycast account, "AI Control Center", for enterprise):
```yaml
providers:
  - id: my_provider
    name: My Provider
    base_url: https://...          # OpenAI-compatible, without /chat/completions
    api_keys:
      my_provider: YOUR_API_KEY    # omit entirely for no-auth providers
    models:
      - id: my-model-id
        name: My Model
        provider: my_provider
        context: 200000
        abilities:
          temperature: { supported: true }
          vision: { supported: true }
          system_message: { supported: true }
          tools: { supported: true }
          reasoning_effort: { supported: false }
```
- `api_keys` is a map (multiple named keys per provider), and individual models can be mapped to a specific key via the model's `provider` field, so one provider entry can serve different keys per model.
- `additional_parameters` adds fields to every `/chat/completions` request; `include_user_email` sends the signed-in email as an `X-User-Email` header for per-user attribution on shared gateways.
- Custom models appear in the system-wide model picker "grouped under the provider's name", usable everywhere (Quick AI, AI Chat, AI Commands). Because Raycast has no benchmark data for them, they show no speed/intelligence scores (honest UI).
- Ollama local models are detected natively and automatically.
- The community extension added a "Sync Models" action that GETs the provider's OpenAI-compatible `/models` endpoint using the provider's configured key, validates the full response, and "leaves the existing catalog untouched on failure" (GitHub issue 28414). Core Raycast does not auto-fetch custom catalogs (third-party blog and GitHub issue confirm).

---

## 6. Zed editor (OpenAI-compatible provider config)

Sources:
- https://zed.dev/docs/ai/llm-providers (fetched)
- https://zed.dev/docs/ai/use-api-access (fetched)

### Flow
- Keys are entered in "Settings → AI → LLM Providers" (command `agent: open settings`) and are stored in the system keychain, not in settings.json; the docs explicitly warn "Do not put API keys in settings.json".
- Environment variables override the keychain: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` (fallback `GOOGLE_AI_API_KEY`), `MISTRAL_API_KEY`, `DEEPSEEK_API_KEY`, `XAI_API_KEY`, `OPENCODE_API_KEY`, `OPENROUTER_API_KEY`, `VERCEL_AI_GATEWAY_API_KEY`, `OLLAMA_API_KEY`, `LMSTUDIO_API_KEY`. For OpenAI-compatible custom providers the env var name is derived from the provider id (`my-gateway` becomes `MY_GATEWAY_API_KEY`).
- The docs frame provider choice as five access paths: "Use Zed-Hosted Models", "Use API Access" (own key), "Use an Existing Subscription", "Use a Gateway" (OpenRouter, Bedrock, Vercel), "Use a Local Model". This taxonomy is a good information architecture for a provider picker.

### OpenAI-compatible config (settings.json)
```json
{
  "language_models": {
    "openai_compatible": {
      "my-provider": {
        "api_url": "https://example.com/v1",
        "available_models": [
          { "name": "my-model", "display_name": "My Model", "max_tokens": 128000 }
        ]
      }
    }
  }
}
```
- Per-model fields include `max_tokens` (context), `max_output_tokens`, `reasoning_effort` ("none" to "max"), and a `capabilities` object with explicit defaults: `tools: true`, `images: false`, `parallel_tool_calls: false`, `prompt_cache_key: false`, `chat_completions: true`, `interleaved_reasoning: false`, `max_tokens_parameter: false`. `chat_completions: false` marks a model that only works with the Responses API. The model list is hand-declared; there is no documented auto-discovery via GET /models.
- Per-feature selection: models are picked from the Agent Panel dropdown for "the Zed Agent, Inline Assistant, Git commit generation, thread summaries"; Edit Prediction "has its own provider setup under `edit_predictions`".

---

## 7. Aider (terminal, env-var first)

Sources:
- https://aider.chat/docs/llms.html (fetched)
- https://aider.chat/docs/config/api-keys.html (fetched)
- https://aider.chat/docs/usage/commands.html (fetched)

### Flow
- Keys accepted four ways, in order of convenience: command line (`--openai-api-key`, `--anthropic-api-key`, and generic `--api-key provider=<key>` which sets `PROVIDER_API_KEY`), environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`), a `.env` file, or `.aider.conf.yml` (`api-key: [gemini=foo, openrouter=bar]`).
- Model switching is in-chat: `/model` "Switch the Main Model to a new LLM", `/models` "Search the list of available models", plus `/editor-model` and `/weak-model` for the secondary roles. Aider therefore has three concurrent model slots (main, editor, weak) chosen independently, the terminal equivalent of Continue's roles.
- Docs recommend OpenRouter for free models (daily limits) and Ollama for local, via "Open AI compatible API". Capability floor warning: "Models weaker than GPT 3.5 may have problems working well with aider".
- Per-model tuning lives in `.aider.model-settings.yml` (linked from the LLMs page as "Advanced model settings"; page not fetched, details UNVERIFIED).

---

## 8. Open WebUI (connections with the simplest mental model)

Sources:
- https://docs.openwebui.com/ecosystem/computer/ai/connect-a-model (fetched via search result content)
- https://docs.openwebui.com/getting-started/quick-start/connect-a-provider (fetched via search result content)
- https://docs.openwebui.com/features/chat-conversations/direct-connections (fetched via search result content)

### Flow
"Settings → Admin → Connections", add a connection. The radical simplification: "There are exactly two provider types: OpenAI and Anthropic. There is no separate Ollama or OpenAI-compatible type: anything that speaks the OpenAI API (Ollama, OpenRouter, vLLM, LM Studio, Groq, ...) is added as provider OpenAI with a custom Base URL."

Connection fields (a near-perfect spec for our connection form):
| Field | Purpose |
|---|---|
| Name | Optional display name |
| Provider | `OpenAI` or `Anthropic` |
| API Type | OpenAI only: Chat Completions or Responses |
| Base URL | Required |
| API Key | Required; Ollama ignores the value but the field must be non-empty |
| Prefix ID | Namespace prepended to model ids, e.g. `openrouter/gpt-5.6-sol`, so multiple connections do not collide |
| Models | Optional comma-separated list; "Leave empty to auto-discover" |

- Model discovery: leave Models empty and Open WebUI fetches the provider's model list (`/models`); models then appear in the selector. Multiple connections coexist; the chat model dropdown is per-conversation. A default model exists (`chat.default_model`).
- Prefix ID is the standout pattern: it makes multi-provider model lists unambiguous ("openrouter/claude-..." vs "direct/claude-...").
- Direct Connections (experimental): with `ENABLE_DIRECT_CONNECTIONS=true`, users connect their own client straight to the provider, bypassing the server backend; docs advise "least-privilege provider credentials" and warn against management/master keys for user traffic.
- Ops detail: the `AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST` env var tunes the model-list fetch timeout when one of several configured endpoints is down (fetched page shows `AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST=3` vs the 10s default, for faster failover of the picker).

---

## 9. LobeChat / LobeHub (per-provider cards with check + fetch)

Sources:
- https://lobehub.com/docs/usage/providers (fetched via search result content)
- https://lobehub.com/docs/usage/providers/openai (fetched via search result content)
- https://lobehub.com/docs/self-hosting/environment-variables/model-provider (fetched via search result content)
- https://deepwiki.com/lobehub/lobe-chat/3.1-provider-configuration-system (third-party code analysis)

### Flow (UI)
1. "Select a provider from the list and turn on its switch."
2. "Enter the credentials shown on the page. Most cloud providers use an API key. Providers such as Amazon Bedrock and Azure OpenAI also show region, endpoint, or other provider-specific fields."
3. "If Proxy URL is available, enter the provider API base URL or a compatible endpoint. For local services, enter the Ollama or vLLM server address."
4. "Select Check to test the connection." (Per-provider guide: a green status indicator confirms success.)
5. "Enable a model in the model list. You can also fetch or add models when those actions are available."
6. "Your changes are saved automatically." The model is then selectable per Agent; each Agent has its own default model.
- Custom providers: "Add Custom Provider" with Provider ID, Request Format (openai/anthropic/...), proxy URL (base URL without `/chat/completions`), key; then "Fetch models" to pull the catalog, or "Add Model" by hand with context window and capability toggles (tool calling, vision, deep thinking). Keys and proxy URLs are encrypted with AES-GCM (third-party guide, UNVERIFIED against first-party docs).
- Self-host env vars follow strict patterns: `{PROVIDER}_API_KEY`, `{PROVIDER}_PROXY_URL` (base URL override), `{PROVIDER}_MODEL_LIST` (mini-language: `+model` add, `-model` hide, `-all` hide all, `id=Display Name`, `id->deployment` remap), `ENABLED_{PROVIDER}`.
- Documented troubleshooting taxonomy maps 1:1 to our error states: connection error/API key invalid (check spaces, key type matches provider), model not available (account tier or retired model), rate limit (slow down, switch provider, upgrade).

---

## 10. Dify (workspace model providers with validation and per-job defaults)

Sources:
- https://docs.dify.ai/en/cloud/use-dify/workspace/model-providers (fetched via search result content)
- https://docs.dify.ai/en/self-host/use-dify/workspace/model-providers (fetched via search result content)
- https://enterprise-docs.dify.ai/en/3.10.x/use/workspace/model-providers (fetched via search result content)
- https://github.com/langgenius/dify/discussions/25955 (fetched via search)

### Flow
1. "In Integrations > Model Provider, browse Install model providers, or open the Marketplace for the full list." Providers are plugins installed from a marketplace.
2. "Install the provider, click Add API Key, and enter your API key along with any other required details." Crucially: "Dify validates the credentials before making the provider available." Validation on save is built in.
3. A provider's models are immediately usable once authorized; you only "Add Model" manually for custom/fine-tuned models, giving it a name plus its own credentials.
- The OpenAI-API-compatible provider is the escape hatch: fields are Model name, Model type (LLM/embedding/...), Credential name, API Key, API endpoint URL (base URL only; "Dify adds /chat/completions when it sends chat requests"), context length, max tokens, function call type, thinking mode. Explicitly documented error guidance: pasting the full `/chat/completions` URL into the base URL field is a named failure mode.
- Multiple keys per provider are supported ("keep development and production apart or spread usage across several accounts"), with load balancing on paid plans, and per-model credential management. If an added model matches an existing name and type, Dify attaches the new key to that model instead of duplicating it.
- Default Models are per job, set once for the workspace: "System Reasoning Model" (general LLM), Embedding, Rerank, Speech-to-Text, Text-to-Speech. "When a default is empty, the features that rely on it stop working" (clear, honest failure semantics).
- Usage Priority lets credits and own keys coexist (spend credits first, own key takes over when exhausted).
- Scope limit: keys are workspace-level; per-agent key assignment is not supported for the agent's own LLM calls (GitHub discussion 25955).

---

## 11. n8n (the credentials system, the most mature generic BYOK)

Sources:
- https://docs.n8n.io/credentials/ (fetched, index)
- https://docs.n8n.io/build/understand-workflows/create-and-edit-credentials (fetched via search result content)
- https://docs.n8n.io/integrations/builtin/credentials/httprequest (fetched via search)
- https://docs.n8n.io/integrations/builtin/credentials/google (fetched via search result content)

### Flow
1. "Select the universal create resource icon Create button ... Select credential." Choose personal space or a project first.
2. "Select the app or service you wish to connect to" (searchable picker of credential types).
3. "Once in the credential modal, enter the details required by your service" (per-service forms: API key, client id/secret, region, ...). OAuth2 credentials show provider-specific buttons ("Sign in with Google" for managed OAuth on cloud, or custom OAuth2 fields plus a copyable redirect URL for self-hosted).
4. "When you save a credential, n8n tests it to confirm it works." Validation on save, automatically.
5. Per-node usage: each node has a credentials dropdown filtered to compatible credential types, with "Create New" inline; credentials can also be created from the node editor.
- Credentials are per service, not per node: "You create one Google credential and every node of that type picks it from the credential dropdown" (community answer). Default naming is "node name account", renameable.
- Credential types include Fixed credential (same for everyone) vs End-user credential (per executing user), a SaaS pattern beyond agent-desk's needs but relevant to team features.
- Sharing/permissions: project-scoped; project members can use credentials in workflows; admins can hide secrets from users (`CREDENTIALS_OVERWRITE_ENDPOINT` sets credential data globally on self-hosted instances so users authenticate without seeing client secrets).
- Encryption: credentials are encrypted at rest with an instance encryption key; losing or changing it breaks decryption ("decrypted credentials will break"), stolen key equals plaintext secrets (Medium analysis + n8n docs).
- Generic escape hatch: the HTTP Request node supports "Predefined Credential Type" (reuse any service credential for custom API calls) plus generic auth modes (Basic, Header, Query, Digest, OAuth1, OAuth2 with grant types including client credentials, HMAC).

---

## 12. Anthropic: OpenAI-compat endpoint vs native API

Source: https://platform.claude.com/docs/en/api/openai-sdk (fetched; redirects from docs.anthropic.com/en/api/openai-sdk)

- Point any OpenAI SDK at `base_url="https://api.anthropic.com/v1/"`, use a Claude API key in the standard `apiKey` field (the `authorization` header is supported), and use Claude model names. Python and TypeScript samples are on the page.
- Supported: chat completions (messages, max_tokens, stop), streaming, tool use (with limits: forced tool calls return 400 on some models; `strict` is ignored), images via `image_url`, thinking via an extra `thinking` body field, structured outputs only as `response_format: json_schema` with `strict: true`.
- Not supported / silently changed: no prompt caching, no OpenTelemetry, no PDFs/citations, audio and file inputs 400, `json_object`/`text` response formats 400, system/developer messages are hoisted and newline-joined into the top-level `system` field, `n` must be 1, temperature is capped at 1 (Claude 4.7+ rejects temperature below 1 and top_p other than 0.99), and many fields (logprobs, seed, penalties, metadata, reasoning_effort, user) are silently ignored.
- Gotcha: keys not scoped to a workspace must also send an `anthropic-workspace-id` header on every request.
- Positioning: Anthropic says the layer is "primarily intended to test and compare model capabilities", not production; the native Messages API is the long-term path. Errors match OpenAI shapes but detailed messages differ ("use them only for logging/debugging").
- Design decision for agent-desk: use the compat endpoint only as a generic OpenAI-compatible fallback for Anthropic-shaped gateways; use the native Messages API (x-api-key + anthropic-version headers, /v1/models listing also exists on native) whenever you need caching, PDFs, citations, or full parameter fidelity.

---

# PATTERNS WORTH COPYING

1. **Verify on save, automatically.** Raycast's flow is the gold standard: paste key, click Verify ("Raycast will check the key with the provider"), then Save. n8n does it implicitly: "When you save a credential, n8n tests it to confirm it works." Dify validates before the provider becomes available. Do not make the user discover a bad key at first prompt. (Corroborated by Cursor's failure: they removed their Verify button because it was buggy, and now invalid keys fail silently until a chat request dies.)
2. **Validate with a cheap, real request, and make validation depend only on the key, not on any model.** Cursor's old bug: validation called gpt-4o, so users who had disabled that model could not validate any key. Use GET /v1/models (auth-only, free, near-universal) as the default validation call; fall back to a 1-token chat completion only if /models is not implemented.
3. **A key entry is a first-class object with name, enable toggle, console deep-link, and per-key limits.** Raycast: toggle a key off without deleting, "Manage in [Provider] Console" button before you even have a key, key icon next to models using it. OpenRouter: per-key `name`, `limit`, `limit_reset` (daily), `disabled`, `limit_remaining`, usage per key, full CRUD API. Copy all of this: keys should be named, pausable, spend-capped, and inspectable.
4. **Connection form fields: name, provider type, auth, base URL, optional model list, optional prefix.** Open WebUI's field list (Name, Provider, API Type, Base URL, API Key, Prefix ID, Models) is the best single-form spec found. The "API key required but ignored for local servers" nuance (Open WebUI, Ollama) matters: never block saving a local connection for lack of a key.
5. **Auto-discover models via GET /v1/models, but always allow a manual list and treat discovery failure as non-fatal.** Open WebUI ("Leave empty to auto-discover"), LobeChat ("fetch or add models"), Continue (AUTODETECT), Raycast community Sync Models ("leaves the existing catalog untouched on failure"). Manual override is essential because discovery endpoints lie (require auth, omit models, or are missing entirely; LobeChat issue 2131 documents auth-required model lists).
6. **Namespace model ids by connection.** Open WebUI's Prefix ID (`openrouter/gpt-...`) prevents collisions when the same model is reachable through several connections, and makes the model picker self-documenting about billing path. Raycast and OpenRouter do the same with provider-grouped model lists.
7. **Per-role/per-job model assignment, not just a default model.** Continue's `roles` array (chat, edit, apply, autocomplete, embed, rerank), Aider's main/editor/weak model commands, Dify's Default Models per job (reasoning, embedding, rerank, STT, TTS). Agent-desk's "assign keys to different jobs" should be modeled as job slots with a model + credential each, with a clear "job breaks when its default is empty" statement (Dify).
8. **Provider presets pre-fill base URL, auth header style, and model list; an OpenAI-compatible escape hatch covers everything else.** Continue's provider ids, Zed's env-var-named presets plus `openai_compatible` config, LiteLLM's provider prefixes, Open WebUI's two-protocol simplification ("anything that speaks the OpenAI API is added as provider OpenAI"). Ship presets for OpenAI, Anthropic, Google, Groq, Mistral, OpenRouter, Together, Ollama, LM Studio, vLLM, plus one generic "OpenAI-compatible" preset with base URL + key + custom headers (Continue's `requestOptions.headers` and Raycast's `additional_parameters` cover gateways needing non-Bearer auth).
9. **Store keys in the OS keychain, never in the config file; let env vars override.** Zed: system keychain with an explicit "Do not put API keys in settings.json" warning, plus `ANTHROPIC_API_KEY`-style env overrides. Continue: `${{ secrets.VAR }}` interpolation so shared configs stay clean. If config files must exist, they should reference the secret store, not contain it.
10. **Normalize every provider error to one typed shape with a stable code, and honor Retry-After.** OpenRouter's `{error: {code, message, metadata.error_type}}` with typed `error_type` values (authentication, payment_required, rate_limit_exceeded, context_length_exceeded, provider_unavailable) plus `Retry-After` on 429/503/402. LiteLLM maps all providers to OpenAI exception classes. Branch UI on the type: 401 points at the key field, 402 at billing, 404 at the model name, 429 at a wait-and-retry affordance.
11. **Handle mid-stream errors in the streaming protocol.** OpenRouter delivers errors as SSE events with `finish_reason: "error"` after a 200. Local-first desktop apps streaming to users must do the same: a dead stream should surface a typed error in the chat UI, not just hang.
12. **Make the privacy/routing story explicit per provider.** Raycast documents which BYOK requests go through its servers and which go direct; Cursor states keys are never stored but requests are routed through Cursor's backend. A local-first app should show, per connection, whether requests leave the machine (and through whom).
13. **Layered budgets: per-key cap, reset window, workspace ceiling.** OpenRouter (key `limit` + `limit_reset` + workspace budget + guardrails), LiteLLM (`max_budget`, `budget_duration`, `tpm/rpm_limit`, and `upperbound_key_generate_params` rejecting over-policy requests with 400 instead of clamping). Even a minimal "monthly cap per key, hard stop" puts agent-desk ahead of most desktop tools.
14. **Fallbacks and routing as configuration.** LiteLLM's `fallbacks`, `context_window_fallbacks`, `content_policy_fallbacks`, `allowed_fails` + `cooldown_time`, and OpenRouter's provider allow/deny lists show the pattern: the job (model+key) can name a fallback job, and unhealthy upstreams get cooled down rather than retried blindly. Also support model aliases (LiteLLM `model_group_alias`, OpenRouter `latest` aliases) so users can pin "best cheap model" without editing every job.
15. **Document and UI-name the common failure modes.** LobeChat ships a troubleshooting triple (invalid key: check spaces/type; model unavailable: tier/retired; rate limit: slow down or switch). Dify names "you pasted the full /chat/completions URL" as an error cause. A base-URL field should validate against trailing path mistakes and say so in the error text.
16. **Deep-link to the provider's key console from the add-key UI.** Raycast's "Manage in [Provider] Console" removes the biggest first-run stumbling block (where do I even get a key). Every preset should ship its console URL.

# ANTI-PATTERNS TO AVOID

1. **No validation on save (Cursor today).** Keys save silently; "requests using that provider fail until you update or remove the key". The user pays for the mistake with a broken chat later, with no link back to the offending field.
2. **Validation coupled to a specific model (Cursor's old bug).** A Verify call that hardcodes one model (gpt-4o) breaks for users of gateways without that model. Validation must be model-independent.
3. **Silent overwriting or clamping of key policies.** If a user requests a budget above policy, reject with 400 (LiteLLM) rather than silently clamping, and never let a new key bypass existing spend counters (an OpenRouter documented pitfall: "new keys don't bypass member budgets").
4. **Key entry disabled or hidden behind mode toggles.** Cursor forum threads are full of BYOK fields that were visually disabled or vanished after upgrades (issue reports from 2026). BYOK UI must degrade gracefully and never strand a saved key behind a hidden setting.
5. **One key field for everything.** A single global "API key" with no provider concept forces env-var gymnastics (Aider's `--api-key provider=` exists precisely because of this) and makes per-job assignment impossible.
6. **Model lists that lie or block.** Blocking save when /models fails (instead of falling back to a manual list), or showing catalog models the key cannot access (account-tier errors later). Dify/Open WebUI handle both by validating the credential and letting the user curate.
7. **Storing raw keys in config files or shipping them in exports.** Zed explicitly warns against keys in settings.json; n8n treats the encryption key as root secret; LobeChat separates KEY_VAULTS_SECRET. A local-first app syncing config across machines must sync references, not secrets.
8. **Error strings from the upstream shown raw as the only UI.** OpenRouter masks provider server errors; Anthropic says compat-layer errors are "for logging/debugging". Map to a small typed set and show an actionable message plus the raw detail behind a disclosure.
9. **Conflicting overrides left armed.** Cursor staff debugging: a stale OpenAI base URL override breaks Anthropic requests. When a user sets a per-provider key, detect and warn about leftover overrides for other providers.
10. **Assuming the OpenAI-compat layer is complete.** Anthropic's compat endpoint silently ignores many parameters and lacks caching/PDFs/citations; forced tool calls 400 on some models; `json_object` 400s. Treat compatibility as a capability matrix (Zed's `capabilities` object is the model), not a boolean.

---

## Verification notes

All first-party doc pages listed above were fetched on 2026-11-21 except where noted as "fetched via search result content" (page content was returned inside search results; URL and quotes are from that content). Claims marked UNVERIFIED: OpenRouter dashboard key-creation steps and credit-purchase minimums, Continue.dev exact "Connect" UI labels (third-party guide), Raycast AES/AES-GCM encryption of saved keys for LobeChat (third-party), Aider `.aider.model-settings.yml` field details, LiteLLM `drop_params` (mentioned in third-party configs only). Cursor forum statements about the removed Verify button are staff statements on official Cursor forums (community source, quoted verbatim).
