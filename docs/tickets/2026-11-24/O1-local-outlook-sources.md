# O1: Which local Outlook data sources actually work here?

Type: research. Claim: unclaimed. Blocked by: none.

## Question

On a corporate Windows laptop with no admin rights and no tenant consent, which local mechanisms can read Outlook mail metadata, and calendar where possible, and write it into a local file the app can read?

The answer must name the exact source (process, file format, registry key, API or local cache), the Outlook client it works with (classic, new, or both), the evidence (official documentation plus a local fact from this machine), and the failure modes (client update, policy block, profile missing, cache encrypted, index disabled).

Candidates worth ruling in or out, not a complete list:

- classic Outlook COM or MAPI against a configured profile;
- new Outlook local cache under `%LOCALAPPDATA%\Microsoft\Olk`;
- Windows Search index queried through OLE DB or the Search API;
- Outlook rules, Quick Steps, VBA or script rules, including macro policy;
- browser automation of Outlook on the web with an existing session;
- third-party local sync or archive tools that need no admin;
- OS-level mail APIs, notification stores or protocol handlers;
- any other local source the research finds.

## Answer

Pending. Resolve from the swarm research and record the exact mechanism, evidence and limits here, then close this ticket and add a line to the map's Decisions so far.
