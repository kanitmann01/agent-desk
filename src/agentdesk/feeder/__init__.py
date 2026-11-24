"""The host-side Outlook metadata feeder.

A platform-agnostic core: collectors hand back the existing
agentdesk.mail.core.Message records (headers only, no body field), one
writer turns them into header-only .eml files that parse_eml reads, and
the runner owns the pass, the lock and the honest status. The platform
branch lives in one module; no HTTP client and no model client exists
anywhere in this package.
"""
