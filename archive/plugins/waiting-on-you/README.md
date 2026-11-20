# Waiting on you

**Question:** which threads did I leave hanging?

## What it reads

The mail metadata bridge's thread state: threads whose last message is
inbound and older than the waiting threshold, with sender and age. Message
metadata only. It never opens a message body, never reads attachments, and
never sends mail.

Reads no files of its own, makes no network call, and runs no shell.

## Elements

| element | binding | shows |
|---|---|---|
| list "Threads waiting on you" | `waitingRows` | thread, sender and age |
| metric "Open threads" | `threads` | count of open threads |
| delta "Messages" | `messages` | message change over 24h |
