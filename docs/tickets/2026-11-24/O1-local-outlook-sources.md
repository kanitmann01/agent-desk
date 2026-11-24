# O1: Which local Outlook data sources actually work here?

Type: research. Claim: unclaimed. Blocked by: none.

## Question

On a corporate laptop, Windows or macOS, with no admin rights and no tenant consent, which local mechanisms can read Outlook mail metadata, and calendar where possible, and write it into a local file the app can read?

The answer must name the exact source (process, file format, registry key, API, cache or OS index), the Outlook client it works with (classic, new, or both), the platform, the evidence (official documentation plus a local fact where one exists), and the failure modes (client update, policy block, profile missing, cache encrypted, index disabled).

Candidates worth ruling in or out, not a complete list:

- classic Outlook COM or MAPI against a configured profile on Windows;
- new Outlook local cache on Windows under `%LOCALAPPDATA%\Packages\Microsoft.OutlookForWindows_8wekyb3d8bbwe`;
- Windows Search index queried through OLE DB or the Search API;
- macOS Spotlight metadata for Outlook for Mac through `mdfind` and `mdls`;
- the Outlook for Mac local profile store, if it is documented and stable;
- Outlook rules, Quick Steps, VBA or script rules, including macro policy;
- browser automation of Outlook on the web with an existing session;
- third-party local sync or archive tools that need no admin;
- OS-level mail APIs, notification stores or protocol handlers;
- any other local source the research finds.

## Answer

Chosen: the operating system notification store as the one automatic source, and the manual `.eml` folder as the history source.

- Windows: `%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db` plus `-wal` and `-shm`. The live probe found 33 toast rows, a 20-toast cap per app, the new Outlook handler `Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookforWindows`, and classic Outlook installed with no profile. Both Outlook clients raise new-mail alerts through this store.
- macOS: `~/Library/Group Containers/group.com.apple.usernoted/db2/db` plus WAL sidecars. `app.identifier` names the source app and `record.data` is a binary property list with title, subtitle and body. Reading it needs Full Disk Access, a per-app user consent, not an admin.
- History: manual `.eml` export on both platforms. The app already reads that folder and keeps the header-only contract.

Why the history collectors are not v1:

- New Outlook for Mac has no AppleScript support; Microsoft cancelled the roadmap item in August 2026. New Outlook for Mac also uses server-side search and is not indexed by Spotlight. There is no supported local history API for it.
- Legacy Outlook for Mac still has Spotlight and AppleScript, but support ends in October 2026 and it stops working against Exchange Online mailboxes then.
- The Windows Search index may cover a classic Outlook mailbox only when the mapi16 handler and the index are healthy, and it does not expose Message-ID.
- Classic COM is protected by the Object Model Guard; prompt-free operation depends on antivirus health and Trust Center policy, which a non-admin cannot change.

These remain future options for a machine where a read-only probe passes. They are not promises of v1.

Evidence: the WPN probe facts and synthetic-store self-checks on this machine; the macOS findings from Microsoft support and current macOS notification-database research. The macOS reader is verified against a synthetic store and a written manual Mac procedure, not a real Mac used in this session.
