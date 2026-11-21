# Multi-key / multi-provider management: data models, API surfaces, UI patterns

Research for agent-desk BYOK (local-first, Python + SQLite + React SPA, localhost). Researched 2026-11-21 against live docs and source. All quotes verbatim from fetched pages unless marked UNVERIFIED.

Scope: how real products model stored LLM credentials, bind a key/model to a job, discover models, expose CRUD over credentials, and lay out the settings UI. Ends with RECOMMENDED SHAPE FOR AGENT-DESK.

---

## 1. Credential / record shapes

### 1.1 LiteLLM (proxy): two separate concepts, connection credentials vs virtual keys

LiteLLM splits "upstream provider credential" from "key handed to callers". Source: Prisma schema at `litellm/schema.prisma` (https://github.com/BerriAI/litellm/blob/main/litellm/schema.prisma) and docs at https://docs.litellm.ai/docs/proxy/virtual_keys, https://docs.litellm.ai/docs/proxy/db_info.

**LiteLLM_CredentialsTable** (stored upstream provider credentials, referenced by deployments as `credential_name`):

```
credential_id      String  @id @default(uuid())
credential_name    String  @unique
display_name       String?
credential_values  Json          // the actual secrets (api_key etc.)
credential_info    Json?
created_at         DateTime @default(now())
created_by         String
updated_at         DateTime @updatedAt
updated_by         String
```

Security analyses confirm `credential_values` holds raw provider keys ("A single `litellm_credentials` row often holds an OpenAI organization key ... an Anthropic console key ... and an AWS Bedrock IAM credential", https://www.sysdig.com/blog/cve-2026-42208-targeted-sql-injection-against-litellms-authentication-path-discovered-36-hours-following-vulnerability-disclosure).

**LiteLLM_VerificationToken** (virtual keys; the `sk-` keys issued to users/apps). Fields from schema.prisma, grouped:

```
token                String  @id            // the sk- hash
key_id               String? @unique @default(uuid())
key_name             String?
key_alias            String?
key_type             String?
user_id / team_id / agent_id / project_id / organization_id  String?
models               String[]               // model allowlist on the key
aliases              Json @default("{}")
config               Json @default("{}")
router_settings      Json
permissions          Json @default("{}")
metadata             Json @default("{}")
blocked              Boolean?
max_budget           Float?
budget_duration      String?                // "30d"
budget_reset_at      DateTime?
spend / total_spend  Float @default(0.0)
model_spend / model_max_budget / budget_fallbacks  Json
tpm_limit / rpm_limit / tpd_limit           BigInt?
max_parallel_requests Int?
expires              DateTime?
allowed_cache_controls / allowed_routes / policies / access_group_ids  String[]
auto_rotate          Boolean? @default(false)
rotation_interval    String?
last_rotation_at / key_rotation_at / rotation_count
last_active          DateTime?
created_at / created_by / updated_at / updated_by
```

**LiteLLM_ProxyModelTable** (a model deployment):

```
model_id        String @id @default(uuid())
model_name      String          // public name, can repeat across deployments (routing)
litellm_params  Json            // model, api_key, api_base, credential_name, ...
model_info      Json?
blocked         Boolean @default(false)
created_at / created_by / updated_at / updated_by
```

Key API: `POST /key/generate` with body `{"models": [...], "max_budget": 50.0, "budget_duration": "30d", "metadata": {...}}` (https://docs.litellm.ai/docs/proxy/virtual_keys). Note `last_active` (LiteLLM's name for last_used_at on a key) and per-key `models[]`: the binding of "which key can call which model" lives on the key record.

Takeaway for a single-user app: you need only the credentials side (one row per saved upstream key), plus a pointer from job to connection; LiteLLM's virtual-key budget/model columns are multi-tenant machinery you do not need, but `last_active`, `blocked`, and `models[]` are cheap and useful.

### 1.2 Open WebUI: connections as parallel arrays + per-connection config objects

Instance-wide connections live in Settings > Admin > Connections; persisted config mirrors env vars (each is "a `ConfigVar` variable", i.e. stored in the DB and editable in the admin UI). From https://docs.openwebui.com/reference/env-configuration:

```
#### `OPENAI_API_KEYS`
   Type: `str`
   Description: Supports multiple OpenAI API keys, semicolon-separated.
   Example: `sk-124781258123;sk-4389759834759834`

#### `OPENAI_API_CONFIGS`
   Type: `str (JSON)`
   Default: `{}`
   Description: Per-connection configuration for the OpenAI-compatible backends, as a JSON
   object keyed by the connection's index in `OPENAI_API_BASE_URLS` (its URL is also accepted
   as a legacy key). Each entry mirrors the per-connection settings from the admin UI, for
   example `enable`, `prefix_id`, `model_ids`, `tags`, and `connection_type`.
   Example: `{"0": {"enable": true, "prefix_id": "openai", "model_ids": ["gpt-5.6-sol"]}}

#### `OLLAMA_API_CONFIGS`
   (same shape, keyed by index in `OLLAMA_BASE_URLS`)
   Example: `{"0": {"enable": true, "prefix_id": "local", "model_ids": ["qwen3.6:27b"]}}
```

So the effective record is: `base_url + api_key + enable + prefix_id (disambiguates two connections to the same provider) + model_ids (allowlist/filter) + tags + connection_type + headers (JSON, with template placeholders like {{USER_EMAIL}})`. Connections also carry a Provider dropdown (OpenAI, Azure OpenAI, Anthropic, OpenAI-compatible) with extra fields per type, e.g. Azure needs "API Version" and "Model IDs (deployment names)" (https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible). Users can additionally hold personal keys via Direct Connections (browser calls the provider directly, bypassing the server backend) (https://docs.openwebui.com/features/chat-conversations/direct-connections).

### 1.3 LobeChat / LobeHub: per-user encrypted key vaults + provider records

Server DB mode stores provider credentials encrypted: `.env.example` comment, verbatim: "use `openssl rand -base64 32` to generate a key for the encryption of the database ... we use this key to encrypt the user api key and proxy url" (`KEY_VAULTS_SECRET`) (https://github.com/lobehub/lobehub/blob/main/.env.example). Multiple keys per provider env var are supported with a selection strategy: "Specify your API Key selection method, currently supporting `random` and `turn`" (`API_KEY_SELECT_MODE=random`), i.e. `OPENAI_API_KEY=key1,key2,key3` rotates/round-robins (same .env.example; also documented in feature request https://github.com/lobehub/lobe/issues/12288).

The provider record itself is managed over tRPC (`apps/server/src/routers/lambda/aiProvider.ts` in https://github.com/lobehub/lobehub). Procedures: `getAiProviderList`, `getAiProviderById`, `createAiProvider` (duplicate id raises CONFLICT), `updateAiProvider`, `updateAiProviderConfig` (encrypts key vaults via a "gate keeper"), `removeAiProvider`, `toggleProviderEnabled` (official providers cannot be disabled), `updateAiProviderOrder` (user-defined sort), and `checkProviderConnectivity` (details in section 4). Secrets are encrypted on write and decrypted only server-side; restricted API-key scopes get `keyVaults` stripped entirely so "decrypted provider credentials" never reach the caller.

Custom provider fields (UI wizard, verbatim from https://github.com/lobehub/lobehub/discussions/21271): Provider ID (lowercase, immutable), Provider Name, Request Format (`openai`), Proxy URL (base URL), API Key. Each model entry then carries capability flags: "Support for Tool Calling, Support Vision and Maximum Context Window".

Env-var side for built-ins (LobeHub .env.example, verified defaults): `OPENAI_PROXY_URL` default `https://api.openai.com/v1`, `ANTHROPIC_PROXY_URL` default `https://api.anthropic.com`, `DEEPSEEK_PROXY_URL` default `https://api.deepseek.com/v1`, `OLLAMA_PROXY_URL` default `http://127.0.0.1:11434`, plus `*_MODEL_LIST` with grammar "+model to add, -model to hide, model=display name" (e.g. `OPENAI_MODEL_LIST=-all,+MODEL_ID`).

### 1.4 n8n: credential = type + name + encrypted data blob + ownership

Entity columns from source (`packages/@n8n/db/src/entities/credentials-entity.ts`, https://github.com/n8n-io/n8n):

```
name        string   @Column({ length: 128 })   // validators: Length(3, 128)
description string | null  "User-supplied note on what the credential is for. Blank is stored as null."
data        string   @Column('text')            // encrypted JSON blob, validator IsObject
type        string   @Column({ length: 128 })   // e.g. openAiApi, githubApi, httpHeaderAuth
shared      SharedCredentials[]                 // ownedBy/team access lives here, not on the row
isManaged   boolean  @Column({ default: false })
isGlobal    boolean  "Whether the credential is available for use by all users."
usageScope  'project' | 'instance'  default 'project'
(resolver fields: isResolvable, resolvableAllowFallback, resolverId, pendingAuthorizationExpiresAt)
+ id, createdAt, updatedAt from WithTimestampsAndStringId
```

`data` is the entire typed payload as one encrypted JSON string (per-type schema, see section 4). Encryption: credentials are encrypted with `N8N_ENCRYPTION_KEY`; since n8n 3.0 a two-layer model exists: "Instance encryption key (`N8N_ENCRYPTION_KEY`): your master key ... Data encryption key: the key that directly encrypts your credential data. This is the key you rotate. n8n stores it encrypted in the database, protected by the instance key." (https://docs.n8n.io/deploy/host-n8n/configure-n8n/security/rotate-encryption-keys). Default deployments keep this in `~/.n8n/database.sqlite` (https://blog.gitguardian.com/n8n-security-encryption-key-compromise).

### 1.5 Continue.dev: models[] entries each with provider + apiKey + apiBase + roles

config.yaml is a flat list of model entries; each entry fully specifies connection and role. Verbatim field docs (https://docs.continue.dev/reference):

```
name     (required): A unique name to identify the model within your configuration.
provider (required): The provider of the model (e.g. `openai`, `ollama`).
model    (required): The specific model name (e.g. `gpt-4`, `starcoder`).
apiKey:  API key (supports ${{ secrets.VAR }} interpolation).
apiBase: Can be used to override the default API base that is specified per model.
roles:   chat, autocomplete, embed, rerank, edit, apply, summarize. Default [chat, edit, apply, summarize].
capabilities: e.g. tool_use, image_input.
defaultCompletionOptions: temperature, maxTokens, ...
useResponsesApi / useLegacyCompletionsEndpoint: endpoint-shaping flags.
contextLength: Maximum context length of the model (config.json reference; default 2048).
```

Real example (https://docs.continue.dev/reference):

```yaml
name: My Config
version: 1.0.0
schema: v1
models:
  - name: GPT-4o
    provider: openai
    model: gpt-4o
    roles: [chat, edit, apply]
    defaultCompletionOptions: {temperature: 0.7, maxTokens: 1500}
  - name: My Model - OpenAI-Compatible
    provider: openai
    apiBase: https://my-proxy.example.com/v1
    model: my-custom-model
    capabilities: [tool_use, image_input]
    roles: [chat]
```

Note: in Continue the unit of configuration is the model, not the key; several models repeat the same apiKey. YAML anchors (`model_defaults: &model_defaults`) are the dedup mechanism.

### 1.6 OpenRouter account keys: label, spend limit, usage counters, last_used_at

From the create-key API reference (https://openrouter.ai/docs/api/api-reference/api-keys/create-a-new-api-key), verbatim response shape:

```json
{
  "data": {
    "created_at": "...",
    "disabled": false,
    "include_byok_in_limit": true,
    "label": "My New API Key",
    "last_used_at": null,
    "limit": 50,
    "limit_remaining": 50,
    "limit_reset": "monthly",
    "name": "My New API Key",
    "usage": 0,
    "usage_daily": 0,
    "usage_monthly": 0,
    "usage_weekly": 0,
    "workspace_id": "0df9e665-..."
  },
  "key": "sk-or-v1-<64 hex characters, returned exactly once at creation>"
}
```

Fields worth copying: `label` (free-text name), `limit` + `limit_reset` + `limit_remaining` (per-key spend cap, "Keys created for you during onboarding get a $100 credit limit and expire after 180 days"), `last_used_at`, `usage*` counters, and the full key returned exactly once at creation (https://openrouter.ai/docs/api_reference/authentication). The Management API (https://openrouter.ai/docs/guides/overview/auth/management-api-keys) offers list/create/get/update (`PATCH /api/v1/keys/{hash}` with `{"disabled": true}`) with keys identified by hash.

### 1.7 Dify: provider record + one or more credentials per provider + enabled models

Docs (https://docs.dify.ai/en/self-host/use-dify/workspace/model-providers): a provider is installed (plugin), then "click `Add API Key` on the provider card, then enter the key and any other credentials the provider asks for, such as a custom endpoint URL or organization ID. Dify validates the credentials before making the provider available." Multi-key is first class: "Add more than one key to a provider when you want to keep development and production apart or spread usage across several accounts." Custom models can carry their own credentials ("If the model you add matches the name and type of an existing one, Dify attaches the new key to that model instead of creating a duplicate").

Plugin YAML defines the credential form schema, verbatim example (https://docs.dify.ai/en/develop-plugin/dev-guides-and-walkthroughs/creating-new-model-provider):

```yaml
provider_credential_schema:
  credential_form_schemas:
    - variable: anthropic_api_key
      label: {en_US: API Key}
      type: secret-input
      required: true
    - variable: anthropic_api_url
      label: {en_US: API URL}
      type: ...
# and two configuration methods:
#   predefined-model: one provider credential unlocks all predefined models
#   customizable-model: per-model credentials (model name + api key + endpoint)
```

REST for credentials (from maintainer answer, https://github.com/langgenius/dify-official-plugins/issues/2230):

```
POST /workspaces/current/model-providers/{provider}/credentials
     body: {"credentials": {...}, "name": "optional-credential-name"}   // name max 30 chars
POST /workspaces/current/model-providers/{provider}/models/credentials
     body: {"model": "model-name", "model_type": "model-type",
            "credentials": {...}, "name": "optional-credential-name"}
```

---

## 2. Per-job / per-feature binding

- **Continue.dev roles** are the canonical example: one config, per-role model selection. "Chat: conversational interactions ... Autocomplete: real-time suggestions as developers type ... A frontier model in Agent mode, a fast local model on autocomplete, a mid-tier hosted model on chat: three providers, one config, zero glue code." Role mapping from the migration guide: "`models` in config should have `roles: [chat]`, `tabAutocompleteModel` -> `roles: [autocomplete]`, `embeddingsProvider` -> `roles: [embed]`, `reranker` -> `roles: [rerank]`" (https://docs.continue.dev/reference/yaml-migration). Users also pick the active chat model from the IDE dropdown.
- **Dify default models per job type**: "Apps and nodes that don't pick a model fall back to your workspace defaults. Click `Default Models` at the top-right corner to set one for each job: System Reasoning Model, Embedding Model, Rerank Model, Speech-to-Text Model, Text-to-Speech Model" (https://docs.dify.ai/en/self-host/use-dify/workspace/model-providers). Notably Dify does NOT support per-agent key binding for the main LLM: "The platform allows you to configure multiple API keys per provider and select credentials (via `credential_id`) for tools invoked by agents, but this selectivity only applies to agent tools, not to the agent's own LLM chat/completion calls" (https://github.com/langgenius/dify/discussions/25955).
- **Raycast per-command model**: custom provider models "show up in the model picker grouped under the provider's name ... Pick them anywhere you'd pick a Raycast AI model, including Quick AI, AI Chat, and AI Commands" and there is a global "AI Commands Model" picker in the AI settings tab (https://manual.raycast.com/ai/custom-providers, https://remi.space/blog/raycast-ai-vibeproxy). BYOK is one key per provider, verified via a Verify button (https://manual.raycast.com/ai/bring-your-own-key).
- **n8n per-node credential pick**: nodes reference a credential by id in their parameters; "It's good practice to give them names that identify the app or service, type, and purpose of the credential" (https://docs.n8n.io/build/understand-workflows/create-and-edit-credentials). This is the strongest pattern for agent-desk's "different keys for different jobs": the job row stores the credential id.
- **LiteLLM key-to-model binding**: `models[]`, budgets, and team/user/project on the virtual key (section 1.1) is the gateway version of the same idea.
- **LangChain/LangGraph agent configs**: agent constructors take a model instance per agent (`create_react_agent(model=...)`), so per-agent model choice is just code-level composition; there is no stored binding table. UNVERIFIED against current docs in this pass; treat Continue/Dify/Raycast/n8n as the pattern sources.

---

## 3. Model discovery

**GET {base_url}/v1/models is the standard picker-population mechanism:**

- OpenRouter: `GET /api/v1/models`, response fields verbatim (https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties):

```json
{
  "architecture": {"input_modalities": ["text"], "modality": "text->text", "output_modalities": ["text"], "tokenizer": "GPT"},
  "canonical_slug": "openai/gpt-4",
  "context_length": 8192,
  "created": 1692901234,
  "description": "GPT-4 is a large multimodal model ...",
  "id": "openai/gpt-4",
  "name": "GPT-4",
  "pricing": {"completion": "0.00006", "image": "0", "prompt": "0.00003", "request": "0"},
  "supported_parameters": ["temperature", "top_p", "max_tokens"],
  "top_provider": {"context_length": 8192, "is_moderated": true, "max_completion_tokens": 4096}
}
```

  So context length, pricing, and capability flags all come from the models endpoint; a per-endpoint breakdown is available at `/api/v1/models/{author}/{slug}/endpoints` including per-provider `context_length`, `pricing`, `uptime_last_30m` (https://openrouter.ai/docs/api_reference/models).
- Raycast custom providers have a "Sync Models" action that "queries the selected custom provider's OpenAI-compatible `/models` endpoint, uses its configured API key, validates the full response before writing, maps available context/capability metadata, and leaves the existing catalog untouched on failure" (https://github.com/raycast/extensions/issues/28414).
- LobeChat UI: "In Model List, click `Fetch models`, or `Add Model` and type `MODEL_ID` exactly" (https://github.com/lobehub/lobehub/discussions/21271); the docs flow adds "Enable a model in the model list" and "Select Check to test the connection" (https://docs.qcode.cc/en/docs/ide/lobechat).
- Open WebUI auto-detects: "Adding a provider is as simple as entering a URL and API key in Settings -> Admin -> Connections. Open WebUI auto-detects available models from most providers" (https://docs.openwebui.com/getting-started/quick-start/connect-a-provider). It also serves its own `GET /v1/models` for downstream clients (https://docs.openwebui.com/reference/api-endpoints).
- LM Studio local server exposes `GET /v1/models`, `POST /v1/chat/completions` etc. on `http://localhost:1234/v1` (https://lmstudio.ai/docs/developer/openai-api).

**Caching:** model lists are cached and refreshed on demand or on a schedule. Kilo (agent IDE) resolves token limits in this order: "1. Your config ... 2. Built-in catalog, Kilo ships a snapshot of models.dev and refreshes it hourly ... 3. Fallback" (https://kilo.ai/docs/code-with-ai/agents/custom-models). Open WebUI caches the merged model list server-side with an explicit refresh (discussion of model-list refresh behavior in https://docs.openwebui.com/features/chat-conversations/direct-connections).

**Manual entry fallback** (endpoints without /models): Anthropic's OpenAI-compat layer documents no models listing endpoint at all (its OpenAI SDK page, see below, only covers chat completions), and some gateways omit it; every product therefore allows typed model IDs: Open WebUI "Model IDs" allowlist field per connection, "Strongly recommended" for OpenRouter ("OpenRouter exposes thousands of models, which will clutter your model selector") (https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible); Dify "Add Model" with Model Name, Model Type, credentials, "API endpoint URL", "Model name in API endpoint", context length, max tokens (https://docs.dify.ai/en/self-host/use-dify/workspace/model-providers); Continue supports `model: AUTODETECT` "to get all available models" for providers that do list (https://docs.continue.dev/reference/json-reference).

**Anthropic compat quirks** (https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk): base URL `https://api.anthropic.com/v1/`; verbatim: "This compatibility layer is primarily intended to test and compare model capabilities, and is not considered a long-term or production-ready solution for most use cases." Only chat completions is described (no /models listing documented); `response_format` only works with `json_schema` + `strict: true`; prompt caching unavailable; many fields silently ignored (`seed`, `logit_bias`, `reasoning_effort`, ...). Design consequence: treat Anthropic-compat as a manual-model-list provider.

**Metadata sources beyond the endpoint:** models.dev, "an open-source database of AI model specifications, pricing, and capabilities", TOML in GitHub, JSON at `api.json` / `models.json` / `catalog.json`, with per-provider env vars, limits and cost; used by OpenCode and Kilo as their built-in catalog (https://github.com/anomalyco/models.dev, https://models.dev, https://kilo.ai/docs/code-with-ai/agents/custom-models). Useful when a gateway's /models returns bare ids with no context_length: look up `limit.context` / `limit.output` from the catalog.

---

## 4. API surface conventions

**n8n public REST** (base `/api/v1`, header `X-N8N-API-KEY`; scopes `credential:create/read/list/update/delete/move`, https://docs.n8n.io/connect/n8n-api/authentication):

```
GET    /api/v1/credentials                          // list (owner/admin only; data omitted)
POST   /api/v1/credentials                          // {name, type, data: {...}} 
GET    /api/v1/credentials/{id}
DELETE /api/v1/credentials/{id}
GET    /api/v1/credentials/schema/{credentialTypeName}   // JSON Schema for the type's data fields
POST   /api/v1/credentials/{id}/test                // test a credential
```

Verified via community threads with verbatim examples: `GET /api/v1/credentials/schema/clickUpApi` returns `{"properties": {"accessToken": {"type": "string"}}, "required": [], ...}` and creation is `POST /api/v1/credentials` with `{"name": "My ClickUp API", "type": "clickUpApi", "data": {"accessToken": "YOUR_API_KEY"}}` (https://community.n8n.io/t/creating-credentials-using-api/68343); the `/test` and `/schema` routes are confirmed in the published OpenAPI (https://apis.io/apis/n8n/n8n-credential-api). The schema-per-type endpoint is the pattern worth copying when credential shapes vary by provider.

**Dify REST**: see section 1.7; credentials are created/validated per provider and per model, response includes the credential record; deletion and listing analogous (all under `/workspaces/current/model-providers/...`).

**LobeChat tRPC** (server mode): `aiProvider.create/update/remove/toggleEnabled/updateOrder/getList`, `aiProvider.checkProviderConnectivity({id, model?})` which either runs a credential-only check or "sends a minimal chat request ('Hi', temperature 0) via the one-shot relay, checking for a relayed `error` event" and returns `{ok, error?, model?, status?}` (source in section 1.3). The parallel `apiKey` router (LobeHub's own API keys, not provider keys) shows the masking convention: create returns the plaintext key "exactly once", reads strip `key`/`keyHash`, update takes `{id, value: {enabled, name, expiresAt, scopes}}`.

**Key-return conventions across products** (masked, never full, except once at creation):
- OpenRouter: full `sk-or-v1-...` only in the create response; afterwards keys are identified by hash, `GET /api/v1/key` returns `limit_remaining` etc. but not the secret (https://openrouter.ai/docs/api/api-reference/api-keys/create-a-new-api-key).
- LobeChat: `keyVaults` encrypted at rest; stripped from responses for restricted scopes; plaintext key shown once on create (sources above).
- n8n: `data` returned encrypted/omitted over the public API; decryption only inside the app via the encryption key (rotate-encryption-keys doc above).
- LiteLLM: virtual keys stored as SHA-256 hashes ("every active virtual key (as a SHA-256 hash)", https://bishopfox.com/blog/cve-2026-42208-pre-authentication-sql-injection-in-litellm-proxy).
- Raycast BYOK UI: paste key, Verify, stored in OS-secured storage; never displayed again (https://manual.raycast.com/ai/bring-your-own-key).

**Test/validate endpoint designs:**
- n8n: `POST /api/v1/credentials/{id}/test` (above).
- LobeChat: `checkProviderConnectivity` with two modes: credential-only for providers with `checkMode: 'credentials'`, else a 1-token chat probe (source above). UI button is labeled "Check"; docs warn "Check passes but chat fails: the test model may differ from the one you chose" (https://github.com/lobehub/lobehub/discussions/21271).
- Raycast: "click Verify. Raycast will check the key with the provider to ensure it can be used" (https://manual.raycast.com/ai/bring-your-own-key).
- Dify: validation happens on save ("Dify validates the credentials before making the provider available").
- Open WebUI: per-connection edit dialog + Verify button in Admin Connections; failed connections show per-connection status (https://docs.openwebui.com/getting-started/quick-start/connect-a-provider). UNVERIFIED: exact button label.

**"Which key will this job use" resolution order** (synthesized from observed products): explicit binding on the job (n8n node credential id, Dify tool `credential_id`, Continue role assignment) > workspace/instance default (Dify Default Models, Open WebUI default model, Raycast AI Commands Model) > single available credential > error listing the unbound job. LiteLLM instead resolves by key permissions at request time (virtual key -> `models[]` allowlist -> deployment routing on `model_name`).

---

## 5. UI layout conventions

- **Dedicated settings page beats modal for management; modal for creation.** Open WebUI: Settings > Admin > Connections (a full page, per-connection rows with an edit dialog); user-level personal keys under Settings > Connections when Direct Connections is enabled (https://docs.openwebui.com/getting-started/quick-start/settings). LobeChat: "App Settings -> AI Providers", provider list with on/off switches, per-provider credential panel with a Check button and model list (https://lobehub.com/docs/usage/providers/openai, https://docs.qcode.cc/en/docs/ide/lobechat). Dify: Settings > Model Provider page: provider cards in a grid with logos at top once configured, "Install model providers" catalog below, Default Models button top-right (https://docs.dify.ai/en/self-host/use-dify/workspace/model-providers). Raycast: Settings -> AI -> Models & Providers with an "API Keys" section and Custom Providers via a YAML file (https://manual.raycast.com/ai/bring-your-own-key, https://manual.raycast.com/ai/custom-providers). n8n: credentials created in a modal opened from the node that needs them ("Create new credential" inside the node's credential dropdown), then reused; credentials list lives in the left sidebar Credentials section (https://docs.n8n.io/build/understand-workflows/create-and-edit-credentials).
- **Add-provider wizard steps** (LobeChat custom provider, verbatim): "1. Create the provider (Provider ID, Provider Name, Request Format: openai, Proxy URL, API Key). 2. Check and add models (Connectivity Check -> Check ... Model List -> Fetch models, or Add Model)". Dify's equivalent: pick provider card -> "Add API Key" -> validated -> models appear -> optionally "Add Model" for unlisted ones -> set Default Models. (Sources above.)
- **Provider grid with logos + status**: Dify provider cards each show key count and model count; Open WebUI connection rows show enabled state; LiteLLM admin UI shows Model Management -> Health Status ("Your model should appear as connected ... Click Health Check", https://docs.sambanova.ai/docs/en/v2.2.6/sambastack/reference-architecture/litellm). LobeChat check produces "Check passed" inline status (discussion 21271).
- **Test button placement**: inside the credential edit form (LobeChat "Select Check to test the connection"; Raycast "Verify" inside the add-key sheet; n8n "Test connection" inside the credential modal). Convention: test lives next to the key input, not on the list row; agent-desk can do both cheaply.
- **Default-key indicator**: products mostly mark a default model rather than a default key (Dify Default Models per job type; Open WebUI user default model; Raycast AI Commands Model). Where multiple keys exist per provider, LobeChat exposes a selection strategy (random/turn) instead of a default. Dify exposes "Usage Priority" on the provider card (credits vs your key). A star on the default connection is agent-desk's simplification of these.
- **Conflict handling (two keys, same provider)**: Open WebUI allows N connections with the same base URL and disambiguates models via `prefix_id` (per-connection model prefix) and separate `model_ids` allowlists; LobeChat supports comma-separated keys per provider with random/turn selection, or multiple custom provider instances each with its own id and model list (https://github.com/lobehub/lobe/issues/12288); Dify keeps multiple named credentials per provider and picks per model/tool; LiteLLM allows multiple deployments with the same `model_name` and load-balances. Conclusion: the label/name plus per-connection model list is how everyone disambiguates; nothing enforces provider uniqueness.

---

## 6. Provider preset catalogs worth copying

Base URLs verified against live provider docs in this pass unless noted.

| Preset | Base URL | Notes / default models | Source |
|---|---|---|---|
| OpenAI | `https://api.openai.com/v1` | SDK default; /v1/models supported | LobeHub .env.example default; https://restfulapi.net/openai-compatible-api |
| Anthropic (OpenAI compat) | `https://api.anthropic.com/v1/` | Chat completions only; no models listing documented; eval-oriented ("not considered a long-term or production-ready solution") | https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk |
| OpenRouter | `https://openrouter.ai/api/v1` | 400+ models via one key; model ids `vendor/model`; /api/v1/models rich metadata | https://openrouter.ai/openai, https://openrouter.ai/docs/quickstart |
| Groq | `https://api.groq.com/openai/v1` | Verbatim from docs example | https://console.groq.com/docs/openai |
| Together | `https://api.together.ai/v1` | models.list supported; ids are `provider/model_name`; legacy host api.together.xyz/v1 still seen in older docs | https://docs.together.ai/docs/openai-api-compatibility |
| Google Gemini (OpenAI compat) | `https://generativelanguage.googleapis.com/v1beta/openai/` | "Support for the OpenAI libraries is still in beta"; batch upload/download not supported | https://aistudio.google.com/docs/openai |
| DeepSeek | `https://api.deepseek.com/v1` | LobeHub documented default | https://github.com/lobehub/lobehub/blob/main/.env.example |
| Mistral | `https://api.mistral.ai/v1` | UNVERIFIED in this pass (docs page moved); widely documented value | - |
| Ollama | `http://localhost:11434/v1` | api_key `'ollama'` "required but ignored"; cloud variant `https://ollama.com/v1` uses OLLAMA_API_KEY | https://docs.ollama.com/api/openai-compatibility, https://ollama.com/blog/openai-compatibility |
| LM Studio | `http://localhost:1234/v1` | /v1/models and /v1/chat/completions; use model identifier shown in LM Studio | https://lmstudio.ai/docs/developer/openai-api |
| vLLM | `http://localhost:8000/v1` | UNVERIFIED in this pass; conventional default for a local vLLM server | - |

Preset list shipping in products: LobeChat ships 30+ provider presets as env-var pairs (`ENABLED_X`, `X_API_KEY`, `X_PROXY_URL`, `X_MODEL_LIST`); Open WebUI ships four connection types (OpenAI-compatible, Ollama, Anthropic, Open Responses) plus provider-specific flavors (Azure); Dify ships a marketplace of provider plugins with per-provider credential forms; Continue ships a provider registry where `provider` selects default apiBase and wire protocol; Raycast ships BYOK presets for Anthropic/Google/OpenAI/OpenRouter plus a generic custom-provider YAML.

---

# RECOMMENDED SHAPE FOR AGENT-DESK

Minimal, single-user, local. Two tables, nine routes, four UI components. Converges on: n8n's "credential = named record referenced by id", LobeChat's "test button + fetch models", Dify's "default model per job type", Continue's "role/job mapping".

## SQLite schema

```sql
CREATE TABLE provider_connections (
  id               TEXT PRIMARY KEY,            -- uuid
  label            TEXT NOT NULL UNIQUE,        -- "OpenAI personal", "Work gateway cheap"
  provider         TEXT NOT NULL,               -- openai|anthropic|openrouter|groq|together|
                                                 -- gemini|deepseek|mistral|ollama|lmstudio|vllm|custom
  base_url         TEXT NOT NULL,               -- preset default, overridable
  api_key_enc      TEXT,                        -- AES-GCM encrypted; NULL/'' for local endpoints
  headers_json     TEXT,                        -- optional extra headers (corporate gateways)
  is_default       INTEGER NOT NULL DEFAULT 0,  -- default connection per provider
  enabled          INTEGER NOT NULL DEFAULT 1,
  status           TEXT NOT NULL DEFAULT 'unknown',  -- unknown|ok|error
  last_checked_at  TEXT, last_error TEXT, last_used_at TEXT,
  models_json      TEXT,                        -- cached [{id, context_length?}] from GET {base}/models
  models_fetched_at TEXT,
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE job_bindings (
  job_key       TEXT PRIMARY KEY,               -- 'chat.default', 'inbox_triage', 'presentation', 'summarize'
  connection_id TEXT NOT NULL REFERENCES provider_connections(id) ON DELETE CASCADE,
  model_id      TEXT NOT NULL,                  -- string sent as "model"
  updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Design notes: no `models[]` on the connection (that is LiteLLM multi-tenant machinery); allow multiple rows with the same `provider` (conflicts are disambiguated by label, the Open WebUI/LobeChat pattern); `last_used_at`/`last_error` copied from LiteLLM VerificationToken and OpenRouter keys; encrypt `api_key_enc` with an app key stored in the OS credential store (n8n/LobeChat pattern, see 03-key-security.md).

## REST routes (localhost only)

```
GET    /api/connections                     -> [{id, label, provider, base_url, masked_key ("sk-...ab12"),
                                                is_default, enabled, status, last_error, model_count}]
POST   /api/connections                     {label, provider, base_url?, api_key?}   -> full key never echoed
PATCH  /api/connections/{id}                partial; api_key replaced only when non-empty string sent
DELETE /api/connections/{id}                cascades job_bindings (UI warns which jobs were bound)
POST   /api/connections/{id}/test           -> {ok, latency_ms?, error?, models_found?}
                                                 test = GET {base}/models with key; fallback minimal
                                                 chat completion ("Hi", max_tokens 1) when /models 404s
                                                 (LobeChat two-mode check)
GET    /api/connections/{id}/models?refresh=0  -> cached models_json; refresh=1 re-fetches /v1/models and
                                                 updates models_fetched_at
GET    /api/jobs                            -> [{job_key, connection_id, model_id, resolved:{label, provider, status}}]
PUT    /api/jobs/{job_key}                  {connection_id, model_id}
```

Resolution rule for "which key will this job use": job_bindings row > default connection for that provider > single enabled connection > fail with an explicit "job unbound" error naming the job (n8n/Dify precedence). Masked keys only; full key never leaves the process after creation (OpenRouter/LobeChat convention).

## UI components

1. **Keys & Providers settings page** (not a modal): list rows with provider logo, label, masked key, base URL (secondary text), status badge (ok/error/unknown, from last test), star toggle for is_default per provider, Test button on row, overflow menu (Edit, Delete).
2. **Add connection form** (modal or inline): preset grid (from section 6 catalog) -> base_url auto-filled and editable -> API key password field (placeholder "not required for local endpoints") -> "Test and fetch models" button -> save. Manual model-id entry field always available (Anthropic-compat and gateways without /models).
3. **Job model picker**: per-job card "Model for this job": connection select (grouped by provider) + model select populated from models_json (or typed manually), showing which key will be used; mirrors Dify Default Models and n8n per-node credential pick.
4. **Connection health strip**: on app start or before a job runs, stale/error connections surface inline with a Re-test action (LiteLLM health-status pattern).

---

## Source index (primary)

- LiteLLM: https://github.com/BerriAI/litellm/blob/main/litellm/schema.prisma ; https://docs.litellm.ai/docs/proxy/virtual_keys ; https://docs.litellm.ai/docs/proxy/db_info ; https://www.sysdig.com/blog/cve-2026-42208-targeted-sql-injection-against-litellms-authentication-path-discovered-36-hours-following-vulnerability-disclosure ; https://bishopfox.com/blog/cve-2026-42208-pre-authentication-sql-injection-in-litellm-proxy
- Open WebUI: https://docs.openwebui.com/reference/env-configuration ; https://docs.openwebui.com/getting-started/quick-start/connect-a-provider ; https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible ; https://docs.openwebui.com/getting-started/quick-start/settings ; https://docs.openwebui.com/features/chat-conversations/direct-connections ; https://docs.openwebui.com/reference/api-endpoints
- LobeChat / LobeHub: https://github.com/lobehub/lobehub (apps/server/src/routers/lambda/aiProvider.ts, .env.example) ; https://lobehub.com/docs/usage/providers/openai ; https://lobehub.com/changelog/2025-01-22-new-ai-provider ; https://github.com/lobehub/lobehub/discussions/21271 ; https://github.com/lobehub/lobe/issues/12288 ; https://docs.qcode.cc/en/docs/ide/lobechat
- n8n: https://github.com/n8n-io/n8n (packages/@n8n/db/src/entities/credentials-entity.ts) ; https://docs.n8n.io/build/understand-workflows/create-and-edit-credentials ; https://docs.n8n.io/deploy/host-n8n/configure-n8n/security/rotate-encryption-keys ; https://docs.n8n.io/connect/n8n-api/authentication ; https://community.n8n.io/t/creating-credentials-using-api/68343 ; https://community.n8n.io/t/how-to-get-type-for-credentials-api/21795 ; https://apis.io/apis/n8n/n8n-credential-api
- Continue.dev: https://docs.continue.dev/reference ; https://docs.continue.dev/reference/yaml-migration ; https://docs.continue.dev/reference/json-reference ; https://docs.continue.dev/customize/model-providers/overview ; https://docs.continue.dev/customize/model-providers/top-level/openai
- OpenRouter: https://openrouter.ai/docs/api_reference/authentication ; https://openrouter.ai/docs/api/api-reference/api-keys/create-a-new-api-key ; https://openrouter.ai/docs/guides/overview/auth/management-api-keys ; https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties ; https://openrouter.ai/docs/api_reference/models ; https://openrouter.ai/docs/guides/overview/models ; https://openrouter.ai/docs/api_reference/limits ; https://openrouter.ai/openai
- Dify: https://docs.dify.ai/en/self-host/use-dify/workspace/model-providers ; https://docs.dify.ai/en/develop-plugin/dev-guides-and-walkthroughs/creating-new-model-provider ; https://github.com/langgenius/dify-official-plugins/issues/2230 ; https://github.com/langgenius/dify/discussions/25955
- Raycast: https://manual.raycast.com/ai/bring-your-own-key ; https://manual.raycast.com/ai/custom-providers ; https://manual.raycast.com/enterprise/custom-provider ; https://github.com/raycast/extensions/issues/28414
- Provider base URLs: https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk ; https://console.groq.com/docs/openai ; https://aistudio.google.com/docs/openai ; https://docs.together.ai/docs/openai-api-compatibility ; https://docs.ollama.com/api/openai-compatibility ; https://ollama.com/blog/openai-compatibility ; https://lmstudio.ai/docs/developer/openai-api
- Model metadata: https://models.dev ; https://github.com/anomalyco/models.dev ; https://kilo.ai/docs/code-with-ai/agents/custom-models
