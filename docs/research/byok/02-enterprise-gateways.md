# Enterprise BYOK patterns: SaaS platforms and AI gateways

Research date: 2026-11-21. All claims below were verified against the cited pages unless marked UNVERIFIED. Purpose: steal architectural patterns for agent-desk's BYOK system (multiple named providers, OpenAI-compatible endpoints, keys assigned to jobs).

---

## Part A: SaaS platforms that let customers plug in their own model keys

### A1. Databricks (external models / BYOSK, and the newer AI Gateway model provider services)

Two generations of the same idea.

**Generation 1: External models endpoints (BYOSK).** The platform holds the key; apps call the platform with a Databricks token and the platform brokers the call to the provider.

- Keys are supplied at endpoint creation and stored encrypted by Databricks: "Databricks encrypts and securely stores the provided credentials for each model provider." Credentials are deleted when the endpoint is deleted.
- Two ways to supply a key: a Databricks Secrets reference (`{{secrets/scope/key}}`, recommended) or a `*_plaintext` field. Every provider config pairs these (`openai_api_key` vs `openai_api_key_plaintext`).
- Apps authenticate with a Databricks PAT against an OpenAI-compatible surface; they never see the provider key.
- Supported providers: openai, anthropic, cohere, amazon-bedrock, google-cloud-vertex-ai, databricks-model-serving, and `custom` for any OpenAI-API-compatible proxy.
- Trust model: platform holds the key, brokers per request, adds AI Gateway governance (rate limiting, usage tracking, guardrails) on top. Data-residency caveat is explicit: your configuration may cause data to be processed outside the origin region.

