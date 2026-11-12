"""Mail: a metadata-only digest of one .eml folder, off by default.

Header-only parsing (From, To, Cc, Subject, Date, Message-ID,
In-Reply-To), threading by In-Reply-To, follow-ups and a 24-hour
digest, handled-thread persistence, and a folder watcher on the
calendar bridge's timer pattern. Message bodies are discarded at parse
time and no LLM call exists anywhere in this package: the data-egress
rule is enforced by the shape of the Message record, not by discipline.
"""
