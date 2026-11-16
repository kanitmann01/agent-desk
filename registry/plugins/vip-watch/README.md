# Sender Watch

**Question:** who is filling my inbox this window?

## What it reads

The mail metadata bridge for the last 24 hours: sender, message count and
time of the latest message. Metadata only. It never opens a message body,
never reads attachments, and never sends mail.

Reads no files of its own, makes no network call, and runs no shell.

## Elements

| element | binding | shows |
|---|---|---|
| list "Top senders" | `sendersRows` | every sender with their message count |
| metric "Messages" | `messages` | messages in the window |
| text "Window" | `windowNote` | window and the metadata-only promise |

The id stays `vip-watch` for install stability. The host has no contact or
VIP list, so the card no longer claims to filter one; it lists real senders
instead of rendering a blank VIP table.
