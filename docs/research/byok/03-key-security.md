# BYOK key security: storage, display, leak prevention, validation, rotation

Research date: 2026-11-21. Scope: security engineering patterns for storing and using multiple LLM API keys in agent-desk, a local-first desktop app (Python backend + SQLite + React SPA on localhost, single user, Windows/macOS/Linux). All claims below were checked against fetched pages; anything not directly verified is marked UNVERIFIED.

## 1. Local secret storage options for a Python desktop app

### 1.1 The three OS-native stores

| OS | Store | What protects the secret | Scope of protection |
|---|---|---|---|
| Windows | Credential Locker, backed by DPAPI (`CryptProtectData` via `win32crypt`/pywin32) | Key material derived from the user's login credentials; "only a user with the same logon credential as the user who encrypted the data can typically decrypt the data" | Other users on the machine, offline disk theft. NOT other apps running in the same user session |
| macOS | Keychain (login keychain by default) | Encryption at rest plus per-item ACLs; other apps reading an item trigger a user prompt unless the creating app signed the ACL | Other users, other apps (strongest of the three), subject to the "same app/process" caveats below |
| Linux | Secret Service (`org.freedesktop.secrets` D-Bus API; gnome-keyring or KWallet daemons; `libsecret` is the client lib) | Collections stored under `~/.local/share/keyrings/`, encrypted with the collection master password (usually the login password, auto-unlocked by `pam_gnome_keyring.so`); GNOME uses AES-256-CBC + HMAC-SHA256 | Other users, offline theft; any process in the unlocked user session can query the service |

