# O3: What is the feeder's privacy, consent and failure contract?

Type: grilling. Claim: unclaimed. Blocked by: O1, O2.

## Question

Given the chosen local source and scheduler, what exactly does the feeder read, what does it write, what does the app show, and what does it refuse to do?

Settle:

- the fields the feeder may read (headers only, or a named metadata subset) and the fields it must never read;
- whether the feeder writes `.eml` files, a local SQLite database, or both, and why;
- where the files live, how long they are kept, and how the user deletes them;
- the consent moment: what the user sees before the feeder is installed, and what the app records;
- the honest states: Outlook not installed, no profile, new Outlook unsupported, cache locked, source stale, task not running, app closed, folder unreadable;
- the exact user-facing copy for each state, following the repo's rule that an attention state never shows an invented zero;
- the uninstall path: remove the task, stop the feeder, keep or delete the data, and what the app says.

## Answer

The contract:

- **Reads:** only the notification record for an Outlook alert. The sender or title line and the subject or subtitle line. The preview line, body, attachments and every other payload key are dropped before anything is written. No mailbox, profile, OST, Olk or Outlook-for-Mac store is opened.
- **Writes:** one header-only `.eml` per alert in the configured `mail_folder`. CRLF, UTF-8 without BOM, a synthesized Message-ID from the source app and notification id, a date from the OS arrival time, and no bytes after the blank line. Deterministic filenames overwrite on a rerun.
- **Keeps:** a status dict with the collector, last run, alert count, coverage window and last error. It is read-only state, not a setting, and it never stores message content.
- **Consent:** the `mail_feeder` toggle is off by default. The Settings copy says "alerts only, not a mailbox" before the user turns it on. On macOS the card explains Full Disk Access and links the manual folder path instead of failing silently.
- **Honest states:** off; no folder; no OS notification store; no Outlook handler or records; Full Disk Access missing on macOS; store schema changed; no alerts in the window; coverage gap after the store pruned old rows. An attention state never shows a number.
- **Uninstall:** turning the toggle off stops the reader and leaves the generated files in the folder. The app does not delete user mail files automatically; the user can clear the folder. No OS task, service or autostart entry is created at any point.
- **Never:** no network, no model, no cloud copy, no send, no body, no attachment, no OS scheduler, no admin.

The exact user-facing copy follows the repo's existing mail and calendar attention states. The card names the collector and its coverage, not a Windows or macOS promise.

## Resolution (2026-11-24)

Resolved and implemented. The writer emits header-only `.eml` files with deterministic names and atomic replaces, the status dict carries collector, platform, last run, result, error, written count and coverage window, `mail_feeder` is off by default, and the manual Save as sentence is the fallback. The exact strings are recorded in the research note and the settings captures. One gap between this contract and the current surface is recorded rather than fixed: the runner replaces reader-specific unavailable causes with the generic manual sentence, so a macOS Full Disk Access cause does not reach the card today.
