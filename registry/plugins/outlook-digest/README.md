# Outlook Digest

**Question:** How much mail, and from whom?

## What it reads

The mail metadata bridge's last-24-hours header digest: the message
count, the active thread count, the busiest senders, and the header
window note. Message metadata only: counts, senders, ages and thread
state. It never opens a message body, never reads attachments, and
never sends mail.

Reads no files of its own, makes no network call, and runs no shell.

## Elements

| element | binding | shows |
|---|---|---|
| metric "Messages 24h" | `messages` | messages received in the last 24 hours |
| list "Top senders" | `topSenders` | the three busiest senders with their counts |
| text "Scope" | `windowNote` | the window and the metadata-only promise |

## Binding note

The host's `mail-digest` source emits `messages`, `threads`, `unread`,
`topSenders` and `windowNote`. `topSenders` is one summary string, not
rows, and the source emits no row binding at all. The "Top senders"
list therefore points at the closest frozen name and renders blank
instead of inventing a rows binding the host would never fill.

## Skills

Kept from 0.1.0: `skills/mail-overview` writes one plain-language
overview line from the same header counts.