Sources: gist "Built-in, machine-bound secret storage" (https://gist.github.com/YoraiLevi/c47b64c30e587cd642df4b8122964d58), LWN libsecret overview (https://lwn.net/Articles/490518), Electron safeStorage docs (https://electronjs.org/docs/latest/api/safe-storage), StackOverflow "How is python-keyring implemented on Windows?" (https://stackoverflow.com/questions/14756352/how-is-python-keyring-implemented-on-windows).

Important honest threat model, common to all three: once the user session is unlocked, any code running as that user can typically read the user's secrets, on Windows and on a default Linux Secret Service setup, and on macOS for items whose ACL allows the creating process tree. macOS is the only one of the three that routinely interposes a per-app consent prompt. Source: keyring security considerations (https://keyring.readthedocs.io/en/latest/), Talk Python episode 418 (https://talkpython.fm/episodes/show/418/how-to-keep-a-secret-in-python-apps).

### 1.2 The Python `keyring` library

`keyring` (https://pypi.org/project/keyring/) is the standard Python facade over all three stores. Recommended backends: macOS Keychain, Freedesktop Secret Service (requires `secretstorage`), KDE KWallet (requires `dbus-python`), Windows Credential Locker. API is three calls: `set_password(service, username, secret)`, `get_password`, `delete_password`. There is no "prompt the user" guarantee: on macOS, "any Python script or application can access secrets created by keyring from that same Python executable without the operating system prompting the user for a password" (keyring security considerations, https://keyring.readthedocs.io/en/latest/). To get a per-read prompt on macOS you must edit the item's Access Control list in Keychain Access.

Failure behavior matters for a desktop app: when no recommended backend can initialize (headless Linux without a keyring daemon, CI, tox with filtered env), keyring raises "RuntimeError: No recommended backend was available". It can also be pinned to a null backend via `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` or `keyring --disable`. Always check `keyring.get_keyring()` before deciding whether a store actually exists. Headless Linux is workable without X11: install gnome-keyring, then `dbus-run-session -- sh` + `gnome-keyring-daemon --unlock` (reads the unlock password from stdin). Source: keyring docs "Using Keyring on headless systems" (https://keyring.readthedocs.io/en/latest/).

Who uses keyring (verified):

- twine: ships keyring support for PyPI uploads; `keyring set https://upload.pypi.org/legacy/ __token__`; explicitly documents the headless-Linux caveat and `keyring --disable` (https://twine.readthedocs.io).
- pip: uses keyring for index credentials when keyring is installed ("If you install keyring, then pip will use it", Python packaging discussion, https://discuss.python.org/t/using-pip-with-keyring/4836). Microsoft's `artifacts-keyring` states "Both pip and twine will use keyring to find credentials" (https://pypi.org/project/artifacts-keyring).
- Poetry: prefers the system keyring ("If a system keyring is available and supported, the password is stored to and retrieved from the keyring", e.g. `poetry-repository-pypi`); if keyring fails it falls back to plaintext `auth.toml`, and `poetry config keyring.enabled false` forces plaintext (https://python-poetry.org/docs/repositories/).
- aws-cli: uses its own `~/.aws/credentials` file, not keyring by default; the keyring ecosystem around AWS is third-party (aws-vault uses Go keyring libs). UNVERIFIED for current aws-cli versions.
- Others noted in the keyring history: devpi client (KeyringError suppression), IBM QRadar SOAR ships a `res-keyring` utility on top of it (https://www.ibm.com/docs/en/sqsp/51.0.0?topic=guide-using-encrypted-keys-optional).

### 1.3 Electron safeStorage (the pattern most local AI desktop apps inherit)

Electron `safeStorage.encryptString/decryptString` wraps Chromium's OSCrypt: one random AES master key per app, stored in the OS keystore (Keychain entry "Safe Storage" on macOS, DPAPI-encrypted on Windows, kwallet/kwallet5/kwallet6/gnome-libsecret on Linux); strings are AES-encrypted with that key and you persist the ciphertext yourself. Per-platform semantics from the official docs (https://electronjs.org/docs/latest/api/safe-storage):

- macOS: protected from other users and other apps in the same userspace; app should be code-signed or Keychain re-prompts on every update.
- Windows: DPAPI, "protected from other users on the same machine, but not from other apps running in the same userspace."
- Linux: varies by secret store; if none is available, items are "encrypted" with a hardcoded plaintext password, detectable via `safeStorage.getSelectedStorageBackend() === 'basic_text'`, which must be treated as "not encrypted."

Deep-dive analysis of the Linux fallback: PBKDF2-HMAC-SHA1, salt hardcoded to "saltysalt", iteration count 1 (https://chenguangliang.com/en/posts/blog169_electron-credential-storage-security). VS Code's `SecretStorage` API is exactly this pattern: safeStorage-encrypted values persisted (in SQLite), "encrypted, not synced across machines" (https://code.visualstudio.com/api/extension-capabilities/common-capabilities). Obsidian's plugin SecretStorage follows the same design (https://forum.obsidian.md/t/cross-platform-secure-storage-for-secrets-and-tokens-that-can-be-syncd/100716).

### 1.4 Fallbacks when no OS keychain exists

Documented real-world fallbacks, from weakest to strongest:

1. Plaintext config file. What Aider (`.env`, `.aider.conf.yml`), Open WebUI (DB config rows), Jan (settings/config files), and Obsidian Smart Connections (`data.json`, https://github.com/brianpetro/obsidian-smart-connections/issues/1347) all do today. Claude Code on Linux/Windows: `~/.claude/.credentials.json` "with file mode 0600" on Linux and NTFS ACL protection on Windows (https://code.claude.com/docs/en/authentication).
2. OS-restricted file, i.e. `0600` on POSIX, user-profile ACLs on Windows. Same as above; the restriction only defends against other local users, and is the same protection class OpenAI itself recommends for env vars.
3. keyrings.alt / keyrings.cryptfile: explicitly labeled "least secure... not recommended for production" (IBM doc above, https://www.ibm.com/docs/en/sqsp/51.0.0?topic=guide-using-encrypted-keys-optional).
4. Machine-bound encryption of a local file: DPAPI-encrypt a master key (or each key) on Windows, or a `basic_text`-class scheme on Linux. This is what Electron apps effectively do; on Windows it is reasonable, on Linux without a secret service it adds little over 0600 unless you add a user passphrase.

The pragmatic consensus for local-first apps: use the OS keychain when present (via `keyring` in Python, `safeStorage`/SecretStorage in Electron), and when absent fall back to a 0600/ACL-restricted file with a visible warning in the UI, plus an env-var escape hatch. That is what Claude Code does (Keychain on macOS, 0600 JSON elsewhere, env vars override everything) and what the keyring ecosystem assumes.

### 1.5 What local AI tools actually do (summary table)

| Tool | Storage | Notes | Source |
|---|---|---|---|
| Aider | Env vars, `.env` (home, git root, cwd; loaded in order, later wins), `.aider.conf.yml`, `--api-key provider=key` which just sets `PROVIDER_API_KEY` | No keychain, no masking machinery; pure env/file | https://aider.chat/docs/config/api-keys.html, https://aider.chat/docs/config/dotenv.html |
| Open WebUI | Provider keys in DB config table as plaintext (community-documented); own REST API keys plaintext in DB; optional Fernet (AES-128) encryption for plugin Valve secrets via `WEBUI_SECRET_KEY`; optional `DATABASE_TYPE=sqlite+sqlcipher` | Multi-user server product, not single-user; encrypting at rest is acknowledged as limited because the process must decrypt at runtime | https://docs.openwebui.com/reference/env-configuration, https://github.com/open-webui/open-webui/discussions/8534, https://docs.openwebui.com/getting-started/advanced-topics/hardening, https://docs.openwebui.com/features/authentication-access/api-keys |
| LM Studio (server keys it issues) | Optional API tokens for its local server; per-token permissions; "Once created, make sure to copy the token as it will not be shown again" | It issues tokens; for consuming cloud keys LM Studio is not the relevant surface | https://lmstudio.ai/docs/developer/core/authentication |
| Jan | Cloud provider keys pasted into Settings > Model Providers, stored in app settings/config files; SECURITY.md acknowledged as config-file storage | Local server key optional, can be any string | https://docs.jan.ai/desktop/remote-models/openai, https://docs.jan.ai/desktop/api-server, https://tigerabrodi.blog/... (Vellum overview corroborating config-file credentials) |
| Claude Code | macOS: Keychain item "Claude Code-credentials"; Linux: `~/.claude/.credentials.json` 0600; Windows: `%USERPROFILE%\.claude\.credentials.json` under profile ACLs; falls back to the file when the Keychain is locked (SSH); env vars take priority over stored creds | The single best-matched precedent for a local agent app. Known weakness: the Keychain item is created via `/usr/bin/security`, so its ACL allows any process in the user session to read it without a prompt | https://code.claude.com/docs/en/authentication, https://www.silverfort.com/blog/skipping-the-lock-a-claude-code-cli-weakness-lets-any-macos-process-read-stored-credentials, https://netwrix.com/en/resources/blog/ai-coding-assistant-credential-storage-risks |
| VS Code extensions (API Vault etc.) | VS Code SecretStorage (safeStorage-backed) | The mainstream "encrypt via OS, persist ciphertext locally" pattern | https://code.visualstudio.com/api/extension-capabilities/common-capabilities |

## 2. Key display UX norms

Verified patterns from GitHub, OpenAI, LM Studio:

- Show the full secret exactly once, at creation time, with a copy button. GitHub: "make sure to copy your personal access token, now you won't be able to see it again" (https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens; the list shows a blurred token with a copy icon next to it). OpenAI Help Center: "For security, a full secret key is only shown when you create it. If you lose it or did not save it, create a new key" (https://help.openai.com/en/articles/4936850-where-do-i-find-my-openai-api-key). LM Studio: "Once created, make sure to copy the token as it will not be shown again" (https://lmstudio.ai/docs/developer/core/authentication).
- After save, identify keys by name plus a masked hint. OpenAI's list shows only the prefix and last four characters ("it only shows me the 'sk' and the last four characters", https://www.reddit.com/r/OpenAI/comments/11hk4z6/how_to_see_the_api_key; the usage dashboard exposes "The beginning of the API key (sk-proj-), the last four characters, and the API key ID (key_ + 16 chars)", https://community.openai.com/t/i-cant-see-api-usage-by-key-only-by-project/1129907). So the canonical mask is first-few + "..." + last-4, e.g. `sk-...abcd`.
- Never re-display on demand: neither GitHub nor OpenAI offers a "show key" button after creation; replacement (regenerate/rotate) is offered instead (Open WebUI's admin flow similarly offers Rotate or Delete, https://docs.openwebui.com/features/authentication-access/api-keys).
- Edit form UX: password-type input with a reveal toggle while typing (Jan and Open WebUI provider settings behave this way), then masked forever after save.
- Keys are named by the user so the list stays meaningful when values are hidden; OpenAI keys also carry a `key_...` ID usable in APIs.

Vercel follows the same create-once-copy-now convention; not independently fetched, UNVERIFIED.

One leak-shaped nuance found while researching: provider error messages themselves echo a masked key, e.g. OpenAI returns "Incorrect API key provided: sk-...prY8cM. You can find your API key at..." (masked first/last chars, https://community.openai.com/t/regex-s-to-validate-api-key-and-org-id-format/44619). So surfacing provider errors to the UI is acceptable as long as the raw key never appears; when in doubt, re-mask.

## 3. Never-leak guarantees

### 3.1 Redaction in logs

LiteLLM is the best-documented example (https://docs.litellm.ai/docs/proxy/logging, https://docs.litellm.ai/docs/proxy/config_settings):

- Automatic secret redaction in proxy log output is on by default; `LITELLM_DISABLE_REDACT_SECRETS=true` turns it off ("disables automatic redaction of secrets (API keys, tokens, credentials) from proxy log output. Secret redaction is enabled by default").
- `litellm.turn_off_message_logging: true` drops request/response bodies from logging callbacks while keeping spend metadata.
- `redact_user_api_key_info: true` redacts hashed-token/user/team identifiers from observability callbacks.
- Enterprise "hide-secrets" guardrail runs detect-secrets over prompts pre-call and logs only "Detected and redacted secrets in message: ['Secret Keyword']" (https://docs.litellm.ai/docs/proxy/guardrails/secret_detection).
- Prompts/responses are not stored in spend logs unless `store_prompts_in_spend_logs` is opted in (https://docs.litellm.ai/docs/proxy/ui_logs).
- Cautionary tale: issue #7603 "API Keys shown in debug mode", debug logs contained LiteLLM and provider API keys because kwargs were logged raw (https://github.com/BerriAI/litellm/issues/7603). Redaction must cover exception payloads and debug dumps, not just the happy path.

General log guidance for key-bearing systems: "Log the key ID or a non-reversible fingerprint... Do not log the secret value, authorization header, or sensitive request and response bodies" (https://api7.ai/blog/best-practices-for-api-key-management).

### 3.2 Never in URLs or query params

Consistent across every source: keys go in headers, never query strings, because URLs persist in server logs, proxies, browser history, and Referer headers. Apigee docs (https://docs.apigee.com/api-platform/tutorials/secure-calls-your-api-through-api-key-validation), Moesif (https://www.moesif.com/blog/technical/query-parameters), FullContact's "Never Put Secrets in URLs and Query Parameters" (https://www.fullcontact.com/blog/engineering/never-put-secrets-urls-query-parameters). Even though OpenAI key bodies are URL-safe, "always pass it via the Authorization: Bearer header, not a URL parameter" (https://vibekit.bot/openai-api-key-format). For agent-desk this also means: never embed keys in localhost URLs between the SPA and backend; use headers on the fetch, and ideally never send the secret to the SPA at all.

### 3.3 Error messages that echo keys

OpenAI's own error output is masked (prefix + last 4, see above), which is the right target: when surfacing provider errors, replace any occurrence of the stored key with its masked form before the message reaches UI or logs. A `logging.Filter` that knows the stored key values (fetched from the keychain at startup) plus generic patterns (`sk-[A-Za-z0-9_-]{16,}`, `Bearer\s+\S+`) covers both exact and accidental matches.

### 3.4 Crash reports and subprocess environments

- Crash/telemetry scrubbing: strip Authorization headers and known key patterns in a before-send hook; no single canonical Python source fetched for this, treat as standard Sentry-pattern practice, UNVERIFIED beyond general guidance.
- Subprocess leakage is real: Claude Code added `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` to strip credentials from the environment inherited by the bash tool, hooks, and MCP stdio servers (https://dev.to/rsdouglas/claude-code-plugin-credentials-what-the-new-keychain-storage-does-and-doesn-t-do-cnf). If agent-desk ever passes keys via env to child processes (it should pass them only in the HTTP client), scrub the env of spawned processes.

## 4. Key validation: cheapest reliable check

What the ecosystem actually does:

- `GET {base_url}/v1/models` is the standard cheap check: free, no tokens consumed, and it doubles as the model-availability list. OpenAI community: the List Models endpoint "doesn't cost anything and will not only validate the API key, but will also tell you the models the user has access to" (https://community.openai.com/t/what-are-the-valid-characters-for-the-apiname/288643). gpt-researcher discussion proposes exactly this as save-time validation (https://github.com/assafelovic/gpt-researcher/discussions/655). Browser key testers do the same (https://trevorfox.com/api-key-tester/openai).
- Local OpenAI-compatible servers implement `GET /v1/models` too (Jan: https://docs.jan.ai/desktop/api-preference), so the same check works for localhost providers, with the caveat that local servers often accept any/dummy key.
- Limitations of /v1/models: a 200 proves the key authenticates and the endpoint exists; it does not prove billing is active (quota errors surface as 429 on the first completion, see StackOverflow "How to check the validity of the OpenAI key from python?", https://stackoverflow.com/questions/76522693/how-to-check-the-validity-of-the-openai-key-from-python), nor that a specific model is permitted (org verification and model access can gate individual models, https://community.openai.com/t/my-api-key-test-null-because-i-cant-validate-org/1364417). Filtering the returned model list for the configured model id closes most of that gap at zero cost.
- Minimal completion (1 token, cheapest model) as a deeper, user-initiated "test connection": costs on the order of a fraction of a cent (a ~105-token round trip on a cheap model was estimated at ~$0.00001, https://www.youtube.com/watch?v=rn6alwafU5Q; price out current cheapest model at time of build). Reasonable as an explicit button, wasteful as an automatic on-save check.
- Format pre-checks (starts with "sk-", length) are useful only as instant client-side feedback; OpenAI has published no official regex (https://community.openai.com/t/regex-s-to-validate-api-key-and-org-id-format/44619).

Health/status patterns from LiteLLM: keys and callbacks carry a healthy/unhealthy status with details ("status: unhealthy, details: Logger exceptions triggered..."), and health endpoints return per-key results (https://docs.litellm.ai/docs/proxy/team_logging). Sensible classification for agent-desk: 401/403 = invalid key (mark unhealthy, surface to user), 429 = rate/quota (cooldown, not unhealthy), 5xx/timeout = transient (retry, keep status). Update `last_used_at` and `last_error` from real traffic, not just from explicit checks.

## 5. SQLite specifics

### 5.1 Is SQLCipher worth it here?

SQLCipher is AES-256-CBC+HMAC page-level encryption for SQLite with 5-15% overhead (https://github.com/sqlcipher/sqlcipher), designed for exactly "mobile apps and single-user embedded databases" (https://turso.tech/blog/sqlite-encryption-what-developers-actually-use). But for a single-user localhost app:

- The DB key has to come from somewhere on the same machine (keychain or config). If malware runs as the user, it gets both the key and the DB; encryption at rest only defends against the file being copied without the user session (stolen disk, cloud-synced folder, backup). Sources: the same reasoning Open WebUI community members give for why DB encryption of secrets is limited when the server must decrypt at runtime (https://github.com/open-webui/open-webui/discussions/8534), and the HN observation that full-disk encryption plus per-file protection covers much of this already (https://news.ycombinator.com/item?id=30972969).
- Modern OSes encrypt disks by default (BitLocker/FileVault/LUKS commonly enabled), which covers the stolen-disk case.
- If secrets never live in SQLite at all (section 5.2), there is very little left worth encrypting.

Verdict: if you adopt the split pattern below, SQLCipher is overkill for agent-desk. It becomes worth considering only if chat transcripts or other sensitive content pile up in the DB and the user's threat model includes synced/backed-up data folders (Open WebUI ships `DATABASE_TYPE=sqlite+sqlcipher` as exactly that kind of optional hardening, https://docs.openwebui.com/getting-started/advanced-topics/hardening).

### 5.2 The split pattern (DB reference + secret in OS keychain)

Store in SQLite: provider, base_url, model, key label, keyring service/username reference, masked hint (last 4), created_at, updated_at, last_used_at, health columns. Store the secret itself: OS keychain via `keyring.set_password("agent-desk", "key/<uuid>", secret)`. This is the VS Code SecretStorage architecture (ciphertext in local storage, master key in OS store), the Claude Code architecture (creds in Keychain on macOS), and what keyring-using Python tools (twine, poetry) effectively do with system stores. Advantages: DB backups/sync contain no secrets; DB schema stays trivially inspectable; deletion semantics are clear (delete keychain item + row).

### 5.3 Keychain unavailability and env-var precedence

Real cases where the keychain is unavailable: headless Linux, containers, CI, macOS over SSH (locked Keychain; Claude Code explicitly falls back to the 0600 file in that case, https://code.claude.com/docs/en/authentication, and users commonly extract the token and pass `CLAUDE_CODE_OAUTH_TOKEN`, https://dev.to/anicca_301094325e/how-to-recover-claude-code-oauth-token-in-30-seconds-1hd).

Precedence conventions observed (most explicit wins):

- Claude Code: `ANTHROPIC_AUTH_TOKEN` > `ANTHROPIC_API_KEY` > apiKeyHelper script > `CLAUDE_CODE_OAUTH_TOKEN` > stored OAuth creds (https://netwrix.com/en/resources/blog/ai-coding-assistant-credential-storage-risks); env beats Keychain.
- Jan CLI: flags/env (`--api-key`, `<PROVIDER>_API_KEY`, `JAN_API_KEY`) beat `~/.jan/config.toml`, which beats Desktop `settings.json` ("Four sources, each beating the ones above it", https://docs.jan.ai/agent/providers).
- Aider: CLI switch, env var, `.env`, YAML are documented as 4 equivalent ways, with `.env` files loaded in order and later files taking priority (https://aider.chat/docs/config.html, https://aider.chat/docs/config/dotenv.html).
- OpenAI's own SDK convention: `OPENAI_API_KEY` env var is the universal override (https://help.openai.com/en/articles/5112595-best-practices-for-api-key-safety).

So the convention agent-desk should follow: per-request explicit key > provider env var (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, ...) > stored keychain entry > none. One additional rule from a real bug: never write env-supplied credentials back into the keychain or delete stored creds while env mode is active (Claude Code issue #37512, where env mode triggered deletion of the Keychain entry, https://github.com/anthropics/claude-code/issues/37512).

## 6. Rotation and revocation UX

- Single-key replacement is the norm for personal/local tools; dual-key (blue/green) rotation is an enterprise pattern. Even for enterprises the guidance is sequential: "For routine rotation, test the replacement before revoking the previous key" (Johns Hopkins/OpenAI platform guide, https://support.cmts.jhu.edu/hc/en-us/articles/38383798293133); Google Cloud: "Periodically create new API keys, update your applications to use the new API keys, and delete the old keys" (https://docs.cloud.google.com/docs/authentication/api-keys-best-practices). GitHub PATs cannot even be programmatically rotated; you create a new one, swap, revoke (https://github.com/orgs/community/discussions/148626).
- Supporting multiple keys per provider gives you dual-key rotation for free: add the new key as a second entry, validate it, switch the model/provider default to it, delete the old one. No special rotation machinery needed.
- Revocation should be immediate and total: delete the keychain item and the DB row together; Open WebUI is the reference for semantics ("Creating a new key overwrites the old one, and deleting a key leaves the account with none... the change takes effect instantly"; creation and deletion are recorded as authentication events, https://docs.openwebui.com/features/authentication-access/api-keys).
- Per-key audit metadata that real dashboards surface: name, creation date, expiration (GitHub fine-grained tokens require an expiration within 366 days and there is a 50-token cap, https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens), "last used" (GitHub shows buckets like "Last used within the last week" / "within the last 2 years", https://github.com/orgs/community/discussions/24531, and auto-removes PATs unused for a year), per-key usage (OpenAI usage dashboard filters by API key, https://support.cmts.jhu.edu/hc/en-us/articles/38383798293133). For agent-desk the single-user equivalent is: created_at, updated_at, last_used_at, last_checked_at, last_error_code/message, plus enabled/disabled.
- Encourage provider-side hygiene the app cannot enforce: users should create app-specific keys (OpenAI project keys `sk-proj-...` are scoped to a project with its own rate limit and billing line, https://vibekit.bot/openai-api-key-format) so that a leaked agent-desk key is low-blast-radius and rotatable without touching other uses.

## RECOMMENDED DESIGN FOR AGENT-DESK

1. Store each secret only in the OS keychain via the Python `keyring` library: `set_password("agent-desk", "key/<uuid>", secret)`. Verify a real backend with `keyring.get_keyring()` at startup; on Windows/macOS and desktop Linux this always exists in practice.
2. SQLite stores metadata only (the split pattern): provider, base_url, model, label, keyring reference, masked hint (first 3 + last 4, e.g. `sk-...abcd`), created_at, updated_at, last_used_at, last_checked_at, status, last_error. The secret itself never enters SQLite, logs, or the React SPA.
3. Backend API never returns secret material. Endpoints accept a key on create/update, return only the masked hint afterwards. No "reveal" endpoint, no copy-full-key button after save (GitHub/OpenAI pattern: full value visible exactly once, in the create form, with a reveal toggle while typing).
4. Fallback ladder when no keychain (headless Linux, container, SSH): accept provider env vars resolved at call time. Precedence: explicit per-request key > env var (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) > keychain entry. Never persist env-provided keys, never let env mode delete stored ones. Optionally offer a 0600/ACL-restricted file store with a visible "keys stored unencrypted" warning, as Claude Code does; no keyrings.alt.
5. No SQLCipher. With secrets out of the DB, there is nothing worth page-encrypting for a single user on localhost; rely on OS user accounts plus default disk encryption. Revisit only if users put sensitive transcripts in a synced folder.
6. Validation on save: `GET {base_url}/v1/models` with the key (free, works across OpenAI-compatible providers and local servers). 200 + model present in list = status healthy; 401/403 = reject or save as unhealthy with the error shown (re-masked); 429 = healthy-but-limited; network error = status unknown, retry later. Offer a user-initiated "deep test" (1-token completion, max_tokens=1, cheapest model) but never run it automatically.
7. Health tracking: update last_used_at and last_error from live traffic. Mark unhealthy only on auth failures (401/403); treat 429 as cooldown and 5xx/timeout as transient. Show status plus last error inline in the key list.
8. Rotation: support multiple keys per provider; rotation is add-new, validate, switch default, delete-old (delete removes keychain item and DB row in one operation, no soft-delete grace period). No background auto-rotation.
9. Audit trail is the metadata columns above; that is the single-user equivalent of GitHub's "last used" and OpenAI's per-key usage. Record nothing else.
10. Redaction: a process-wide `logging.Filter` replacing the exact values of all stored keys plus generic patterns (`sk-...`, `Bearer ...`) in every log record and rendered exception text; keys only ever leave the process in Authorization headers; never in URLs, query params, or localhost SPA calls. If child processes are spawned, scrub key-bearing env vars first.
11. Local providers (LM Studio, Jan, Ollama): key optional; allow empty key and skip validation when the base_url is localhost/127.0.0.1; do not force dummy values into the keychain.
12. Explicitly overkill for this app: SQLCipher, hashing keys (the app must present the plaintext to providers, so hashes cannot work), dual-key rotation machinery, external secret managers (Vault/Doppler), and per-item macOS Keychain ACL hardening beyond what keyring gives by default. All add complexity without changing the actual threat model (another process running as the same logged-in user).

Primary sources index: keyring docs (https://keyring.readthedocs.io/en/latest/), Electron safeStorage (https://electronjs.org/docs/latest/api/safe-storage), VS Code SecretStorage (https://code.visualstudio.com/api/extension-capabilities/common-capabilities), Claude Code auth docs (https://code.claude.com/docs/en/authentication), Aider API keys (https://aider.chat/docs/config/api-keys.html), Open WebUI env reference + hardening + API keys (https://docs.openwebui.com/reference/env-configuration, https://docs.openwebui.com/getting-started/advanced-topics/hardening, https://docs.openwebui.com/features/authentication-access/api-keys), LM Studio authentication (https://lmstudio.ai/docs/developer/core/authentication), Jan docs (https://docs.jan.ai/desktop/remote-models/openai, https://docs.jan.ai/desktop/api-server, https://docs.jan.ai/agent/providers), LiteLLM logging + redaction (https://docs.litellm.ai/docs/proxy/logging, https://docs.litellm.ai/docs/proxy/config_settings), GitHub PAT management (https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens), OpenAI key safety + help (https://help.openai.com/en/articles/5112595-best-practices-for-api-key-safety, https://help.openai.com/en/articles/4936850-where-do-i-find-my-openai-api-key), secrets-in-URLs (https://www.fullcontact.com/blog/engineering/never-put-secrets-urls-query-parameters, https://docs.apigee.com/api-platform/tutorials/secure-calls-your-api-through-api-key-validation), SQLCipher (https://github.com/sqlcipher/sqlcipher, https://turso.tech/blog/sqlite-encryption-what-developers-actually-use).