Verbatim endpoint creation (source: https://docs.databricks.com/en/generative-ai/external-models.html):

```python
client.create_endpoint(
    name="anthropic-completions-endpoint",
    config={
        "served_entities": [
            {
                "name": "test",
                "external_model": {
                    "name": "claude-2",
                    "provider": "anthropic",
                    "task": "llm/v1/completions",
                    "anthropic_config": {
                        "anthropic_api_key": "{{secrets/my_anthropic_secret_scope/anthropic_api_key}}"
                    }
                }
            }
        ]
    }
)
```

Custom OpenAI-compatible provider with a bearer token (same page):

```python
"custom_provider_config": {
    "custom_provider_url": "https://api.provider.com/chat/completions",
    "bearer_token_auth": {
        "token": "{{secrets/my_custom_provider_secret_scope/custom_provider_token}}"
    }
}
```

Querying it with the OpenAI client, note the Databricks token, not the provider key (same page):

```python
client = OpenAI(
    api_key="dapi-your-databricks-token",
    base_url="https://example.staging.cloud.databricks.com/serving-endpoints"
)
```

**Generation 2: Unity Catalog model provider services.** The provider credential becomes a governed, securable object in the catalog (source: https://docs.databricks.com/aws/en/ai-gateway/create-model-provider-services):

- A provider service = `{provider_type, base_url, credential, targets (allowlist of upstream models), endpoint_route}`. Created via UI, REST (`POST /api/2.1/unity-catalog/model-provider-services`), Terraform, or SDKs.
- Credential options, in increasing governance strength:
  1. Inline plaintext (encrypted at rest, never shown again in the UI).
  2. Backed by a Unity Catalog secret: "The secret is read at query time under the service owner's access and never copied onto the service, so rotation requires no service change." Works for OpenAI, Azure OpenAI, Anthropic, Bedrock (both), Microsoft Foundry, Google Gemini Enterprise, Custom.
  3. Bedrock via UC service credential (IAM role): Databricks fetches short-lived AWS credentials per request. Callers need no privilege on the credential.
- Grants are SQL-securable, verbatim:

```sql
GRANT READ SECRET ON SECRET <catalog>.<schema>.<secret> TO `<model-provider-service-owner>`;
GRANT ACCESS ON SERVICE CREDENTIAL <service-credential-name> TO `<model-provider-service-owner>`;
```

- Consumers need `EXECUTE` on the service plus `USE CATALOG`/`USE SCHEMA`; revoking `READ SECRET` "stops queries for everyone, even callers who hold EXECUTE."
- Spend tracking built in: spend is estimated from list prices into `system.ai.gateway.external_model_spend`, with a configurable price multiplier (e.g. 0.8 for negotiated 80% of list). Rate limits: "Cap queries per minute to manage capacity and cost."
- There is even a BYO-subscription mode where each caller's Claude Max/ChatGPT subscription is used with no stored credential at all.

**Takeaway for agent-desk:** the "credential reference beats credential value" ladder (inline -> secret reference -> short-lived role), the "targets" allowlist per provider, and spend recorded per provider with a price multiplier.

### A2. Snowflake Cortex (network rules + secrets + API integrations)

Snowflake's BYOK for external LLM APIs is assembled from three first-class objects: a network rule (egress allowlist), a secret (the key), and an external access integration or API integration that binds them. The platform holds the key inside its secret store and code reads it by reference at runtime.

Verbatim setup for calling an external API from Cortex Agents (source: Snowflake engineering blog, https://medium.com/snowflake/integrating-third-party-apis-into-snowflake-cortex-agents-2802fe50ae9d):

```sql
CREATE OR REPLACE NETWORK RULE nasa_rule mode = egress type = host_port value_list = ('api.nasa.gov:443');

create or replace secret nasa_api_key type = generic_string secret_string = '<YOUR_API_KEY_HERE>';
```

Password-type secret plus integration (source: https://medium.com/snowflake/snowflake-cortex-rag-from-external-api-%EF%B8%8F-abc493bc155f):

```sql
CREATE NETWORK RULE ninja_rule
  TYPE = HOST_PORT
  MODE = EGRESS
  VALUE_LIST = ('api.api-ninjas.com');

CREATE or REPLACE SECRET ninja_api_key
  TYPE = password
  USERNAME = 'NOT_USED'
  PASSWORD = '<Your Access Token>';

CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION ninja_integration
  ALLOWED_NETWORK_RULES = (ninja_rule)
  ALLOWED_AUTHENTICATION_SECRETS = (ninja_api_key)
  ENABLED = true;
```

A UDF then binds the secret by name and reads it at call time (same page):

```sql
CREATE OR REPLACE FUNCTION historical_figure(person STRING)
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = 3.10
HANDLER = 'get_history'
EXTERNAL_ACCESS_INTEGRATIONS = (ninja_integration)
PACKAGES = ('requests')
SECRETS = ('api_key' = HISPERSON.public.ninja_api_key)
AS $$
import requests
import _snowflake

def get_history(person):
    api_key = _snowflake.get_username_password('api_key').password
    response = requests.get(api_url, headers={'X-Api-Key': api_key})
    ...
$$;
```

For external MCP servers, `CREATE API INTEGRATION` supports an `API_KEY = api_key` parameter and `API_ALLOWED_PREFIXES` / `API_BLOCKED_PREFIXES` to scope which URLs the integration may touch, plus `ENABLED = TRUE|FALSE` as a kill switch (source: https://docs.snowflake.com/en/sql-reference/sql/create-api-integration). Note the URL-level allow/deny lists: egress scope is part of the key's permission, not just the key value.

Cortex itself (AI_COMPLETE etc.) runs models from OpenAI, Anthropic, Meta, Mistral, DeepSeek, xAI inside Snowflake's governed boundary and bills per token in credits; a "hybrid" pattern calls external models for generation while keeping retrieval in Snowflake (sources: https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql, https://keebo.ai/blog/snowflake-cortex-versus-other-llm). Snowflake also ships an AI Gateway URL you can point tools at for spend attribution (source: https://docs.omni.co/ai/settings/model-providers/snowflake-cortex).

**Takeaway for agent-desk:** key = object with grants; network egress allowlist attached to the key; secrets read by reference at call time; disable flag on the integration.

### A3. Azure AI Foundry (now Microsoft Foundry): connections

Foundry models BYOK as "connections" attached to a project (source: https://learn.microsoft.com/en-us/azure/foundry/how-to/connections-add, formerly /azure/ai-foundry/concepts/connections):

- Connection types include Azure OpenAI, OpenAI, Serp, "API key" ("handle authentication to your specified target on an individual basis"), "Custom key" ("securely store and access keys while storing related properties, such as targets and versions ... you manage authentication"), Serverless Model, Azure APIM, and Model Gateway (the last two for governance of models called by Foundry Agent Service).
- Secrets live in a managed Azure Key Vault by default (not visible in your subscription); customers may attach their own Key Vault instead. Limit: one Key Vault connection per Foundry resource; secret migration is not supported, you recreate connections.
- Auth per connection is either API key or Microsoft Entra ID; RBAC gates who can add connections (Foundry User / Foundry Owner / Contributor). Up to 120 connections per project.
- Network isolation via private endpoints to each connected resource.

So the trust model is: platform stores the key in a vault it controls (or your vault), apps resolve connections by name at runtime through the Foundry SDK.

**Takeaway for agent-desk:** the "Custom key" connection type is exactly the corporate-gateway case: a bag of key + arbitrary properties (target, version) where the app manages how auth is applied.

### A4. AWS Bedrock

AWS now has several BYOK-adjacent surfaces:

1. **Bedrock API keys** (short-term and long-term bearer keys) (source: https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html):
   - Long-term keys are IAM service-specific credentials, generated per IAM user, controllable via SCPs, with a condition key `iam:ServiceSpecificCredentialAgeDays` to force expiry (e.g. 90 days).
   - Usage is controlled by IAM actions `bedrock:CallWithBearerToken` / `bedrock-mantle:CallWithBearerToken` with a `bearerTokenType` condition (`SHORT_TERM` or `LONG_TERM`), so you can grant "short-term keys only" as a policy.
   - Logging guarantee, verbatim: "All API calls are logged in AWS CloudTrail. API keys are passed as authorization headers and are not logged."
2. **OpenAI-compatible endpoints** (`bedrock-runtime` and `bedrock-mantle`) authenticated with either AWS SigV4 credentials or a Bedrock API key; model IDs use inference profiles like `global.openai.gpt-5.6-sol` (sources: https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html, https://developers.openai.com/api/docs/guides/amazon-bedrock). Cross-account/cross-region inference profiles (system profiles `us.*`, `global.*`) are how Bedrock routes to entitled models across regions.
3. **AgentCore Identity: bring your own secret.** Credential Providers reference a secret ARN in AWS Secrets Manager rather than storing the value. Verbatim CLI (source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-providers.html):

```
agentcore identity api-key-credential-provider create \
  --name your-service-name \
  --api-key-secret-reference '{"secretId": "arn:aws:secretsmanager:us-east-1:123456789012:secret:my-secret", "jsonKey": "api_key"}' \
  --region us-east-1
```

   Rules from the same page and the AWS blog (https://aws.amazon.com/blogs/machine-learning/reference-your-own-aws-secrets-manager-secrets-in-amazon-bedrock-agentcore-identity): the secret must be a JSON object and you name the `jsonKey` holding the credential; AgentCore calls `secretsmanager:GetSecretValue` at runtime; you own the CMK, tags, rotation, and resource policies; the service-managed vs BYO-secret choice is immutable (delete and recreate to switch); same region only.
4. **Custom model providers / bring your own endpoint** (registering external provider endpoints and invoking them through Bedrock): the user-guide pages exist (https://docs.aws.amazon.com/bedrock/latest/userguide/custom-model-providers.html, .../model-invocation-endpoint.html) but are JS-rendered and I could not extract the config details. UNVERIFIED beyond their existence.

**Takeaway for agent-desk:** short-lived vs long-lived key classes with policy-enforced max age; explicit "keys are never logged, calls are" audit split; secret-reference (ARN + JSON key) instead of raw value; immutable auth-mode choice per provider entry.

### A5. Google Vertex AI

Vertex is the counter-example: it is not key-first.

- Default auth is a service account (JSON key or ADC), plus project ID and region. Portkey's integration takes `Vertex Project ID` + `Vertex Region` + Service Account JSON, or a per-request OAuth2 token if you only configure project/region (source: https://docs.portkey.ai/docs/integrations/llms/vertex-ai).
- There is an Express Mode with a plain API key (`GOOGLE_API_KEY`) for simplified access; API key and OAuth/ADC are mutually exclusive (sources: https://www.promptfoo.dev/docs/providers/vertex, https://discuss.google.dev/t/how-to-connect-adk-agents-to-vertex-ai-api-key-setup-issue/186935).
- Gateways that inject static bearer headers struggle with Vertex because the service-account key must be locally signed into an OAuth token per request; kagent documents exactly this limitation (source: https://docs.solo.io/kagent/latest/setup/model-providers/google-vertexai).
- Google's own guidance for SaaS builders is to centrally manage service accounts and only ask customers for keys in a deliberate BYOK business model (source: https://support.google.com/gemini/thread/397427423).

**Takeaway for agent-desk:** not every provider is `Authorization: Bearer <key>`. The provider abstraction needs an auth kind (bearer header, custom header name, service-account signing, OAuth client credentials) and extra fields (project, region), matching Kong's and Databricks' custom-header options.

---

## Part B: LLM gateways companies deploy in front of many providers

### B1. LiteLLM proxy/gateway (the reference config shape)

Core model: `model_list` entries pair a public alias (`model_name`, what callers ask for) with deployment params (`litellm_params.model`, provider string + base_url + key). Multiple entries sharing one `model_name` are load-balanced; fallbacks and aliases route between names. Verbatim from https://docs.litellm.ai/docs/proxy/configs:

```yaml
model_list:
  - model_name: gpt-6.1-sol        ### RECEIVED MODEL NAME ###
    litellm_params:                 # all params accepted by litellm.completion()
      model: azure/gpt-6.1-sol-eu   ### MODEL NAME sent to litellm.completion() ###
      api_base: https://my-endpoint-europe-berri-992.openai.azure.com/
      api_key: "os.environ/AZURE_API_KEY_EU"   # does os.getenv("AZURE_API_KEY_EU")
      rpm: 6      # [OPTIONAL] Rate limit for this deployment: in requests per minute (rpm)
  - model_name: vllm-models
    litellm_params:
      model: openai/facebook/opt-125m   # the `openai/` prefix tells litellm it's openai compatible
      api_base: http://0.0.0.0:4000/v1
      api_key: none
      rpm: 1440
  # Default models: works for ALL Providers, needs default provider credentials in .env
  - model_name: "*"
    litellm_params:
      model: "*"

litellm_settings:
  drop_params: True
  success_callback: ["langfuse"]

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  alerting: ["slack"]
```

Routing and resilience, verbatim (same page):

```yaml
litellm_settings:
  num_retries: 3
  request_timeout: 10
  fallbacks: [{"zephyr-beta": ["gpt-6-luna"]}]
  context_window_fallbacks: [{"zephyr-beta": ["gpt-6.1-sol"]}]

router_settings:
  allowed_fails: 3            # cooldown a deployment once it fails more than 3 calls within cooldown_time
  routing_strategy: simple-shuffle   # or least-busy, usage-based-routing, latency-based-routing
  model_group_alias: {"gpt-5.6": "gpt-6-luna"}   # all requests with gpt-5.6 route to gpt-6-luna
```

Centralized credentials (define once, reference from many models, explicitly for secret rotation), verbatim (same page):

```yaml
model_list:
  - model_name: gpt-6.1-sol
    litellm_params:
      model: azure/gpt-6.1-sol
      litellm_credential_name: default_azure_credential   # Reference credential below

credential_list:
  - credential_name: default_azure_credential
    credential_values:
      api_key: os.environ/AZURE_API_KEY
      api_base: os.environ/AZURE_API_BASE
      api_version: "2023-05-15"
    credential_info:
      description: "Production credentials for EU region"
      custom_llm_provider: "azure"
```

Per-deployment environments (`model_info.supported_environments: [production, staging, development]`) gate which models are exposed where.

**Virtual keys** (internal-user keys decoupled from provider keys), from https://docs.litellm.ai/docs/proxy/virtual_keys:

```bash
curl 'http://0.0.0.0:4000/key/generate' \
  --header 'Authorization: Bearer <your-master-key>' \
  --header 'Content-Type: application/json' \
  --data-raw '{"models": ["gpt-6-luna", "gpt-6.1-sol"], "metadata": {"user": "ishaan@berri.ai"}}'
```

Key params: `max_budget` (USD), `budget_duration` ("10d"), `duration` ("30d"), `models` allowlist, `aliases` ({"gpt-6-luna": "my-free-tier"}), `tpm_limit`/`rpm_limit`, `max_parallel_requests`, `auto_rotate` + `rotation_interval`, `grace_period` ("48h": "Both old and new keys work until the grace period elapses, so you can cut over without production downtime"). Spend is computed per request with `completion_cost()` and stored per key/user/team (`LiteLLM_VerificationTokenTable` etc.), queryable via `/key/info?key=`. Keys can be blocked via `/key/block`, budgets temporarily raised via `/key/update` with `temp_budget_increase`.

Encryption: with `LITELLM_SALT_KEY` set, "the salt key encrypts and decrypts your stored credentials, and the master key is only an auth credential" (https://docs.litellm.ai/docs/proxy/docker_quick_start, https://docs.litellm.ai/docs/proxy/master_key_rotations). Note virtual keys are stored hashed, not encrypted.

### B2. Portkey (Prisma AIRS AI Gateway)

Config is a JSON object (self-hosted open-source gateway is stateless: each request can carry its config in the `x-portkey-config` header). Shapes, verbatim from https://docs.portkey.ai/docs/api-reference/inference-api/config-object and https://docs.portkey.ai/docs/product/ai-gateway/configs:

Single provider with retry:

```json
{
  "provider": "openai",
  "api_key": "sk-...",
  "retry": { "attempts": 3, "on_status_codes": [429, 500, 502, 503] }
}
```

Load balance across providers (weights), and nested strategies:

```json
{
  "strategy": { "mode": "loadbalance" },
  "targets": [
    { "provider": "@openai-prod", "weight": 0.7 },
    { "provider": "@azure-prod",  "weight": 0.3 }
  ]
}
```

```json
{
  "strategy": { "mode": "fallback", "on_status_codes": [429, 500] },
  "targets": [
    { "provider": "@openai-prod" },
    { "strategy": { "mode": "fallback", "on_status_codes": [429, 500] },
      "targets": [ { "provider": "@openai-backup" }, { "provider": "@anthropic-prod" } ] }
  ]
}
```

Conditional routing on request metadata (source: https://portkey.ai/blog/failover-routing-strategies-for-llms-in-production):

```json
{
  "strategy": {
    "mode": "conditional",
    "conditions": [
      { "query": { "metadata.user_plan": { "$eq": "paid" } }, "then": "finetuned-gpt4" },
      { "query": { "metadata.user_plan": { "$eq": "free" } }, "then": "base-gpt4" }
    ],
    "default": "base-gpt4"
  },
  "targets": [
    { "name": "finetuned-gpt4", "provider": "@xx", "override_params": { "model": "ft://gpt4-xxxxx" } },
    { "name": "base-gpt4",     "provider": "@yy", "override_params": { "model": "gpt-4" } }
  ]
}
```

Key modeling today: providers are registered once in the Model Catalog (dashboard: Model Catalog, Add Provider, paste key, name it e.g. `openai-prod`), then referenced by slug `@openai-prod` in configs and even in the model string: `model="@openai-prod/gpt-4o"` (source: https://docs.portkey.ai/docs/guides/getting-started/getting-started-with-ai-gateway). This replaces older "virtual keys": "Provider credentials stored securely, never exposed in code ... Fine-grained budgets, rate limits, and model allow-lists" (https://portkey.ai/docs/product/ai-gateway/virtual-keys). Targets support `override_params`/`default_params`/`drop_params`, `custom_host` for privately hosted models, `forward_headers`, and `passthrough: true` (let the incoming request decide the provider).

Secret references: instead of storing provider keys in Portkey, point at AWS Secrets Manager / Azure Key Vault / HashiCorp Vault; "The actual key never touches Portkey's storage. The data plane fetches the secret directly from your vault and caches it for 5 minutes ... Rotate a key in your vault, and every app picks it up automatically within minutes" (source: https://portkey.ai/blog/secret-references-ai-api-key-management). The self-hosted gateway also supports per-provider request/token rate limits in `conf.json` (source: https://geekflare.com/open-source/portkey-gateway).

### B3. Kong AI Gateway

Two config systems, both current.

**Classic: ai-proxy plugin on a route** (the app talks to Kong; Kong attaches the provider key). Verbatim `kong.yaml` (source: https://developer.konghq.com/plugins/ai-proxy/examples/openai-chat-route):

```yaml
_format_version: "3.0"
plugins:
- name: ai-proxy
  route: routeName|Id
  config:
    route_type: llm/v1/chat
    auth:
      header_name: Authorization
      header_value: Bearer ${{ env "DECK_OPENAI_API_KEY" }}
    model:
      provider: openai
      name: gpt-4
      options:
        max_tokens: 512
        temperature: 1.0
```

"Your app never holds an OpenAI key. Kong does" (source: https://dev.to/thegatewayguy/proxy-openai-through-kong-ai-gateway-on-kubernetes-1p83). Supported providers include OpenAI, Azure OpenAI, Bedrock, Anthropic, Gemini, Vertex AI, Mistral, Cohere, xAI, DeepSeek, Ollama, Databricks, vLLM (source: https://developer.konghq.com/plugins/ai-proxy). Requests are transformed to OpenAI format by default (`config.llm_format` opts out). Multi-target routing with balancing lives in the enterprise AI Proxy Advanced plugin.

**New: AI Model Provider entity.** A provider is a named object holding type + auth, and models route to it by name. Verbatim kongctl YAML (source: https://developer.konghq.com/ai-gateway/entities/ai-model-provider):

```yaml
ai_gateway_model_providers:
- ref: my-openai-account
  ai_gateway: !lookup {id: !env AI_GATEWAY_ID}
  display_name: OpenAI Production
  name: my-openai-account
  type: openai
  config:
    auth:
      type: basic
      headers:
      - name: Authorization
        value: !secret {source: !env OPENAI_AUTH_HEADER}
```

Anthropic variant uses `x-api-key` header with `!secret` interpolation (source: https://developer.konghq.com/ai-gateway/ai-providers/anthropic). Notable: authentication can be "Provided by AI gateway or Provided by client or agent", i.e. the same model route supports platform-held keys or caller-held keys. Policies attach globally, per model, or via AI Consumer Groups with ACLs.

### B4. Cloudflare AI Gateway

Provider-agnostic endpoint in front of your providers; three auth modes (source: https://developers.cloudflare.com/ai-gateway/get-started/connecting-applications/):

1. Unified Billing (no provider keys at all),
2. BYOK / stored keys: "Store your own provider API Keys with Cloudflare, and AI Gateway will include them at runtime",
3. Per-request headers (`Authorization: Bearer <OPENAI_API_KEY>`).

Endpoint format: `https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/{provider}`.

Stored-key details (source: https://developers.cloudflare.com/ai-gateway/configuration/bring-your-own-keys/):

- Keys live in Cloudflare Secrets Store; via API the secret name must follow `{gateway_id}_{provider_slug}_{alias}` (e.g. `my-gateway_anthropic_default`).
- Multiple keys per provider via aliases (dev vs prod, gradual rotation); the `default` alias is used unless overridden by header:

```bash
curl https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/openai/chat/completions \
  -H 'cf-aig-authorization: Bearer {CF_AIG_TOKEN}' \
  -H 'cf-aig-byok-alias: production' \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4", "messages": [...]}'
```

- Stored keys are only injected when the request lacks its own provider auth header (explicit key wins).
- Rotation: "generate a new provider key, edit the existing entry in the dashboard, save, apps pick it up immediately with no code changes or downtime." Revocation: "Deleting an API key will immediately stop all requests that depend on it."
- Gateway features: caching, rate limiting, analytics (requests, tokens, cost), logging, model aliases and fallbacks with dynamic routes for conditional flows (source: https://developers.cloudflare.com/ai-gateway/). The legacy "universal endpoint" JSON retry/fallback page moved; exact current format UNVERIFIED.

---

## Part C: the central pattern, compared

Every system converges on: named providers/connections of shape `{name, provider type, base_url, api_key, models[]}` plus a routing layer that maps a caller-facing name or job to a connection.

| System | Provider object | Credential handling | Model list | Routing to a job |
| --- | --- | --- | --- | --- |
| LiteLLM | `model_list` entry (per deployment) + `credential_list` | `os.environ/` refs, secret managers, salt-key-encrypted DB | implicit via model names + wildcard `*` | `model_name` alias, `model_group_alias`, teams/keys with `models` allowlist |
| Portkey | Model Catalog provider (slug `@openai-prod`) | stored in vault, or secret references to AWS/Azure/HashiCorp | provider's catalog + overrides | config object: fallback, loadbalance, conditional on metadata; `model="@slug/model"` |
| Kong | AI Model Provider entity (`ref`, `type`, auth headers) | `!secret` from env/vault, or client-provided | AI Models target a provider | routes/consumer groups/ACLs; `route_type` per capability |
| Cloudflare | provider segment in gateway URL + stored key aliases | Secrets Store, alias per key | provider-native names | gateway per app + `cf-aig-byok-alias`, dynamic routes |
| Databricks | model provider service (UC securable) | inline, UC secret reference, or IAM service credential | `targets` allowlist | `EXECUTE` grants; endpoints; AI Gateway policies |
| Azure Foundry | connection (per project) | managed Key Vault or BYO Key Vault | provider-dependent | project-scoped connection name lookup |
| Snowflake | secret + external access integration | secrets with grants; API integration `API_KEY` | network-rule scoped | UDF/procedure binding by secret name |
| AWS AgentCore | credential provider (secret ARN + jsonKey) | your Secrets Manager, CMK, your rotation | n/a (per-tool) | runtime `GetSecretValue` by reference |

Two-layer key model is universal: upstream provider credentials (few, high-value, vaulted) and downstream virtual/internal keys (many, cheap, scoped, budgeted, revocable). Routing never exposes the upstream key; callers address aliases like "gpt-class" or `@openai-prod/gpt-4o`.

---

## Part D: governance patterns

1. **Scoping per team/workspace.** LiteLLM virtual keys carry `models` allowlists, `team_id`/`user_id`, `tpm/rpm` limits, `max_parallel_requests`; keys inherit from owner unless overridden. Portkey Model Catalog gives "fine-grained budgets, rate limits, and model allow-lists" and org-level credential sharing across workspaces. Kong scopes via consumers and AI Consumer Groups + ACLs. Databricks scopes via UC `EXECUTE` grants on the provider service. Cloudflare scopes via separate gateways per app.
2. **Audit logs of key usage.** Bedrock: "All API calls are logged in AWS CloudTrail. API keys are passed as authorization headers and are not logged." LiteLLM writes spend logs naming the key used; TrueFoundry's governance writeup frames the enterprise ask exactly: per-team attribution, records of which requests carried customer data, ability to "revoke access without rotating provider keys", compliance-grade audit logs (source: https://www.truefoundry.com/blog/ai-governance-audit-enterprise-llm-gateway).
3. **Spend/budget caps per key.** LiteLLM: `max_budget` + `budget_duration` resettable windows, team/user/key spend tables, budget alerting (`alerting: ["slack"]`), temporary budget increases. Databricks: `system.ai.gateway.external_model_spend` with price multipliers for negotiated rates. Cloudflare analytics: requests, tokens, cost.
4. **Key health checks and circuit breaking.** LiteLLM: `allowed_fails` + cooldown time per deployment, cooldowns on 429/quota errors, fallbacks and `context_window_fallbacks`, routing strategies including latency-based; a pending feature request describes the desired shape: "On 429 / quota-exhaustion, cooldown the failing key and pick the next one ... Admin UI shows per-key health and cooldown status" (https://github.com/BerriAI/litellm/issues/32118). Kong AI Proxy Advanced does balancer-style multi-target routing.
5. **Zero-downtime rotation.** Three concrete mechanisms found:
   - Dual-key overlap: validation accepts current + previous key with an expiry; "AWS allows a maximum of two access keys per IAM user, and Azure issues the same pair per resource, so the platforms themselves assume exactly this choreography" (source: https://dev.to/ayinedjimi-consultants/api-key-rotation-without-downtime-patterns-and-implementation-j77, https://cloudai.pt/api-key-rotation-for-ai-apis-the-zero-downtime-runbook).
   - Grace periods: LiteLLM key rotation keeps both keys valid for `grace_period` (e.g. "48h"); managed rotators (Infisical, Phase) mint new LiteLLM keys, switch the active secret, then revoke the old one (https://infisical.com/docs/documentation/platform/secret-rotation/litellm-api-key, https://docs.phase.dev/integrations/platforms/litellm).
   - Reference indirection: Cloudflare edit-in-place ("edit the existing entry ... apps pick it up immediately"), Portkey secret references with 5-minute cache TTL, Databricks UC secret read "at query time ... rotation requires no service change", AgentCore reading Secrets Manager at runtime. Nobody who does rotation well rotates by editing the key value where it is used; they rotate behind a reference.

---

## Part E: what enterprises say they require from BYOK

From vendor compliance pages, standards bodies, and OpenAI's own enterprise offering:

- **Encryption at rest, decryption only in memory at use time.** Govyn: keys "encrypted with AES-256-GCM before touching any storage layer ... decrypted only in-memory, only at the moment a request is forwarded ... No key material is ever logged, cached in plaintext, or exposed through API responses" (https://govynai.com/features/byok). Gateco: "KMS-wrapped DEK, AES-256 at rest, never written to logs" (https://www.gateco.ai/security). OpenLIT: central vault, AES-256-GCM, "decoupling key rotation from redeploys" (https://docs.openlit.io/latest/openlit/developer-resources/vault/overview).
- **Keys never in logs.** Bedrock states it explicitly (above); IBYOK: "Error messages, debug output, and request logs often include sensitive headers or parameters. Production logs become treasure troves" (https://www.ibyok.com/blog/securing-api-keys-best-practices).
- **Least privilege and blast-radius scoping.** Per-app or per-environment keys instead of shared keys: "highly scoped keys mapped to individual environments", "unique keys per application ensure granular audit trails" (https://www.lockllm.com/blog/BYOK-vs-managed-keys, https://www.ibyok.com/blog/soc2-compliance-llm-key-management).
- **Ability to revoke instantly.** Cloudflare: deleting a stored key "will immediately stop all requests that depend on it". Databricks: revoking READ SECRET "stops queries for everyone". TrueFoundry: revoke one team's virtual key "without rotating provider keys" for everyone.
- **Per-key observability.** Spend per key, usage per key, key age, rotation logs; SOC 2 auditors "examine key management system configuration, access control settings ... audit trails for credential access" (https://www.ibyok.com/blog/soc2-compliance-llm-key-management; IBM: https://www.ibm.com/think/topics/byok).
- **Customer-managed encryption keys (CMK/HYOK) for the most sensitive data.** OpenAI Enterprise Key Management: customer content encrypted under a DEK wrapped by a KEK in the customer's AWS KMS / GCP / Azure Key Vault / OCI Vault, with limited IAM policies and AssumeRole/workload-identity trust (https://help.openai.com/en/articles/20000943-openai-enterprise-key-management-ekm-overview). CSA notes CSPs keep audit logs of cryptographic ops even under CMK, while pure HYOK limits provider-side visibility (https://cloudsecurityalliance.org/artifacts/multi-cloud-kms).
- Framework mapping: HIPAA (technical safeguards, access records), GDPR (sovereignty), SOC 2 Type II (key lifecycle evidence), PCI DSS (https://www.ibm.com/think/topics/byok, https://govynai.com/features/byok).

---

## ARCHITECTURE PATTERNS FOR A LOCAL DESK APP

What to steal for agent-desk (single user, local-first, multiple saved keys, keys assigned to jobs):

1. **Model the provider as a named connection object, exactly `{name, type, base_url, auth, models[]}`, not a bag of env vars.** Every surveyed system converges on this (LiteLLM `model_list` + `credential_list`, Kong AI Model Provider, Databricks provider service, Portkey Model Catalog). In agent-desk: a `providers.json`/DB table where each entry has a stable `id`, `name`, `type` (openai, anthropic-compat, openrouter, groq, together, gateway, vllm/ollama), `base_url`, credential reference, and a `models[]` allowlist fetched or curated per provider.
2. **Separate the credential from the connection by one level of indirection.** LiteLLM `credential_list`, Databricks UC secrets, AgentCore secret ARN + jsonKey, Portkey secret references all exist so rotation never touches the connection config. Locally this maps to the OS keychain (Windows Credential Manager / Keychain / libsecret) holding the secret, and the provider config storing only a keychain reference. Rotation then means writing one keychain entry, not editing N provider configs.
3. **Support an auth "kind" per provider, not just a bearer key.** Kong and Databricks both allow custom header names (e.g. Anthropic `x-api-key` vs OpenAI `Authorization`), Azure needs `api-version`, Vertex needs project/region/service-account, gateways may need extra headers. Schema: `auth: {type: bearer|header|service_account|oauth, header_name?, api_version?, project?, region?}`.
4. **Two key layers are unnecessary locally, but a job-to-key assignment table is essential.** Virtual keys for internal users solve a multi-tenant problem agent-desk does not have. Keep instead the routing half: a `jobs` or `features` map (`chat`, `summarize`, `embed`, `title-generation`) that names a provider + model alias, exactly like LiteLLM's `model_group_alias` and Portkey's configs map caller-facing names to targets. Users should never pick "OpenAI gpt-4o-mini" per feature; they pick which connection serves the "fast-cheap" class.
5. **Alias model classes, not vendor models.** LiteLLM: `model_name` is "the name to pass TO litellm from the external client" while `litellm_params.model` is what goes upstream; teams ask for a class and ops remap. agent-desk jobs should reference a class ("gpt-class", "haiku-class", "local") resolved through the routing table, so swapping vendors is a one-line config change.
6. **Per-key and per-job spend tracking with budget caps.** LiteLLM's `max_budget` + `budget_duration` and Databricks' `external_model_spend` with a price multiplier are the pattern. Locally: log tokens and estimated cost per request keyed by (job, provider, key), keep a rolling window in SQLite, warn at thresholds. A price multiplier field matters if the user has negotiated or discounted rates.
7. **Health checking with cooldown/circuit breaking on provider keys.** Copy LiteLLM: `allowed_fails` within a cooldown window, cool the key down on 401 (rotate prompt), 429 (back off), 5xx (fail over); surface per-key health in the UI (status: healthy / cooling / invalid). This is cheap locally and prevents a dead corporate gateway key from hanging every job.
8. **Failover chains per job.** Portkey's nested fallback config (`on_status_codes: [429, 500]`) and LiteLLM's `fallbacks` map: job -> ordered [primary provider/model, secondary, local Ollama fallback]. For a local app the natural terminal fallback is the local model.
9. **Rotation UX: dual-entry with overlap.** Cloudflare's edit-in-place plus alias switching, and LiteLLM's grace period, both translate to: a provider connection can hold current and previous key (or two keychain slots), a "test then switch" flow that verifies the new key with a 1-token request before cutting over, and instant revoke of the old one. Never a modal that deletes the old key first.
10. **Log everything about the call, never the key.** Bedrock's contract is the model: log timestamp, job, provider, model, status, tokens, cost, latency; scrub authorization headers from any debug/error output. Add an audit view: "key X used by job Y at time T", satisfying the SOC 2 style expectations at personal scale.
11. **Kill switches and disable flags.** Snowflake integrations have `ENABLED = TRUE|FALSE`; Cloudflare deletion halts dependent requests. Locally: a per-connection `enabled` toggle and a global "disable all remote providers" switch (also good for offline mode), plus a pre-flight connectivity/credential test (`GET /models` or 1-token completion) shown as the key's health badge.
12. **Egress allowlisting is a cloud concern; explicit base_url is the local equivalent.** Snowflake network rules and Databricks PrivateLink do not apply, but the lesson does: never construct provider URLs from user text at call time. Pin `base_url` in the connection, show it in the UI, and treat changes to it as an explicit user action.
13. **What to skip:** multi-tenant RBAC and team hierarchies (LiteLLM teams, Foundry roles, Kong consumer groups), KMS/HSM integration and envelope encryption beyond the OS keychain, unified billing, per-request policy engines (Cedar/OPA), and centralized config ownership battles (LiteLLM's config.yaml vs DB key-ownership rules). A single user gets 90% of the value from: keychain + connections + job routing + spend log + health/fallback.

---

## Source index (primary)

- Databricks external models: https://docs.databricks.com/en/generative-ai/external-models.html
- Databricks model provider services: https://docs.databricks.com/aws/en/ai-gateway/create-model-provider-services
- Snowflake API integrations: https://docs.snowflake.com/en/sql-reference/sql/create-api-integration
- Snowflake external access pattern: https://medium.com/snowflake/integrating-third-party-apis-into-snowflake-cortex-agents-2802fe50ae9d, https://medium.com/snowflake/snowflake-cortex-rag-from-external-api-%EF%B8%8F-abc493bc155f
- Azure Foundry connections: https://learn.microsoft.com/en-us/azure/foundry/how-to/connections-add
- Bedrock API keys: https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html
- Bedrock OpenAI-compat: https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html
- AgentCore Identity BYOS: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-providers.html, https://aws.amazon.com/blogs/machine-learning/reference-your-own-aws-secrets-manager-secrets-in-amazon-bedrock-agentcore-identity
- Vertex AI: https://docs.portkey.ai/docs/integrations/llms/vertex-ai, https://www.promptfoo.dev/docs/providers/vertex, https://docs.solo.io/kagent/latest/setup/model-providers/google-vertexai
- LiteLLM config: https://docs.litellm.ai/docs/proxy/configs
- LiteLLM virtual keys: https://docs.litellm.ai/docs/proxy/virtual_keys
- LiteLLM quickstart/salt key: https://docs.litellm.ai/docs/proxy/docker_quick_start, https://docs.litellm.ai/docs/proxy/master_key_rotations
- Portkey config object: https://docs.portkey.ai/docs/api-reference/inference-api/config-object
- Portkey configs: https://docs.portkey.ai/docs/product/ai-gateway/configs
- Portkey virtual keys / Model Catalog: https://portkey.ai/docs/product/ai-gateway/virtual-keys, https://docs.portkey.ai/docs/guides/getting-started/getting-started-with-ai-gateway
- Portkey secret references: https://portkey.ai/blog/secret-references-ai-api-key-management
- Kong ai-proxy: https://developer.konghq.com/plugins/ai-proxy, https://developer.konghq.com/plugins/ai-proxy/examples/openai-chat-route
- Kong AI Model Provider: https://developer.konghq.com/ai-gateway/entities/ai-model-provider, https://developer.konghq.com/ai-gateway/ai-providers/anthropic
- Cloudflare AI Gateway BYOK: https://developers.cloudflare.com/ai-gateway/configuration/bring-your-own-keys/, https://developers.cloudflare.com/ai-gateway/get-started/connecting-applications/
- Rotation: https://dev.to/ayinedjimi-consultants/api-key-rotation-without-downtime-patterns-and-implementation-j77, https://cloudai.pt/api-key-rotation-for-ai-apis-the-zero-downtime-runbook, https://infisical.com/docs/documentation/platform/secret-rotation/litellm-api-key
- Compliance: https://help.openai.com/en/articles/20000943-openai-enterprise-key-management-ekm-overview, https://www.ibm.com/think/topics/byok, https://govynai.com/features/byok, https://www.ibyok.com/blog/soc2-compliance-llm-key-management, https://cloudsecurityalliance.org/artifacts/multi-cloud-kms, https://www.truefoundry.com/blog/ai-governance-audit-enterprise-llm-gateway
