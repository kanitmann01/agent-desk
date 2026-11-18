# Outlook Brief

**Question:** What arrived, what matters, and how do I start a reply?

## What it reads

The local Outlook mail folder, exported as header-only `.eml` files by
`tools/export-outlook.ps1` (or any other `.eml` export). It builds three
views from the same read:

- the active threads in the last 24 hours, newest first
- the one message most worth opening in the last three days, with the
  reasons it won
- three reply starters built from that message's subject line only

Works with no connector, no OAuth and no network call. Reads message
headers only: it never opens a body, never reads attachments, and never
sends mail. The plugin declares no filesystem read of its own: the host
mail setting names the folder, and the plugin reads the host's header
brief.

## Elements

| element | binding | shows |
|---|---|---|
| metric "Active messages (24h)" | `messages` | messages received in the last 24 hours |
| text "Most important email" | `topEmailSubject` | the subject of the one message that matters |
| text "From" | `topEmailLine` | sender and age of that message |
| text "Why this one" | `topEmailWhy` | the rule reasons, in plain words |
| list "Active threads" | `threadRows` | thread, last sender, message count and age |
| list "Reply starters" | `replyOptions` | Direct, Clarify and Brief openers |

## Binding note

The host's `outlook-brief` source emits `messages`, `threads`,
`threadRows`, `topEmailSubject`, `topEmailLine`, `topEmailWhy`,
`replyOptions` and `windowNote`. No body binding exists, so no element
can request one.

## Skills

`skills/mail-overview` turns the same header brief into one plain-language
overview line: what arrived, what matters, and the suggested first reply.
