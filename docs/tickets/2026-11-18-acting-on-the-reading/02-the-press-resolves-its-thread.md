# 02: A drafted reply knows which thread it belongs to

**What to build:** the draft route resolves the thread a reply draft is for, by exact subject and sender against the mail view, and answers with the thread's recipients and subject or a named refusal.

**Build in:** `src/agentdesk/insight/press.py`, `src/agentdesk/server/app.py`, reusing `agentdesk.mail.core.reply_recipients`/`reply_subject`.

**Blocked by:** none.

**Status:** ready-for-agent
**GitHub:** issue #138

- [ ] A `reply-draft` body may carry `subject` and `sender`; when both are present the answer gains `thread: {"id", "to", "subject"}` alongside the existing draft fields.
- [ ] Resolution is exact: subject equal to the message's thread or subject after the existing normalisation, and the sender matching the message's from (address or display name, case-insensitive). Case- and whitespace-insensitive, nothing fuzzier.
- [ ] No match answers 404 with a sentence naming the subject; more than one match answers 409 naming the senders and staging nothing; mail off or unconfigured answers 503 with the existing copy. Every refusal carries the disclosure list so a client can still show what would have been sent.
- [ ] The answer never carries a message body, and no message id is added to any dashboard payload.
- [ ] tests/test_insight_press.py gains: one match resolves and echoes recipients; two matches refuse and name both; no match refuses and names the subject; mail off refuses; a body without subject/sender keeps today's answer unchanged.
