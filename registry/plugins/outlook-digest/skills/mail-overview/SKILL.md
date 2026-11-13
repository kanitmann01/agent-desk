---
name: mail-overview
description: Summarize the last 24 hours of mail for the digest card. Reads the header-only digest counts (messages, threads, top senders; message bodies are never read) and writes one plain-language overview line.
---

# Mail overview

Reads the mail digest's header counts and writes a short overview.

Use it when the user asks what happened in the mail folder. Name the
message and thread counts first, then at most the top two senders. Work
from counts only: the digest never carries message bodies, and the
overview must not either.
